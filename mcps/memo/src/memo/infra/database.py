"""DB 接続とスキーマ管理 (共有インフラ)。

dynamic_prompt と同様、SQLite を WAL モードで使う。ツール呼び出しごとに
新しい接続を返す (`_connect_db`) ことで、FastMCP が複数スレッドからツールを
呼んでもスレッド安全を保つ。

**外部キーを常に有効化する** (`PRAGMA foreign_keys=ON`)。これにより親テーブル
(users / categories) の変更へ下位 (categories / memos / memo_embeddings) を
DB の仕組みで追従させる:

- ユーザー削除 → そのカテゴリ・メモ・埋め込みキャッシュをカスケード削除。
- メモ削除 → 埋め込みキャッシュをカスケード削除。
- カテゴリのリネーム/削除 → メモの ``category`` 文字列をトリガーで同期
  (リネームは付け替え、削除はユーザーごとの既定 ``OTHERS`` へ戻す)。

スキーマ変更はバージョン管理付きマイグレーション (``memo.migrations``) で行う。
新規 DB は `_create_schema` が現行 (外部キー付き) スキーマを作り、既存 (外部キー
無し) DB は ``run_migrations`` がテーブルを作り替える。SQLite は ``ALTER TABLE``
で外部キーを後付けできないため、この作り替えが必要 (詳細は migrations 参照)。

ドメインごとのデータアクセスは ``repository`` パッケージ (``repository.memo`` /
``repository.user`` / ``repository.category``) が担う。このモジュールは接続
ファクトリ・スキーマ初期化・トリガー定義・共通定数だけを持つ。
"""

import os
import sqlite3
from pathlib import Path

# __file__ = src/memo/infra/database.py → parent.parent = src/memo (memo.db の場所)。
# infra/ へ移動して1階層深くなったぶん parent.parent で従来と同じ場所を指す。
DB_PATH = Path(
    os.environ.get("MEMO_DB_PATH", str(Path(__file__).parent.parent / "memo.db"))
)

#: 全ユーザーのメモを操作できる特権ユーザー名。init_db() で必ずシードされる。
ADMIN_USER = "admin"

#: カテゴリ未指定のメモが属する既定カテゴリ。カテゴリ名は大文字に正規化して
#: 保存・照合する (repository.category.normalize_category) ため、この定数も大文字。
OTHERS_CATEGORY = "OTHERS"


def _create_schema(db: sqlite3.Connection) -> None:
    """現行スキーマ (外部キー付き) を作成する (冪等)。

    新規 DB はこれで完成形になる。既存 (外部キー無し) DB はテーブルが既に
    存在するため ``CREATE TABLE IF NOT EXISTS`` は no-op となり、マイグレーション
    (``memo.migrations``) が外部キー付きへ作り替える。
    """
    db.execute("""
        CREATE TABLE IF NOT EXISTS users (
            name         TEXT PRIMARY KEY,
            display_name TEXT NOT NULL DEFAULT '',
            note         TEXT NOT NULL DEFAULT '',
            created_at   TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at   TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    # ユーザーごとのカテゴリ台帳 (第一級の実体)。(user, name) で一意。
    # user は users(name) を参照し、ユーザー削除でカスケード削除される。
    db.execute("""
        CREATE TABLE IF NOT EXISTS categories (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            user       TEXT NOT NULL REFERENCES users(name)
                       ON DELETE CASCADE ON UPDATE CASCADE,
            name       TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE(user, name)
        )
    """)
    db.execute("CREATE INDEX IF NOT EXISTS idx_categories_user ON categories(user)")
    # メモ本体。user は users(name) を参照しユーザー削除でカスケード削除される。
    # category は文字列のまま (登録済みカテゴリかの検証は service 層)。カテゴリ
    # 名のリネーム/削除への追従はトリガー (_create_triggers) が行う。
    db.execute(f"""
        CREATE TABLE IF NOT EXISTS memos (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            user       TEXT NOT NULL REFERENCES users(name)
                       ON DELETE CASCADE ON UPDATE CASCADE,
            title      TEXT NOT NULL,
            summary    TEXT NOT NULL DEFAULT '',
            category   TEXT NOT NULL DEFAULT '{OTHERS_CATEGORY}',
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    db.execute("CREATE INDEX IF NOT EXISTS idx_memos_user ON memos(user)")
    # セマンティック検索用の埋め込みベクトルキャッシュ。memo_id ごとに1行。
    # memo_id は memos(id) を参照し、メモ削除でカスケード削除される。
    db.execute("""
        CREATE TABLE IF NOT EXISTS memo_embeddings (
            memo_id      INTEGER PRIMARY KEY REFERENCES memos(id) ON DELETE CASCADE,
            summary_hash TEXT NOT NULL,
            model        TEXT NOT NULL,
            vector       TEXT NOT NULL,
            created_at   TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    _create_triggers(db)


def _create_triggers(db: sqlite3.Connection) -> None:
    """カテゴリ変更をメモ (``memos.category`` 文字列) へ同期するトリガーを作る (冪等)。

    カテゴリは ``(user, name)`` 文字列でメモから参照されており、リネーム時の
    付け替えと削除時の「ユーザーごとの ``OTHERS`` へ戻す」振る舞いは標準の
    外部キーアクションでは表せない (削除先が行ごとに動的)。そこでトリガーで
    DB 側に持たせ、アプリの手動カスケードをなくす。
    """
    # リネーム: カテゴリ名が変わったら、そのユーザーの同名メモを新名へ付け替える。
    db.execute("""
        CREATE TRIGGER IF NOT EXISTS trg_categories_rename_cascade
        AFTER UPDATE OF name ON categories
        FOR EACH ROW WHEN OLD.name <> NEW.name
        BEGIN
            UPDATE memos SET category = NEW.name, updated_at = datetime('now')
            WHERE user = NEW.user AND category = OLD.name;
        END
    """)
    # 削除: カテゴリ削除前に、紐づくメモを既定 OTHERS へ付け替える (OTHERS 自体は
    # 対象外)。ユーザー削除に伴うカテゴリのカスケード削除でも発火するが、その場合
    # メモも別途カスケード削除されるため実害はない。
    db.execute(f"""
        CREATE TRIGGER IF NOT EXISTS trg_categories_delete_reassign
        BEFORE DELETE ON categories
        FOR EACH ROW WHEN OLD.name <> '{OTHERS_CATEGORY}'
        BEGIN
            UPDATE memos SET category = '{OTHERS_CATEGORY}', updated_at = datetime('now')
            WHERE user = OLD.user AND category = OLD.name;
        END
    """)


def _seed(db: sqlite3.Connection) -> None:
    """ブートストラップ用のシード (冪等)。

    - ユーザー管理用 ``admin`` を必ず用意する。admin はユーザー台帳を CRUD
      できるだけの通常ユーザーで、他人のメモは操作しない。
    - 全ユーザーへ既定カテゴリ ``OTHERS`` をシードし、既存メモが持つ
      ``(user, category)`` をカテゴリとして後埋めする (既存メモを有効に保つ)。
    """
    db.execute(
        "INSERT OR IGNORE INTO users (name, display_name) VALUES (?, ?)",
        (ADMIN_USER, "Administrator"),
    )
    db.execute(
        "INSERT OR IGNORE INTO categories (user, name) "
        f"SELECT name, '{OTHERS_CATEGORY}' FROM users"
    )
    db.execute(
        "INSERT OR IGNORE INTO categories (user, name) "
        "SELECT DISTINCT user, category FROM memos"
    )


def init_db() -> None:
    """スキーマ作成 + マイグレーション + シードを実行する。起動時に1回だけ呼ぶ (冪等)。

    接続はオートコミット (``isolation_level = None``) にする。マイグレーション
    (m001) がテーブル作り替えのため ``PRAGMA foreign_keys`` をトランザクション外で
    切り替え、自前で ``BEGIN``/``COMMIT`` する必要があるため。
    """
    # 遅延 import で循環参照を避ける (migrations → infra.database を import する)。
    from memo.migrations import run_migrations

    db = sqlite3.connect(DB_PATH)
    db.isolation_level = None  # オートコミット (マイグレーションの PRAGMA 切替に必要)
    try:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA foreign_keys=ON")
        _create_schema(db)
        run_migrations(db)
        _seed(db)
    finally:
        db.close()


def _connect_db() -> sqlite3.Connection:
    """毎回新しい接続を返す。呼び出し側は `with _connect_db() as db:` で使うこと。

    外部キー強制は接続ごとに有効化する必要があるため、ここで毎回
    ``PRAGMA foreign_keys=ON`` する (カスケード削除・トリガーが効くようにする)。
    """
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    return db

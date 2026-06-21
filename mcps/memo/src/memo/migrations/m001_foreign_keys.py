"""Migration 001: 外部キー (カスケード) とカテゴリ↔メモのトリガーを導入する。

ねらい: 親テーブル (users / categories) の変更に下位 (categories / memos /
memo_embeddings) を **DB の仕組みで** 必ず追従させ、アプリ側の手動カスケードを
やめる。

- ``memos.user`` / ``categories.user`` → ``users(name)``: ON DELETE CASCADE
  (ユーザー削除でメモ・カテゴリも消える) / ON UPDATE CASCADE。
- ``memo_embeddings.memo_id`` → ``memos(id)``: ON DELETE CASCADE
  (メモ削除で埋め込みキャッシュも消える)。
- カテゴリ名のリネーム/削除は ``memos.category`` (文字列) へ波及させるが、
  「削除時はユーザーごとの既定 ``OTHERS`` へ付け替え」という動的な振る舞いは
  標準の外部キーアクションでは表せないため **トリガー** で行う
  (これも手動更新ではなく DB の仕組み)。

SQLite は ``ALTER TABLE`` で外部キーを後付けできないので、既存 DB は
「新テーブル作成 → データ移送 → 旧テーブル削除 → リネーム」でテーブルを
作り替える (公式手順)。新規 DB は ``init_db`` の ``_create_schema`` で既に
外部キー付きなので、この移行はトリガーの作成だけ行ってスキップする (冪等)。
"""

import sqlite3

from memo.infra.database import OTHERS_CATEGORY, _create_triggers

VERSION = 1
DESCRIPTION = "Enable foreign-key cascades and category->memo sync triggers"


def _has_fk(db: sqlite3.Connection, table: str) -> bool:
    return bool(db.execute(f"PRAGMA foreign_key_list({table})").fetchall())


def _column_exists(db: sqlite3.Connection, table: str, column: str) -> bool:
    return any(r[1] == column for r in db.execute(f"PRAGMA table_info({table})"))


def migrate(db: sqlite3.Connection) -> None:
    """既存 DB のテーブルを外部キー付きに作り替え、トリガーを用意する。

    既に外部キーがある (新規 DB / 適用済み) 場合は作り替えをスキップし、
    トリガーの存在だけ保証する。``db`` はオートコミットであること。
    """
    if _has_fk(db, "memos") and _has_fk(db, "categories"):
        _create_triggers(db)
        return

    # かなり古い DB が user / category 列を持たない可能性に備える (防御的)。
    if not _column_exists(db, "memos", "user"):
        db.execute("ALTER TABLE memos ADD COLUMN user TEXT NOT NULL DEFAULT ''")
    if not _column_exists(db, "memos", "category"):
        db.execute(
            "ALTER TABLE memos ADD COLUMN category TEXT NOT NULL "
            f"DEFAULT '{OTHERS_CATEGORY}'"
        )

    # テーブル作り替えは外部キー強制を OFF にし、トランザクション外で PRAGMA を
    # 切り替えてから行う (PRAGMA foreign_keys はトランザクション内では無効)。
    db.execute("PRAGMA foreign_keys=OFF")
    db.execute("BEGIN")
    try:
        _drop_orphans(db)
        _rebuild_categories(db)
        _rebuild_memos(db)
        _rebuild_embeddings(db)
        _create_triggers(db)
        violations = db.execute("PRAGMA foreign_key_check").fetchall()
        if violations:
            raise sqlite3.IntegrityError(
                f"foreign_key_check failed after FK migration: {violations}"
            )
        db.execute("COMMIT")
    except Exception:
        db.execute("ROLLBACK")
        raise
    finally:
        db.execute("PRAGMA foreign_keys=ON")


def _drop_orphans(db: sqlite3.Connection) -> None:
    """親を持たない孤立行を削除する (外部キー検証を通すため + 孤立データ一掃)。

    旧スキーマは外部キーが無いため、所有者が ``users`` に居ないメモ/カテゴリ
    (例: 旧マイグレーションの ``user=''`` 行) や、実体メモを失った埋め込み
    キャッシュが残り得る。外部キー付きでは保持できないので削除する。
    """
    db.execute("DELETE FROM memos WHERE user NOT IN (SELECT name FROM users)")
    db.execute("DELETE FROM categories WHERE user NOT IN (SELECT name FROM users)")
    db.execute(
        "DELETE FROM memo_embeddings WHERE memo_id NOT IN (SELECT id FROM memos)"
    )


def _rebuild_categories(db: sqlite3.Connection) -> None:
    db.execute("""
        CREATE TABLE categories_new (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            user       TEXT NOT NULL REFERENCES users(name)
                       ON DELETE CASCADE ON UPDATE CASCADE,
            name       TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE(user, name)
        )
    """)
    db.execute(
        "INSERT INTO categories_new (id, user, name, created_at, updated_at) "
        "SELECT id, user, name, created_at, updated_at FROM categories"
    )
    db.execute("DROP TABLE categories")
    db.execute("ALTER TABLE categories_new RENAME TO categories")
    db.execute("CREATE INDEX IF NOT EXISTS idx_categories_user ON categories(user)")


def _rebuild_memos(db: sqlite3.Connection) -> None:
    db.execute(f"""
        CREATE TABLE memos_new (
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
    db.execute(
        "INSERT INTO memos_new "
        "(id, user, title, summary, category, created_at, updated_at) "
        "SELECT id, user, title, summary, category, created_at, updated_at FROM memos"
    )
    db.execute("DROP TABLE memos")
    db.execute("ALTER TABLE memos_new RENAME TO memos")
    db.execute("CREATE INDEX IF NOT EXISTS idx_memos_user ON memos(user)")


def _rebuild_embeddings(db: sqlite3.Connection) -> None:
    db.execute("""
        CREATE TABLE memo_embeddings_new (
            memo_id      INTEGER PRIMARY KEY REFERENCES memos(id) ON DELETE CASCADE,
            summary_hash TEXT NOT NULL,
            model        TEXT NOT NULL,
            vector       TEXT NOT NULL,
            created_at   TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    db.execute(
        "INSERT INTO memo_embeddings_new "
        "(memo_id, summary_hash, model, vector, created_at) "
        "SELECT memo_id, summary_hash, model, vector, created_at FROM memo_embeddings"
    )
    db.execute("DROP TABLE memo_embeddings")
    db.execute("ALTER TABLE memo_embeddings_new RENAME TO memo_embeddings")

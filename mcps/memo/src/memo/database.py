"""DB 接続とスキーマ管理 (共有インフラ)。

dynamic_prompt と同様、SQLite を WAL モードで使う。ツール呼び出しごとに
新しい接続を返す (`_connect_db`) ことで、FastMCP が複数スレッドからツールを
呼んでもスレッド安全を保つ。

ドメインごとのデータアクセスは ``repository`` パッケージ (``repository.memo`` /
``repository.user``) が担う。このモジュールは接続ファクトリ・スキーマ初期化・
共通定数だけを持つ。
"""

import os
import sqlite3
from pathlib import Path

DB_PATH = Path(os.environ.get("MEMO_DB_PATH", str(Path(__file__).parent / "memo.db")))

#: 全ユーザーのメモを操作できる特権ユーザー名。init_db() で必ずシードされる。
ADMIN_USER = "admin"


def init_db() -> None:
    """スキーマを作成する。サーバー起動時に1回だけ呼ぶ (冪等)。

    ``user`` カラムを持たない既存 DB は ``ALTER TABLE`` で移行する
    (既存メモは ``user=''`` となり、admin 以外からはアクセスできなくなる)。
    ``users`` テーブルを作成し、特権ユーザー ``admin`` をシードする。
    """
    db = sqlite3.connect(DB_PATH)
    try:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("""
            CREATE TABLE IF NOT EXISTS memos (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                user       TEXT NOT NULL,
                title      TEXT NOT NULL,
                summary    TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        # 既存 DB に user カラムが無ければ追加する (軽量マイグレーション)
        columns = {row[1] for row in db.execute("PRAGMA table_info(memos)")}
        if "user" not in columns:
            db.execute("ALTER TABLE memos ADD COLUMN user TEXT NOT NULL DEFAULT ''")
        # ユーザー単位の絞り込みを高速化する
        db.execute("CREATE INDEX IF NOT EXISTS idx_memos_user ON memos(user)")

        # 接続を許可するユーザーの台帳。name が不変の識別子、display_name と
        # note は admin が編集できる属性。
        db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                name         TEXT PRIMARY KEY,
                display_name TEXT NOT NULL DEFAULT '',
                note         TEXT NOT NULL DEFAULT '',
                created_at   TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at   TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        # 特権ユーザー admin を必ず用意する (ブートストラップ)
        db.execute(
            "INSERT OR IGNORE INTO users (name, display_name) VALUES (?, ?)",
            (ADMIN_USER, "Administrator"),
        )
        db.commit()
    finally:
        db.close()


def _connect_db() -> sqlite3.Connection:
    """毎回新しい接続を返す。呼び出し側は `with _connect_db() as db:` で使うこと。"""
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    return db

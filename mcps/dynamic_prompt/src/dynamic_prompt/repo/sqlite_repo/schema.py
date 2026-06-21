"""スキーマ作成とバージョン管理付きマイグレーション。

新しいマイグレーションを追加するには:
  1. ``_migration_NNN(db)`` 関数を定義する
  2. ``_MIGRATIONS`` リストの末尾に ``(バージョン番号, 説明, 関数)`` を追加する
バージョン番号は連番にすること。
"""

import sqlite3
from collections.abc import Callable

from dynamic_prompt.repo.sqlite_repo import connection


def _column_exists(db: sqlite3.Connection, table: str, column: str) -> bool:
    cols = db.execute(f"PRAGMA table_info({table})").fetchall()
    return any(c[1] == column for c in cols)


def _table_exists(db: sqlite3.Connection, table: str) -> bool:
    row = db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    return row is not None


# ---------------------------------------------------------------------------
# マイグレーション定義
# ---------------------------------------------------------------------------


def _migration_001(db: sqlite3.Connection) -> None:
    """既存 DB に status / reviewed_at カラムがなければ追加する。"""
    if not _column_exists(db, "unknown_words", "status"):
        db.execute(
            "ALTER TABLE unknown_words ADD COLUMN status TEXT NOT NULL DEFAULT 'unlearned'"
        )
    if not _column_exists(db, "unknown_words", "reviewed_at"):
        db.execute(
            "ALTER TABLE unknown_words ADD COLUMN reviewed_at TEXT DEFAULT NULL"
        )


def _migration_002(db: sqlite3.Connection) -> None:
    """story_topics テーブルを追加する。"""
    if not _table_exists(db, "story_topics"):
        db.execute("""
            CREATE TABLE story_topics (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                lang       TEXT NOT NULL,
                topic      TEXT NOT NULL,
                summary    TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)


def _migration_003(db: sqlite3.Connection) -> None:
    """自由回答クイズ対応: quiz_questions に question_type / model_answer / user_answer_text、
    quiz_sessions に scored_at を追加する。"""
    if _table_exists(db, "quiz_questions"):
        if not _column_exists(db, "quiz_questions", "question_type"):
            db.execute(
                "ALTER TABLE quiz_questions ADD COLUMN question_type TEXT NOT NULL DEFAULT 'mc'"
            )
        if not _column_exists(db, "quiz_questions", "model_answer"):
            db.execute(
                "ALTER TABLE quiz_questions ADD COLUMN model_answer TEXT DEFAULT NULL"
            )
        if not _column_exists(db, "quiz_questions", "user_answer_text"):
            db.execute(
                "ALTER TABLE quiz_questions ADD COLUMN user_answer_text TEXT DEFAULT NULL"
            )
    if _table_exists(db, "quiz_sessions"):
        if not _column_exists(db, "quiz_sessions", "scored_at"):
            db.execute(
                "ALTER TABLE quiz_sessions ADD COLUMN scored_at TEXT DEFAULT NULL"
            )


_MIGRATIONS: list[tuple[int, str, Callable[[sqlite3.Connection], None]]] = [
    (1, "Add status and reviewed_at to unknown_words", _migration_001),
    (2, "Add story_topics table", _migration_002),
    (3, "Add free-answer quiz support", _migration_003),
]


def _get_current_version(db: sqlite3.Connection) -> int:
    """現在のスキーマバージョンを返す。テーブルがなければ 0。"""
    if not _table_exists(db, "schema_version"):
        return 0
    row = db.execute("SELECT MAX(version) FROM schema_version").fetchone()
    return row[0] or 0


def _migrate(db: sqlite3.Connection) -> None:
    """未適用のマイグレーションを順番に実行する。"""
    db.execute("""
        CREATE TABLE IF NOT EXISTS schema_version (
            version     INTEGER PRIMARY KEY,
            description TEXT NOT NULL,
            applied_at  TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    current = _get_current_version(db)
    for version, description, func in _MIGRATIONS:
        if version > current:
            func(db)
            db.execute(
                "INSERT INTO schema_version (version, description) VALUES (?, ?)",
                (version, description),
            )
    db.commit()


def init_db() -> None:
    """スキーマ作成とマイグレーションを実行する。サーバー起動時に1回だけ呼ぶ。"""
    db = sqlite3.connect(connection.DB_PATH)
    try:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("""
            CREATE TABLE IF NOT EXISTS unknown_words (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                lang        TEXT NOT NULL,
                word        TEXT NOT NULL,
                context     TEXT,
                status      TEXT NOT NULL DEFAULT 'unlearned',
                reviewed_at TEXT DEFAULT NULL,
                created_at  TEXT NOT NULL DEFAULT (datetime('now')),
                UNIQUE(lang, word)
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS quiz_sessions (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                lang         TEXT NOT NULL,
                title        TEXT NOT NULL DEFAULT '',
                created_at   TEXT NOT NULL DEFAULT (datetime('now')),
                submitted_at TEXT DEFAULT NULL,
                scored_at    TEXT DEFAULT NULL
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS quiz_questions (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id       INTEGER NOT NULL REFERENCES quiz_sessions(id),
                question_index   INTEGER NOT NULL,
                question_text    TEXT NOT NULL,
                choices          TEXT NOT NULL DEFAULT '[]',
                correct_index    INTEGER NOT NULL DEFAULT 0,
                user_answer      INTEGER DEFAULT NULL,
                is_correct       INTEGER DEFAULT NULL,
                question_type    TEXT NOT NULL DEFAULT 'mc',
                model_answer     TEXT DEFAULT NULL,
                user_answer_text TEXT DEFAULT NULL,
                UNIQUE(session_id, question_index)
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS story_topics (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                lang       TEXT NOT NULL,
                topic      TEXT NOT NULL,
                summary    TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        _migrate(db)
    finally:
        db.close()

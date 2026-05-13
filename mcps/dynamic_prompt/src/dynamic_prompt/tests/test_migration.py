"""マイグレーションシステムの単体テスト。"""

import sqlite3
import tempfile
from pathlib import Path

from dynamic_prompt.database import (
    _column_exists,
    _get_current_version,
    _MIGRATIONS,
    _migrate,
    _table_exists,
)


def _fresh_db() -> sqlite3.Connection:
    """テスト用の一時 DB 接続を返す（ファイルベース）。"""
    path = Path(tempfile.mkdtemp()) / "test_migrate.db"
    return sqlite3.connect(str(path))


# ---------------------------------------------------------------------------
# _table_exists / _column_exists
# ---------------------------------------------------------------------------


class TestHelpers:
    def test_table_exists_true(self):
        db = _fresh_db()
        db.execute("CREATE TABLE t (id INTEGER)")
        assert _table_exists(db, "t") is True
        db.close()

    def test_table_exists_false(self):
        db = _fresh_db()
        assert _table_exists(db, "nonexistent") is False
        db.close()

    def test_column_exists_true(self):
        db = _fresh_db()
        db.execute("CREATE TABLE t (id INTEGER, name TEXT)")
        assert _column_exists(db, "t", "name") is True
        db.close()

    def test_column_exists_false(self):
        db = _fresh_db()
        db.execute("CREATE TABLE t (id INTEGER)")
        assert _column_exists(db, "t", "name") is False
        db.close()


# ---------------------------------------------------------------------------
# schema_version テーブルとバージョン管理
# ---------------------------------------------------------------------------


class TestSchemaVersion:
    def test_migrate_creates_schema_version_table(self):
        db = _fresh_db()
        db.execute("CREATE TABLE unknown_words (id INTEGER, lang TEXT, word TEXT)")
        _migrate(db)
        assert _table_exists(db, "schema_version") is True
        db.close()

    def test_initial_version_is_zero(self):
        db = _fresh_db()
        assert _get_current_version(db) == 0
        db.close()

    def test_version_after_migrate(self):
        db = _fresh_db()
        db.execute(
            "CREATE TABLE unknown_words ("
            "id INTEGER, lang TEXT, word TEXT, "
            "status TEXT DEFAULT 'unlearned', reviewed_at TEXT)"
        )
        _migrate(db)
        expected_max = max(v for v, _, _ in _MIGRATIONS)
        assert _get_current_version(db) == expected_max
        db.close()

    def test_schema_version_records_description(self):
        db = _fresh_db()
        db.execute(
            "CREATE TABLE unknown_words ("
            "id INTEGER, lang TEXT, word TEXT, "
            "status TEXT DEFAULT 'unlearned', reviewed_at TEXT)"
        )
        _migrate(db)
        rows = db.execute(
            "SELECT version, description FROM schema_version ORDER BY version"
        ).fetchall()
        assert len(rows) == len(_MIGRATIONS)
        for (ver, desc), (expected_ver, expected_desc, _) in zip(rows, _MIGRATIONS):
            assert ver == expected_ver
            assert desc == expected_desc
        db.close()

    def test_schema_version_has_applied_at(self):
        db = _fresh_db()
        db.execute("CREATE TABLE unknown_words (id INTEGER, lang TEXT, word TEXT)")
        _migrate(db)
        row = db.execute(
            "SELECT applied_at FROM schema_version WHERE version = 1"
        ).fetchone()
        assert row[0] is not None
        db.close()


# ---------------------------------------------------------------------------
# マイグレーションの冪等性
# ---------------------------------------------------------------------------


class TestMigrationIdempotency:
    def test_migrate_twice_is_safe(self):
        """_migrate を2回呼んでもエラーにならず、バージョンが重複しない。"""
        db = _fresh_db()
        db.execute("CREATE TABLE unknown_words (id INTEGER, lang TEXT, word TEXT)")
        _migrate(db)
        _migrate(db)
        count = db.execute("SELECT COUNT(*) FROM schema_version").fetchone()[0]
        assert count == len(_MIGRATIONS)
        db.close()

    def test_skips_already_applied(self):
        """既に適用済みのバージョンはスキップされる。"""
        db = _fresh_db()
        db.execute("CREATE TABLE unknown_words (id INTEGER, lang TEXT, word TEXT)")
        _migrate(db)
        v1 = _get_current_version(db)
        _migrate(db)
        v2 = _get_current_version(db)
        assert v1 == v2
        db.close()


# ---------------------------------------------------------------------------
# migration_001: status / reviewed_at カラム追加
# ---------------------------------------------------------------------------


class TestMigration001:
    def test_adds_status_column(self):
        """status カラムがない DB に追加される。"""
        db = _fresh_db()
        db.execute(
            "CREATE TABLE unknown_words (id INTEGER, lang TEXT, word TEXT, context TEXT)"
        )
        _migrate(db)
        assert _column_exists(db, "unknown_words", "status") is True
        db.close()

    def test_adds_reviewed_at_column(self):
        """reviewed_at カラムがない DB に追加される。"""
        db = _fresh_db()
        db.execute(
            "CREATE TABLE unknown_words (id INTEGER, lang TEXT, word TEXT, context TEXT)"
        )
        _migrate(db)
        assert _column_exists(db, "unknown_words", "reviewed_at") is True
        db.close()

    def test_noop_if_columns_exist(self):
        """カラムが既にある場合はエラーなくスキップされる。"""
        db = _fresh_db()
        db.execute(
            "CREATE TABLE unknown_words ("
            "id INTEGER, lang TEXT, word TEXT, "
            "status TEXT DEFAULT 'unlearned', reviewed_at TEXT)"
        )
        _migrate(db)
        assert _column_exists(db, "unknown_words", "status") is True
        assert _column_exists(db, "unknown_words", "reviewed_at") is True
        db.close()


# ---------------------------------------------------------------------------
# migration_003: 自由回答クイズ対応カラム追加
# ---------------------------------------------------------------------------


class TestMigration003:
    def _db_with_quiz_tables(self):
        db = _fresh_db()
        db.execute(
            "CREATE TABLE unknown_words ("
            "id INTEGER, lang TEXT, word TEXT, "
            "status TEXT DEFAULT 'unlearned', reviewed_at TEXT)"
        )
        db.execute(
            "CREATE TABLE quiz_sessions ("
            "id INTEGER PRIMARY KEY, lang TEXT, title TEXT, "
            "created_at TEXT, submitted_at TEXT)"
        )
        db.execute(
            "CREATE TABLE quiz_questions ("
            "id INTEGER PRIMARY KEY, session_id INTEGER, question_index INTEGER, "
            "question_text TEXT, choices TEXT, correct_index INTEGER, "
            "user_answer INTEGER, is_correct INTEGER)"
        )
        return db

    def test_adds_question_type_column(self):
        db = self._db_with_quiz_tables()
        _migrate(db)
        assert _column_exists(db, "quiz_questions", "question_type") is True
        db.close()

    def test_adds_model_answer_column(self):
        db = self._db_with_quiz_tables()
        _migrate(db)
        assert _column_exists(db, "quiz_questions", "model_answer") is True
        db.close()

    def test_adds_user_answer_text_column(self):
        db = self._db_with_quiz_tables()
        _migrate(db)
        assert _column_exists(db, "quiz_questions", "user_answer_text") is True
        db.close()

    def test_adds_scored_at_to_sessions(self):
        db = self._db_with_quiz_tables()
        _migrate(db)
        assert _column_exists(db, "quiz_sessions", "scored_at") is True
        db.close()

    def test_noop_if_columns_exist(self):
        db = self._db_with_quiz_tables()
        _migrate(db)
        _migrate(db)
        assert _column_exists(db, "quiz_questions", "question_type") is True
        assert _column_exists(db, "quiz_sessions", "scored_at") is True
        db.close()

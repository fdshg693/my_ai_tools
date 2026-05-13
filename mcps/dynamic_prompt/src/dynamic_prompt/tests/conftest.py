"""テスト共通設定。

main.py のモジュールレベル副作用（init_db, start_quiz_server）を安全にするため、
テストモジュールのインポートより先にパッチを当てる。
"""

import tempfile
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# 1. DB パスを一時ファイルに差し替え（実 DB を触らないようにする）
# ---------------------------------------------------------------------------
import dynamic_prompt.database as _db_mod

_test_db_dir = tempfile.mkdtemp()
_db_mod.DB_PATH = Path(_test_db_dir) / "test_vocab.db"

# ---------------------------------------------------------------------------
# 2. quiz_server の副作用を無効化（サーバー起動・ポート操作を防ぐ）
# ---------------------------------------------------------------------------
import dynamic_prompt.quiz_server as _qs_mod

_qs_mod.start_quiz_server = lambda *a, **kw: None  # type: ignore[assignment]
_qs_mod.push_quiz = lambda data: None  # type: ignore[assignment]
_qs_mod.get_active_port = lambda: 8765  # type: ignore[assignment]

# ---------------------------------------------------------------------------
# 3. 初回スキーマ作成（main.py インポート時の init_db はパッチ済み DB に向く）
# ---------------------------------------------------------------------------
_db_mod.init_db()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_TABLES = ("quiz_questions", "quiz_sessions", "unknown_words", "story_topics", "schema_version")


@pytest.fixture(autouse=True)
def clean_tables():
    """各テストの前にテーブルを空にする（スキーマは保持）。"""
    with _db_mod._connect_db() as db:
        for table in _TABLES:
            db.execute(f"DELETE FROM {table}")
    yield

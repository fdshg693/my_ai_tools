"""テスト共通設定。

main.py のモジュールレベル副作用（init_repo, start_quiz_server）を安全にするため、
テストモジュールのインポートより先にパッチを当てる。
"""

import tempfile
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# 1. DB パスを一時ファイルに差し替え（実 DB を触らないようにする）
#    全 SQL は repo.sqlite_repo.connection の DB_PATH を参照するため、そこを書き換える。
# ---------------------------------------------------------------------------
from dynamic_prompt.repo.sqlite_repo import connection as _conn_mod

_test_db_dir = tempfile.mkdtemp()
_conn_mod.DB_PATH = Path(_test_db_dir) / "test_vocab.db"

# ---------------------------------------------------------------------------
# 2. quiz_server の副作用を無効化（サーバー起動・ポート操作を防ぐ）
# ---------------------------------------------------------------------------
import dynamic_prompt.quiz_server as _qs_mod

_qs_mod.start_quiz_server = lambda *a, **kw: None  # type: ignore[assignment]
_qs_mod.push_quiz = lambda data: None  # type: ignore[assignment]
_qs_mod.get_active_port = lambda: 8765  # type: ignore[assignment]

# ---------------------------------------------------------------------------
# 3. リポジトリを初期化（パッチ済み DB_PATH に向けてスキーマ作成・マイグレーション）
# ---------------------------------------------------------------------------
from dynamic_prompt.repo import init_repo

init_repo("sqlite")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_TABLES = ("quiz_questions", "quiz_sessions", "unknown_words", "story_topics", "schema_version")


@pytest.fixture(autouse=True)
def clean_tables():
    """各テストの前にテーブルを空にする（スキーマは保持）。"""
    with _conn_mod._connect_db() as db:
        for table in _TABLES:
            db.execute(f"DELETE FROM {table}")
    yield

"""テスト共通設定。

main.py のモジュールレベル副作用 (init_db) を実 DB に向けないよう、
テストモジュールのインポートより先に DB パスを一時ファイルへ差し替える。
"""

import tempfile
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# 1. DB パスを一時ファイルに差し替え (実 DB を触らないようにする)
# ---------------------------------------------------------------------------
import memo.database as _db_mod

_test_db_dir = tempfile.mkdtemp()
_db_mod.DB_PATH = Path(_test_db_dir) / "test_memo.db"

# ---------------------------------------------------------------------------
# 2. 差し替えた DB パスでスキーマを作成
# ---------------------------------------------------------------------------
_db_mod.init_db()


@pytest.fixture(autouse=True)
def clean_tables():
    """各テストの前にテーブルを空にする (スキーマは保持)。

    ``users`` も空にするが、特権ユーザー ``admin`` は init_db と同じく必ず
    シードし直す (ブートストラップを保つ)。
    """
    with _db_mod._connect_db() as db:
        db.execute("DELETE FROM memos")
        db.execute("DELETE FROM memo_embeddings")
        db.execute("DELETE FROM users")
        db.execute(
            "INSERT OR IGNORE INTO users (name, display_name) VALUES (?, ?)",
            (_db_mod.ADMIN_USER, "Administrator"),
        )
    yield

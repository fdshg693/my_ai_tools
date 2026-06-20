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
import memo.infra.database as _db_mod
import memo.server.mcp.auth as _auth_mod

_test_db_dir = tempfile.mkdtemp()
_db_mod.DB_PATH = Path(_test_db_dir) / "test_memo.db"

# ---------------------------------------------------------------------------
# 2. 差し替えた DB パスでスキーマを作成
# ---------------------------------------------------------------------------
_db_mod.init_db()


@pytest.fixture(autouse=True)
def clean_tables():
    """各テストの前にテーブルを空にし、auth のプロセス状態を既定に戻す。

    ``users`` も空にするが、特権ユーザー ``admin`` は init_db と同じく必ず
    シードし直す (ブートストラップを保つ)。auth はプロセスグローバルな状態
    (トランスポート種別 / stdio ユーザー / client_id マップ) を持つので、
    テスト間でリークしないよう既定 (stdio・未設定) に戻す。
    """
    _auth_mod.set_http_transport(False)
    _auth_mod.set_stdio_user(None)
    _auth_mod._http_user_by_client.clear()
    with _db_mod._connect_db() as db:
        db.execute("DELETE FROM memos")
        db.execute("DELETE FROM memo_embeddings")
        db.execute("DELETE FROM users")
        db.execute(
            "INSERT OR IGNORE INTO users (name, display_name) VALUES (?, ?)",
            (_db_mod.ADMIN_USER, "Administrator"),
        )
    yield

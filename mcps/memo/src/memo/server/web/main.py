"""``memo-admin`` のエントリポイント。ローカル Web サーバーを起動する。

アプリ本体 (Starlette + ルートハンドラ) は ``app.py`` にあり、ここは uvicorn
での起動とバインド先 (``MEMO_ADMIN_HOST`` / ``MEMO_ADMIN_PORT``) の解決だけを担う。
"""

import logging
import os

import uvicorn

from memo.infra.database import init_db
from memo.server.web.app import create_app

logger = logging.getLogger(__name__)

DEFAULT_PORT = 8090  # memo HTTP(8080) / dynamic_prompt quiz(8765) と衝突しない既定値


def main() -> None:
    """ローカル Web サーバーを起動する。"""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    init_db()  # memo.db が無い初回でもスキーマと admin を用意する

    host = os.environ.get("MEMO_ADMIN_HOST", "127.0.0.1")
    port = int(os.environ.get("MEMO_ADMIN_PORT", str(DEFAULT_PORT)))
    if host not in ("127.0.0.1", "localhost"):
        logger.warning(
            "MEMO_ADMIN_HOST=%s で外部公開しています。この管理画面は無認証で "
            "admin を含む全ユーザーを操作できるため、前段に認証を必ず置いてください。",
            host,
        )
    logger.info("memo-admin starting on http://%s:%d", host, port)
    uvicorn.run(create_app(), host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()

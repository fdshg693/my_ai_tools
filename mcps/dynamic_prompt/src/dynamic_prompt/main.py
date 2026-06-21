"""AIに言語学習のサポートをさせるためのMCPモジュール。"""

import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from fastmcp import FastMCP
from fastmcp.server.auth.auth import AccessToken
from fastmcp.server.auth.providers.google import GoogleTokenVerifier
from starlette.responses import JSONResponse

# 環境変数を優先しつつ、mcps/dynamic_prompt/.env をフォールバックとして読み込む
# (load_dotenv は既存の環境変数を上書きしない)。database が import 時に
# 環境変数 (DB_PATH 等) を参照するため、それより前に読み込む。
# __file__ = mcps/dynamic_prompt/src/dynamic_prompt/main.py → parents[2] = mcps/dynamic_prompt
load_dotenv(Path(__file__).resolve().parents[2] / ".env")

from dynamic_prompt.repo import init_repo  # noqa: E402

logger = logging.getLogger(__name__)


class EmailAllowlistGoogleTokenVerifier(GoogleTokenVerifier):
    """Google トークン検証後に email を許可リストと照合する。

    親クラスが userinfo を取得して `claims["email"]` を埋めた上で、
    許可リストに含まれない場合は None を返す（= 認証失敗）。
    `userinfo.email` スコープが付与されていない場合も email が取れず拒否される。
    """

    def __init__(self, *, allowed_emails: set[str], **kwargs) -> None:
        super().__init__(**kwargs)
        self._allowed_emails = allowed_emails

    async def verify_token(self, token: str) -> AccessToken | None:
        access_token = await super().verify_token(token)
        if access_token is None:
            return None
        email = (access_token.claims or {}).get("email")
        if not email or email.lower() not in self._allowed_emails:
            logger.warning("Rejecting Google token: email %r not in allowlist", email)
            return None
        return access_token


mcp = FastMCP("dynamic_prompt")

import dynamic_prompt.tools  # noqa: E402, F401 — ツール登録 (side-effect import)

init_repo(os.environ.get("DATA_BACKEND", "sqlite"))  # fastmcp run 経由でも確実に実行されるようモジュールレベルで呼ぶ


@mcp.custom_route("/health", methods=["GET"])
async def health(request):
    return JSONResponse({"status": "healthy"})


def main():
    transport = os.environ.get("TRANSPORT", "stdio")
    if transport == "http":
        import asyncio
        from contextlib import asynccontextmanager

        import uvicorn
        from starlette.applications import Starlette
        from starlette.routing import Mount, Route
        from starlette.staticfiles import StaticFiles

        # クイズルートハンドラと静的ファイルディレクトリを import
        from dynamic_prompt.quiz_server import (
            homepage,
            sse_endpoint,
            pending_quiz,
            submit_answers,
            save_words,
            _STATIC_DIR,
        )
        import dynamic_prompt.quiz_server as qs

        # OAuth 認証: 環境変数が設定されていれば GoogleProvider を有効化
        google_client_id = os.environ.get("GOOGLE_CLIENT_ID")
        google_client_secret = os.environ.get("GOOGLE_CLIENT_SECRET")
        service_url = os.environ.get("SERVICE_URL", "http://localhost:8080")

        if google_client_id and google_client_secret:
            from fastmcp.server.auth.providers.google import GoogleProvider

            # email スコープを必須化して userinfo に email を含める
            required_scopes = [
                "openid",
                "https://www.googleapis.com/auth/userinfo.email",
            ]
            provider = GoogleProvider(
                client_id=google_client_id,
                client_secret=google_client_secret,
                base_url=service_url,
                required_scopes=required_scopes,
            )

            allowed_emails_env = os.environ.get("ALLOWED_EMAILS", "").strip()
            if allowed_emails_env:
                allowed = {
                    e.strip().lower()
                    for e in allowed_emails_env.split(",")
                    if e.strip()
                }
                provider._token_validator = EmailAllowlistGoogleTokenVerifier(
                    allowed_emails=allowed,
                    required_scopes=required_scopes,
                )
            else:
                logger.warning(
                    "ALLOWED_EMAILS is not set: any Google account can authenticate."
                )

            mcp.auth = provider

        # MCP の Starlette アプリを取得
        # (/mcp ルート + /health custom_route + lifespan 管理を含む)
        mcp_app = mcp.http_app(path="/mcp")

        # lifespan: MCP セッションマネージャーの初期化 + クイズキューの初期化を統合
        # 重要: mcp_app.lifespan を親アプリに渡さないと MCP が動作しない
        @asynccontextmanager
        async def combined_lifespan(app):
            # クイズキューを ASGI イベントループで初期化
            qs._quiz_queue = asyncio.Queue()
            qs._server_loop = asyncio.get_running_loop()
            # MCP セッションマネージャーの lifespan を呼び出す
            async with mcp_app.lifespan(app):
                yield

        # 統合アプリ: クイズルート (個別) + MCP アプリ (Mount)
        # Route は先にマッチされ、Mount("/") はフォールバックとして /mcp, /health 等を処理
        combined = Starlette(
            routes=[
                Route("/", homepage),
                Route("/events", sse_endpoint),
                Route("/api/pending", pending_quiz),
                Route("/api/submit", submit_answers, methods=["POST"]),
                Route("/api/save_words", save_words, methods=["POST"]),
                Mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static"),
                Mount("/", app=mcp_app),  # /mcp, /health 等をサブアプリに委譲
            ],
            lifespan=combined_lifespan,
        )

        host = os.environ.get("HOST", "0.0.0.0")
        port = int(os.environ.get("PORT", "8080"))
        uvicorn.run(combined, host=host, port=port)
    else:
        from dynamic_prompt.config import config_store
        from dynamic_prompt.quiz_server import start_quiz_server

        start_quiz_server(
            port=config_store.app_config.quiz_server_port,
            pool_size=config_store.app_config.quiz_server_port_pool_size,
        )
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()

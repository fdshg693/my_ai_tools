"""AIに言語学習のサポートをさせるためのMCPモジュール。"""

import os

from fastmcp import FastMCP
from starlette.responses import JSONResponse

from dynamic_prompt.database import init_db

mcp = FastMCP("dynamic_prompt")

import dynamic_prompt.tools  # noqa: E402, F401 — ツール登録 (side-effect import)

init_db()  # fastmcp run 経由でも確実に実行されるようモジュールレベルで呼ぶ


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
            mcp.auth = GoogleProvider(
                client_id=google_client_id,
                client_secret=google_client_secret,
                base_url=service_url,
            )

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

"""MCP サーバーの ``mcp`` インスタンスとツール登録 (副作用 import)。

``main.py`` (エントリ) と分離しているのは、ツールが ``from
memo.server.mcp.app import mcp`` でこのインスタンスを参照するためである。
ここにインスタンスとミドルウェア追加・ツール副作用 import・``init_db()`` を置き、
``main.py`` がこのモジュールを import してから ``main()`` でサーバーを起動する。
この分離で「app がツールを副作用 import / main が app を import」という
一方向の流れになり、循環 import を避けられる。
"""

from fastmcp import FastMCP
from starlette.responses import JSONResponse

from memo.infra.database import init_db
from memo.server.mcp.admin_tools import apply_server_default
from memo.server.mcp.logging_middleware import AuditLogMiddleware

mcp = FastMCP("memo")
mcp.add_middleware(AuditLogMiddleware())  # 全ツール呼び出しを横断的にログする

import memo.server.mcp.tools  # noqa: E402, F401 — ツール登録 (side-effect import)

# ツール登録後に admin タグのツールをサーバーレベルで既定無効化する。switch_user で
# admin に切り替わったセッションだけが ctx.enable_components で上書きする (admin_tools 参照)。
apply_server_default(mcp)

init_db()  # どの起動経路でも確実にスキーマを用意する


@mcp.custom_route("/health", methods=["GET"])
async def health(request):
    return JSONResponse({"status": "healthy"})

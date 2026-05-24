"""シンプルなメモ管理MCPサーバー。

タイトル・概要を持つメモを SQLite に保存し、CRUD とタイトル部分一致検索を
MCP ツールとして提供する。
"""

import os

from fastmcp import FastMCP
from starlette.responses import JSONResponse

from memo.database import init_db

mcp = FastMCP("memo")

import memo.tools  # noqa: E402, F401 — ツール登録 (side-effect import)

init_db()  # どの起動経路でも確実にスキーマを用意する


@mcp.custom_route("/health", methods=["GET"])
async def health(request):
    return JSONResponse({"status": "healthy"})


def main():
    transport = os.environ.get("TRANSPORT", "stdio")
    if transport == "http":
        host = os.environ.get("HOST", "0.0.0.0")
        port = int(os.environ.get("PORT", "8080"))
        mcp.run(transport="http", host=host, port=port, path="/mcp")
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()

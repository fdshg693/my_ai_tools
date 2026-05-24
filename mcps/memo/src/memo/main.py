"""シンプルなメモ管理MCPサーバー。

タイトル・概要を持つメモを SQLite に保存し、CRUD とタイトル部分一致検索を
MCP ツールとして提供する。
"""

import argparse
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
    parser = argparse.ArgumentParser(prog="memo", description="シンプルなメモ管理 MCP サーバー")
    parser.add_argument(
        "--user",
        default=os.environ.get("MEMO_USER"),
        help="stdio 接続時のユーザー名。このプロセスのメモはすべてこのユーザーが所有する "
        "(HTTP 接続ではクエリパラメータ ?user=NAME を使うため無視される)。",
    )
    args = parser.parse_args()

    transport = os.environ.get("TRANSPORT", "stdio")
    if transport == "http":
        host = os.environ.get("HOST", "0.0.0.0")
        port = int(os.environ.get("PORT", "8080"))
        mcp.run(transport="http", host=host, port=port, path="/mcp")
    else:
        # stdio はプロセス全体でユーザーが1人に固定される
        from memo.auth import set_stdio_user

        set_stdio_user(args.user)
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()

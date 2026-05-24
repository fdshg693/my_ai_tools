"""シンプルなメモ管理MCPサーバー。

タイトル・概要を持つメモを SQLite に保存し、CRUD とタイトル部分一致検索を
MCP ツールとして提供する。
"""

import argparse
import logging
import os
import sys

from fastmcp import FastMCP
from starlette.responses import JSONResponse

from memo.database import init_db
from memo.logging_middleware import AuditLogMiddleware

mcp = FastMCP("memo")
mcp.add_middleware(AuditLogMiddleware())  # 全ツール呼び出しを横断的にログする

import memo.tools  # noqa: E402, F401 — ツール登録 (side-effect import)

init_db()  # どの起動経路でも確実にスキーマを用意する


def _configure_logging(debug: bool) -> None:
    """memo 名前空間のログを stderr に出す。

    stdio では stdout が JSON-RPC 本体なのでログは必ず stderr へ。fastmcp は自分の
    "fastmcp" ロガーにしかハンドラを付けない (root を触らない) ため、memo.* は
    basicConfig しないと一切出力されない。
    """
    # root は常に INFO 止まり。--debug でも DEBUG にするのは memo.* だけに絞り、
    # asyncio など第三者ライブラリの DEBUG ノイズを混ぜない。
    logging.basicConfig(
        stream=sys.stderr,
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    logging.getLogger("memo").setLevel(logging.DEBUG if debug else logging.INFO)


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
    parser.add_argument(
        "--debug",
        action="store_true",
        default=os.environ.get("MEMO_LOG_DEBUG", "").lower() in ("1", "true", "yes"),
        help="セッション全体像 (request_id / 解決前後のユーザー名 / initialize 等の "
        "全メソッド) を DEBUG レベルで出力する (env MEMO_LOG_DEBUG でも可)。",
    )
    args = parser.parse_args()
    _configure_logging(args.debug)

    from memo.auth import set_http_transport, set_stdio_user

    transport = os.environ.get("TRANSPORT", "stdio")
    is_http = transport == "http"
    set_http_transport(is_http)  # トランスポート種別を起動時に一度だけ確定させる
    logging.getLogger(__name__).info(
        "memo server starting (transport=%s, debug=%s)", transport, args.debug
    )

    if is_http:
        # 既定はローカル束縛 (個人ローカル運用)。switch_user は secret なしで admin にも
        # なれるため、0.0.0.0 公開はネットワーク上の誰でも admin 化できる穴になる。
        # コンテナ運用で 0.0.0.0 が要る場合は env HOST=0.0.0.0 を明示し前段に認証を置くこと。
        host = os.environ.get("HOST", "127.0.0.1")
        port = int(os.environ.get("PORT", "8080"))
        mcp.run(transport="http", host=host, port=port, path="/mcp")
    else:
        # stdio はプロセス全体でユーザーが1人に固定される
        set_stdio_user(args.user)
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()

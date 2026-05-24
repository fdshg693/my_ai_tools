"""接続中ユーザーの識別。

ユーザーはトランスポートごとに異なる方法で渡される:

- **stdio**: サーバー起動時のコマンドライン引数 (`memo --user alice`)。
  stdio はクライアントごとにプロセスが起動するため、プロセス全体で
  ユーザーは1人に固定される。起動時に `set_stdio_user()` で記録する。
- **HTTP**: MCP エンドポイントのクエリパラメータ (`/mcp?user=alice`)。
  HTTP サーバーは複数クライアントで共有されるため、リクエストごとに
  クエリパラメータから取り出す。

ユーザーを識別できない場合は None を返す。ツール側はこれをエラーとして
拒否し、未識別のまま操作させない。
"""

from fastmcp.server.dependencies import get_http_request

_stdio_user: str | None = None


def set_stdio_user(user: str | None) -> None:
    """stdio 起動時に渡されたユーザー名を記録する。"""
    global _stdio_user
    _stdio_user = (user or "").strip() or None


def current_user() -> str | None:
    """接続中ユーザー名を返す。識別できなければ None。

    HTTP リクエストコンテキスト内ならクエリパラメータ ``user`` を、
    そうでなければ (stdio) 起動時に記録したユーザー名を返す。
    """
    try:
        request = get_http_request()
    except RuntimeError:
        # HTTP リクエストコンテキスト外 → stdio トランスポート
        return _stdio_user
    user = (request.query_params.get("user") or "").strip()
    return user or None

"""ツール呼び出しを横断的に記録する監査ログミドルウェア。

主目的は **Mcp-Session-Id がどう変化するかの可視化**。接続単位で安定する
``Mcp-Session-Id`` (HTTP ヘッダ) を毎呼び出しに添えて出すことで、再接続で
セッションが張り替わる様子と、安定鍵である自前 ``?client_id=`` との対応関係が
追える。

``Middleware.on_message`` は ``initialize`` を含む全メッセージの最外層フックなので、
ここ一箇所で tools/call も初期化もまとめて捕捉できる (各ツールには手を入れない)。

出力レベル:

- **INFO (既定)**: ``tools/call`` のときに最小1行
  ``tool=<name> user=<resolved> client_id=<id> session=<Mcp-Session-Id>``
- **DEBUG**: 全メソッドでセッション全体像
  ``method=<m> request_id=<rid> client_id=<id> raw_user=<生?user=> resolved_user=<解決後> session=<id>``

INFO / DEBUG の出し分けはロガーレベルに委譲し、明示的なフラグ分岐は書かない。
"""

import logging

from fastmcp.server.dependencies import get_http_request
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext

from memo.server.mcp.auth import current_user, transport_is_http

logger = logging.getLogger(__name__)  # "memo.logging_middleware"


def _http_fields() -> tuple[str | None, str | None, str | None]:
    """HTTP モードなら ``(client_id, raw_user, session_id)`` を返す。

    ``client_id`` / ``raw_user`` はクエリパラメータ (機能B の鍵と同一ソース)、
    ``session_id`` は ``Mcp-Session-Id`` の生ヘッダ (観測対象)。
    stdio モードでは取得しようがないので ``(None, None, None)``。
    """
    if not transport_is_http():
        return None, None, None
    request = get_http_request()
    qp = request.query_params
    client_id = (qp.get("client_id") or "").strip() or None
    raw_user = (qp.get("user") or "").strip() or None
    session_id = request.headers.get("mcp-session-id")
    return client_id, raw_user, session_id


def _safe_request_id(context: MiddlewareContext) -> str | None:
    """``request_id`` を取得する。コンテキスト未確立なら None。

    ``Context.request_id`` はリクエストコンテキスト外で RuntimeError を投げうる。
    """
    ctx = context.fastmcp_context
    if ctx is None:
        return None
    try:
        return ctx.request_id
    except RuntimeError:
        return None


class AuditLogMiddleware(Middleware):
    """全メッセージを1箇所でログする監査ミドルウェア。"""

    async def on_message(self, context: MiddlewareContext, call_next: CallNext):
        method = context.method or "unknown"
        client_id, raw_user, session_id = _http_fields()
        # current_user() は同期だが I/O を伴わない (クエリ参照 or モジュール変数) ため
        # async から直接呼んでよい。client_id の初期登録は setdefault で冪等。
        resolved_user = current_user()

        if method == "tools/call":
            tool_name = getattr(context.message, "name", None)
            logger.info(
                "tool=%s user=%s client_id=%s session=%s",
                tool_name,
                resolved_user,
                client_id,
                session_id,
            )

        logger.debug(
            "method=%s request_id=%s client_id=%s raw_user=%s resolved_user=%s session=%s",
            method,
            _safe_request_id(context),
            client_id,
            raw_user,
            resolved_user,
            session_id,
        )
        return await call_next(context)

"""接続呼び出し元の認可 (識別 → 登録チェック → admin 判定)。

メモ用ツールとユーザー管理ツールが共通で使う。ユーザーの識別は ``auth`` に、
登録判定は ``repository.user`` に委譲し、ここでは「このツール呼び出しを
許可してよいか」という認可の結論をまとめる。

- 識別できない (`--user` / `?user=` の指定が無い) → 拒否
- 識別できても ``users`` 台帳に未登録 → 拒否
- ``admin`` (``ADMIN_USER``) なら ``is_admin=True`` を返し、メモツールは全
  ユーザーのメモを、ユーザー管理ツールは台帳の操作を許可する。
"""

from memo.infra.database import ADMIN_USER
from memo.repository.user import is_registered_user
from memo.server.mcp.auth import current_user

NO_USER_ERROR = (
    "Error: user is not identified. "
    "stdio では起動引数 (--user NAME)、HTTP ではクエリパラメータ (?user=NAME) でユーザーを指定してください。"
)
ADMIN_ONLY_ERROR = "Error: this tool is admin-only."


def _not_registered_error(user: str) -> str:
    return (
        f"Error: user '{user}' is not registered. "
        "管理者 (admin) に create_user での登録を依頼してください。"
    )


def resolve_caller() -> tuple[str | None, bool, str | None]:
    """接続中ユーザーを解決し、登録済みかを確認する。

    戻り値は ``(user, is_admin, error)``。``error`` が None でなければ、
    呼び出し側のツールはそのメッセージをそのまま返して処理を中断する。
    """
    user = current_user()
    if not user:
        return None, False, NO_USER_ERROR
    if not is_registered_user(user):
        return None, False, _not_registered_error(user)
    return user, user == ADMIN_USER, None

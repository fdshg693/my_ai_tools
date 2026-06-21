"""接続呼び出し元の認可 (識別 → 登録チェック → admin 判定)。

メモ用ツールとユーザー管理ツールが共通で使う。ユーザーの識別 (名前) は ``auth``
に、台帳引きは ``repository.user`` に委譲し、ここでは「このツール呼び出しを
許可してよいか」という認可の結論をまとめる。接続は名前で識別するが、解決した
ユーザーレコード (不変の ``id`` と管理者権限 ``is_admin`` を含む) を返すので、
下位のメモ・カテゴリ操作は ``id`` でスコープできる。

- 識別できない (`--user` / `?user=` の指定が無い) → 拒否
- 識別できても ``users`` 台帳に未登録 → 拒否
- ``is_admin`` が立っていれば管理者。これは**ユーザー管理ツールの admin-only
  判定にのみ**使う (名前ではなく ``users.is_admin`` フラグで判定する)。メモ・
  カテゴリツールは ``is_admin`` を使わず常に接続ユーザー単位でスコープする
  (admin も他人のメモは操作できない)。
"""

from memo.repository.user import get_user_db
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


def resolve_caller() -> tuple[dict | None, str | None]:
    """接続中ユーザーを解決し、登録済みかを確認してユーザーレコードを返す。

    戻り値は ``(caller, error)``。``caller`` は ``users`` のレコード dict
    (``id`` / ``name`` / ``is_admin`` などを含む)。``error`` が None でなければ、
    呼び出し側のツールはそのメッセージをそのまま返して処理を中断する。
    メモ/カテゴリ操作は ``caller["id"]`` でスコープし、管理者判定は
    ``caller["is_admin"]`` で行う。
    """
    name = current_user()
    if not name:
        return None, NO_USER_ERROR
    caller = get_user_db(name)
    if caller is None:
        return None, _not_registered_error(name)
    return caller, None

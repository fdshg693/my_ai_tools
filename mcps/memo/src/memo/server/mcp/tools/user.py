"""ユーザー管理の MCP ツール定義 (主に admin 専用)。

ユーザー管理ツール (create/get/list/update/delete_user) は ``authz.resolve_caller()`` で
識別・登録を確認したうえで、``is_admin`` でなければ ``admin-only`` エラーを返す。
``name`` は不変の識別子で、更新できるのは ``display_name`` / ``note`` のみ。ユーザーを
削除してもそのユーザーのメモは残り、以後は admin だけが操作できる。

例外として ``switch_user`` は admin 専用ではなく、登録済みユーザーなら誰でも自分の接続の
現在ユーザーを切り替えられる (個人ローカル運用向け)。
"""

import json

from fastmcp import Context

from memo.infra.database import ADMIN_USER
from memo.repository.user import is_registered_user
from memo.service.category import list_categories
from memo.server.mcp.admin_tools import ADMIN_TOOL_TAG, apply_session_visibility
from memo.server.mcp.app import mcp
from memo.server.mcp.auth import (
    http_client_id,
    set_stdio_user,
    switch_http_user,
    transport_is_http,
)
from memo.server.mcp.authz import ADMIN_ONLY_ERROR, resolve_caller
from memo.service.user import (
    CannotDeleteAdmin,
    NameRequired,
    UserAlreadyExists,
    UserNotFound,
    create_user as create_user_service,
    delete_user as delete_user_service,
    get_user as get_user_service,
    list_users as list_users_service,
    update_user as update_user_service,
)


def _dump(obj) -> str:
    """結果を読みやすい JSON 文字列にして返す (日本語をエスケープしない)。"""
    return json.dumps(obj, ensure_ascii=False, indent=2)


@mcp.tool(
    description=(
        "(admin 専用) 新しいユーザーを登録する。登録されたユーザーだけが接続できる。\n\n"
        "name         : ユーザー名 (必須・一意の識別子)。\n"
        "display_name : 表示名 (任意)。\n"
        "note         : メモ・備考 (任意)。\n"
        "成功時は短いメッセージを返す。既に同名が存在すればその旨を返す。"
    ),
    tags={ADMIN_TOOL_TAG},
)
def create_user(name: str, display_name: str = "", note: str = "") -> str:
    """is_admin を確認し service.user.create_user を呼ぶ。ドメイン例外をメッセージに変換。"""
    _user, is_admin, error = resolve_caller()
    if error:
        return error
    if not is_admin:
        return ADMIN_ONLY_ERROR
    try:
        created = create_user_service(name, display_name, note)
    except NameRequired:
        return "Error: name is required."
    except UserAlreadyExists as e:
        return f"User '{e.name}' already exists."
    return f"Created user '{created['name']}'."


@mcp.tool(
    description=(
        "(admin 専用) 登録済みユーザーの一覧を名前順に取得する。\n\n"
        "ユーザーの配列を JSON で返す。"
    ),
    tags={ADMIN_TOOL_TAG},
)
def list_users() -> str:
    """is_admin を確認し service.user.list_users を返す。"""
    _user, is_admin, error = resolve_caller()
    if error:
        return error
    if not is_admin:
        return ADMIN_ONLY_ERROR
    users = list_users_service()
    if not users:
        return "No users found."
    return _dump(users)


@mcp.tool(
    description=(
        "(admin 専用) ユーザーを1件取得する。\n\n"
        "name : 取得するユーザー名。\n"
        "見つかればユーザーを JSON で返し、無ければその旨を返す。"
    ),
    tags={ADMIN_TOOL_TAG},
)
def get_user(name: str) -> str:
    """is_admin を確認し service.user.get_user を呼ぶ。UserNotFound をメッセージに変換。"""
    _user, is_admin, error = resolve_caller()
    if error:
        return error
    if not is_admin:
        return ADMIN_ONLY_ERROR
    try:
        user = get_user_service(name)
    except UserNotFound:
        return f"User '{name}' not found."
    return _dump(user)


@mcp.tool(
    description=(
        "(admin 専用) ユーザーの属性を更新する。ユーザー名 (識別子) は変更できない。\n\n"
        "name         : 更新するユーザー名。\n"
        "display_name : 新しい表示名 (省略時は変更しない)。\n"
        "note         : 新しいメモ・備考 (省略時は変更しない)。\n"
        "成功時は短いメッセージを返し、無ければその旨を返す。"
    ),
    tags={ADMIN_TOOL_TAG},
)
def update_user(name: str, display_name: str | None = None, note: str | None = None) -> str:
    """is_admin を確認し service.user.update_user を呼ぶ。name は不変、None=変更しない。"""
    _user, is_admin, error = resolve_caller()
    if error:
        return error
    if not is_admin:
        return ADMIN_ONLY_ERROR
    try:
        update_user_service(name, display_name, note)
    except UserNotFound:
        return f"User '{name}' not found."
    return f"Updated user '{name}'."


@mcp.tool(
    description=(
        "(admin 専用) ユーザーを台帳から削除する。以後そのユーザーは接続できない。\n\n"
        "name : 削除するユーザー名。\n"
        "そのユーザーのメモは削除せず残す (以後は admin だけが操作できる)。\n"
        "特権ユーザー admin 自身は削除できない。"
    ),
    tags={ADMIN_TOOL_TAG},
)
def delete_user(name: str) -> str:
    """is_admin を確認し service.user.delete_user を呼ぶ。admin 不可ガードは service 側。"""
    _user, is_admin, error = resolve_caller()
    if error:
        return error
    if not is_admin:
        return ADMIN_ONLY_ERROR
    name = name.strip()
    try:
        delete_user_service(name)
    except CannotDeleteAdmin as e:
        return f"Error: cannot delete the admin user '{e.name}'."
    except UserNotFound:
        return f"User '{name}' not found."
    return f"Deleted user '{name}'."


@mcp.tool(
    description=(
        "現在の接続ユーザーを target に切り替える (個人ローカル運用向け・admin 専用ではない)。\n\n"
        "target : 切り替え先のユーザー名 (users 台帳に登録済みであること)。\n"
        "stdio では以後この接続のメモ操作が target のものになる (サーバー再起動は不要)。\n"
        "HTTP では接続時にクエリ ?client_id= を指定している必要がある (指定が無いと\n"
        "切り替え状態を保持できない)。admin への切り替えも可能。\n"
        "成功時は、切り替え先ユーザーのメモが持つカテゴリ一覧も併せて返す\n"
        "(検索・一覧を category で絞り込む際の手掛かりになる)。\n"
        "admin に切り替えると、この接続だけでユーザー管理ツールが有効化される\n"
        "(無効化されている場合あり。env MEMO_ADMIN_TOOLS_AUTO_ENABLE)。"
    )
)
async def switch_user(target: str, ctx: Context) -> str:
    """stdio は set_stdio_user、HTTP は client_id→user マップを書き換える。

    admin 専用ではなく、登録済みなら誰でも切替可。成功メッセージに target の
    カテゴリ一覧 (service.category.list_categories) を添える。切替後、この接続だけ admin タグの
    ツールの可視性を ``apply_session_visibility`` で更新する (admin → 有効化、
    admin 以外 → 無効化)。FastMCP がこの変更で list_changed をクライアントへ自動送信する。
    """
    _user, _is_admin, error = resolve_caller()
    if error:
        return error
    target = target.strip()
    if not target:
        return "Error: target is required."
    if not is_registered_user(target):
        return f"Error: user '{target}' is not registered."

    # 切り替え先がメモを持つカテゴリ一覧を添える。admin への切り替えは全メモが対象。
    categories = list_categories(target, is_admin=target == ADMIN_USER)
    cat_note = (
        "メモのカテゴリ: " + ", ".join(categories)
        if categories
        else "(カテゴリを持つメモはまだありません)"
    )

    if not transport_is_http():
        # stdio: モジュール変数を実行時書き換え (GIL 下の単純代入で安全)
        set_stdio_user(target)
        suffix = ""
    else:
        client_id = http_client_id()
        if client_id is None:
            return (
                "Error: HTTP では接続時にクエリ ?client_id=NAME を指定してください "
                "(client_id が無いと切り替え状態を保持できません)。"
            )
        switch_http_user(client_id, target)
        suffix = f" (client_id={client_id})"

    # この接続だけ admin タグのツールの可視性を切り替える (セッションレベル可視性)。
    await apply_session_visibility(ctx, target)
    return f"Switched user to '{target}'{suffix}. {cat_note}"

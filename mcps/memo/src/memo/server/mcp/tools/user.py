"""ユーザー管理の MCP ツール定義 (主に admin 専用)。

ユーザー管理ツール (create/get/list/update/delete_user) は ``authz.resolve_caller()`` で
識別・登録を確認したうえで、``is_admin`` でなければ ``admin-only`` エラーを返す。
``name`` は不変の識別子で、更新できるのは ``display_name`` / ``note`` のみ。ユーザーを
削除してもそのユーザーのメモは残り、以後は admin だけが操作できる。

例外として ``switch_user`` は admin 専用ではなく、登録済みユーザーなら誰でも自分の接続の
現在ユーザーを切り替えられる (個人ローカル運用向け)。
"""

import json

from memo.repository.user import is_registered_user
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


@mcp.tool
def create_user(name: str, display_name: str = "", note: str = "") -> str:
    """
    (admin 専用) 新しいユーザーを登録する。登録されたユーザーだけが接続できる。

    name         : ユーザー名 (必須・一意の識別子)。
    display_name : 表示名 (任意)。
    note         : メモ・備考 (任意)。
    成功時は短いメッセージを返す。既に同名が存在すればその旨を返す。
    """
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


@mcp.tool
def list_users() -> str:
    """
    (admin 専用) 登録済みユーザーの一覧を名前順に取得する。

    ユーザーの配列を JSON で返す。
    """
    _user, is_admin, error = resolve_caller()
    if error:
        return error
    if not is_admin:
        return ADMIN_ONLY_ERROR
    users = list_users_service()
    if not users:
        return "No users found."
    return _dump(users)


@mcp.tool
def get_user(name: str) -> str:
    """
    (admin 専用) ユーザーを1件取得する。

    name : 取得するユーザー名。
    見つかればユーザーを JSON で返し、無ければその旨を返す。
    """
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


@mcp.tool
def update_user(name: str, display_name: str | None = None, note: str | None = None) -> str:
    """
    (admin 専用) ユーザーの属性を更新する。ユーザー名 (識別子) は変更できない。

    name         : 更新するユーザー名。
    display_name : 新しい表示名 (省略時は変更しない)。
    note         : 新しいメモ・備考 (省略時は変更しない)。
    成功時は短いメッセージを返し、無ければその旨を返す。
    """
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


@mcp.tool
def delete_user(name: str) -> str:
    """
    (admin 専用) ユーザーを台帳から削除する。以後そのユーザーは接続できない。

    name : 削除するユーザー名。
    そのユーザーのメモは削除せず残す (以後は admin だけが操作できる)。
    特権ユーザー admin 自身は削除できない。
    """
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


@mcp.tool
def switch_user(target: str) -> str:
    """
    現在の接続ユーザーを target に切り替える (個人ローカル運用向け・admin 専用ではない)。

    target : 切り替え先のユーザー名 (users 台帳に登録済みであること)。
    stdio では以後この接続のメモ操作が target のものになる (サーバー再起動は不要)。
    HTTP では接続時にクエリ ?client_id= を指定している必要がある (指定が無いと
    切り替え状態を保持できない)。admin への切り替えも可能。
    """
    _user, _is_admin, error = resolve_caller()
    if error:
        return error
    target = target.strip()
    if not target:
        return "Error: target is required."
    if not is_registered_user(target):
        return f"Error: user '{target}' is not registered."

    if not transport_is_http():
        # stdio: モジュール変数を実行時書き換え (GIL 下の単純代入で安全)
        set_stdio_user(target)
        return f"Switched user to '{target}'."

    client_id = http_client_id()
    if client_id is None:
        return (
            "Error: HTTP では接続時にクエリ ?client_id=NAME を指定してください "
            "(client_id が無いと切り替え状態を保持できません)。"
        )
    switch_http_user(client_id, target)
    return f"Switched user to '{target}' (client_id={client_id})."

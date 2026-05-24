"""ユーザー管理の MCP ツール定義 (admin 専用)。

各ツールは ``authz.resolve_caller()`` で識別・登録を確認したうえで、
``is_admin`` でなければ ``admin-only`` エラーを返す。``name`` は不変の識別子で、
更新できるのは ``display_name`` / ``note`` のみ。ユーザーを削除してもそのユーザーの
メモは残り、以後は admin だけが操作できる。
"""

import json

from memo.authz import ADMIN_ONLY_ERROR, resolve_caller
from memo.database import ADMIN_USER
from memo.main import mcp
from memo.repository.user import (
    create_user_db,
    delete_user_db,
    get_user_db,
    list_users_db,
    update_user_db,
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
    name = name.strip()
    if not name:
        return "Error: name is required."
    created = create_user_db(name, display_name.strip(), note.strip())
    if created is None:
        return f"User '{name}' already exists."
    return f"Created user '{name}'."


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
    users = list_users_db()
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
    user = get_user_db(name.strip())
    if user is None:
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
    updated = update_user_db(
        name.strip(),
        display_name.strip() if display_name is not None else None,
        note.strip() if note is not None else None,
    )
    if updated is None:
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
    if name == ADMIN_USER:
        return f"Error: cannot delete the admin user '{ADMIN_USER}'."
    deleted = delete_user_db(name)
    if not deleted:
        return f"User '{name}' not found."
    return f"Deleted user '{name}'."

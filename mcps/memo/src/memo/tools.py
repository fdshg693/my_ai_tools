"""メモ管理の MCP ツール定義 (CRUD + タイトル部分一致検索) と、admin 専用の
ユーザー管理ツール。

すべてのツールは接続中ユーザー (`auth.current_user`) を解決し、``users`` 台帳に
登録されているかを確認する。識別できない / 未登録の接続はエラーで拒否する。

メモ操作は原則「接続中ユーザー自身のメモ」に限られるが、特権ユーザー
``admin`` (``ADMIN_USER``) だけは全ユーザー (``user=''`` の孤立メモ含む) の
メモを操作できる。ユーザー管理ツール (``*_user``) は admin 専用。
"""

import json

from memo.auth import current_user
from memo.database import (
    ADMIN_USER,
    create_memo_db,
    create_user_db,
    delete_memo_db,
    delete_user_db,
    get_memo_db,
    get_user_db,
    is_registered_user,
    list_memos_db,
    list_users_db,
    search_memos_db,
    update_memo_db,
    update_user_db,
)
from memo.main import mcp

_NO_USER_ERROR = (
    "Error: user is not identified. "
    "stdio では起動引数 (--user NAME)、HTTP ではクエリパラメータ (?user=NAME) でユーザーを指定してください。"
)
_ADMIN_ONLY_ERROR = "Error: this tool is admin-only."


def _not_registered_error(user: str) -> str:
    return (
        f"Error: user '{user}' is not registered. "
        "管理者 (admin) に create_user での登録を依頼してください。"
    )


def _dump(obj) -> str:
    """結果を読みやすい JSON 文字列にして返す (日本語をエスケープしない)。"""
    return json.dumps(obj, ensure_ascii=False, indent=2)


def _auth() -> tuple[str | None, bool, str | None]:
    """接続中ユーザーを解決し、登録済みかを確認する。

    戻り値は ``(user, is_admin, error)``。``error`` が None でなければ、
    呼び出し側のツールはそのメッセージをそのまま返して処理を中断する。
    """
    user = current_user()
    if not user:
        return None, False, _NO_USER_ERROR
    if not is_registered_user(user):
        return None, False, _not_registered_error(user)
    return user, user == ADMIN_USER, None


# ---------------------------------------------------------------------------
# メモ管理ツール
# ---------------------------------------------------------------------------


@mcp.tool
def create_memo(title: str, summary: str = "") -> str:
    """
    新しいメモを作成する。作成者は接続中ユーザーとして記録される。

    title   : メモのタイトル (必須)。
    summary : メモの概要 (任意)。
    成功時は作成したメモの id を含む短いメッセージを返す。
    """
    user, _is_admin, error = _auth()
    if error:
        return error
    title = title.strip()
    if not title:
        return "Error: title is required."
    memo = create_memo_db(user, title, summary.strip())
    return f"Created memo id={memo['id']}."


@mcp.tool
def get_memo(memo_id: int) -> str:
    """
    ID を指定してメモを1件取得する。

    memo_id : 取得するメモの ID。
    通常は自分のメモのみ取得できる。admin は所有者を問わず取得できる。
    見つかればメモを JSON で返し、無ければその旨を返す。
    """
    user, is_admin, error = _auth()
    if error:
        return error
    memo = get_memo_db(user, memo_id, is_admin=is_admin)
    if memo is None:
        return f"Memo id={memo_id} not found."
    return _dump(memo)


@mcp.tool
def list_memos(limit: int = 50) -> str:
    """
    メモの一覧を新しい順 (更新日時の降順) に取得する。

    limit : 取得する最大件数 (デフォルト 50)。
    通常は自分のメモのみ。admin は全ユーザーのメモを取得する。
    メモの配列を JSON で返す。
    """
    user, is_admin, error = _auth()
    if error:
        return error
    memos = list_memos_db(user, limit, is_admin=is_admin)
    if not memos:
        return "No memos found."
    return _dump(memos)


@mcp.tool
def search_memos(query: str, limit: int = 50) -> str:
    """
    メモをタイトルの部分一致で検索する (大文字小文字を区別しない)。

    query : 検索キーワード。カンマ (,) 区切りで複数指定でき、いずれかに
            部分一致したメモを返す (OR 検索)。
    limit : 取得する最大件数 (デフォルト 50)。
    通常は自分のメモのみ。admin は全ユーザーのメモを対象に検索する。
    一致したメモの配列を JSON で返す。各メモは matched_keywords を持ち、
    どのキーワードに一致したかを明示する。
    """
    user, is_admin, error = _auth()
    if error:
        return error
    seen: set[str] = set()
    keywords: list[str] = []
    for part in query.split(","):
        kw = part.strip()
        if kw and kw not in seen:
            seen.add(kw)
            keywords.append(kw)
    if not keywords:
        return "Error: query is required."
    memos = search_memos_db(user, keywords, limit, is_admin=is_admin)
    if not memos:
        return f"No memos matched any of: {', '.join(keywords)}."
    return _dump(memos)


@mcp.tool
def update_memo(memo_id: int, title: str | None = None, summary: str | None = None) -> str:
    """
    メモを更新する。指定したフィールドのみ変更する。

    memo_id : 更新するメモの ID。
    title   : 新しいタイトル (省略時は変更しない)。
    summary : 新しい概要 (省略時は変更しない)。
    通常は自分のメモのみ更新できる。admin は所有者を問わず更新できる。
    成功時は短いメッセージを返し、無ければその旨を返す。
    """
    user, is_admin, error = _auth()
    if error:
        return error
    memo = update_memo_db(
        user,
        memo_id,
        title.strip() if title is not None else None,
        summary.strip() if summary is not None else None,
        is_admin=is_admin,
    )
    if memo is None:
        return f"Memo id={memo_id} not found."
    return f"Updated memo id={memo_id}."


@mcp.tool
def delete_memo(memo_id: int) -> str:
    """
    メモを削除する。

    memo_id : 削除するメモの ID。
    通常は自分のメモのみ削除できる。admin は所有者を問わず削除できる。
    """
    user, is_admin, error = _auth()
    if error:
        return error
    deleted = delete_memo_db(user, memo_id, is_admin=is_admin)
    if not deleted:
        return f"Memo id={memo_id} not found."
    return f"Deleted memo id={memo_id}."


# ---------------------------------------------------------------------------
# ユーザー管理ツール (admin 専用)
#
# 接続中ユーザーが admin でなければすべて拒否する。name は不変の識別子で、
# 更新できるのは display_name / note のみ。ユーザーを削除してもそのユーザーの
# メモは残り、admin だけが操作できる。
# ---------------------------------------------------------------------------


@mcp.tool
def create_user(name: str, display_name: str = "", note: str = "") -> str:
    """
    (admin 専用) 新しいユーザーを登録する。登録されたユーザーだけが接続できる。

    name         : ユーザー名 (必須・一意の識別子)。
    display_name : 表示名 (任意)。
    note         : メモ・備考 (任意)。
    成功時は短いメッセージを返す。既に同名が存在すればその旨を返す。
    """
    _user, is_admin, error = _auth()
    if error:
        return error
    if not is_admin:
        return _ADMIN_ONLY_ERROR
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
    _user, is_admin, error = _auth()
    if error:
        return error
    if not is_admin:
        return _ADMIN_ONLY_ERROR
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
    _user, is_admin, error = _auth()
    if error:
        return error
    if not is_admin:
        return _ADMIN_ONLY_ERROR
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
    _user, is_admin, error = _auth()
    if error:
        return error
    if not is_admin:
        return _ADMIN_ONLY_ERROR
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
    _user, is_admin, error = _auth()
    if error:
        return error
    if not is_admin:
        return _ADMIN_ONLY_ERROR
    name = name.strip()
    if name == ADMIN_USER:
        return f"Error: cannot delete the admin user '{ADMIN_USER}'."
    deleted = delete_user_db(name)
    if not deleted:
        return f"User '{name}' not found."
    return f"Deleted user '{name}'."

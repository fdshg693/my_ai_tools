"""メモ管理の MCP ツール定義 (CRUD + タイトル部分一致検索)。

すべてのツールは接続中ユーザー (`auth.current_user`) を解決し、その
ユーザーが所有するメモだけを操作する。他ユーザーのメモは読み取りも含めて
一切操作できず、対象 ID が他人のものなら「存在しない」ものとして扱う。
ユーザーを識別できない接続はエラーで拒否する。
"""

import json

from memo.auth import current_user
from memo.database import (
    create_memo_db,
    delete_memo_db,
    get_memo_db,
    list_memos_db,
    search_memos_db,
    update_memo_db,
)
from memo.main import mcp

_NO_USER_ERROR = (
    "Error: user is not identified. "
    "stdio では起動引数 (--user NAME)、HTTP ではクエリパラメータ (?user=NAME) でユーザーを指定してください。"
)


def _dump(obj) -> str:
    """結果を読みやすい JSON 文字列にして返す (日本語をエスケープしない)。"""
    return json.dumps(obj, ensure_ascii=False, indent=2)


@mcp.tool
def create_memo(title: str, summary: str = "") -> str:
    """
    新しいメモを作成する。作成者は接続中ユーザーとして記録される。

    title   : メモのタイトル (必須)。
    summary : メモの概要 (任意)。
    成功時は作成したメモの id を含む短いメッセージを返す。
    """
    user = current_user()
    if not user:
        return _NO_USER_ERROR
    title = title.strip()
    if not title:
        return "Error: title is required."
    memo = create_memo_db(user, title, summary.strip())
    return f"Created memo id={memo['id']}."


@mcp.tool
def get_memo(memo_id: int) -> str:
    """
    ID を指定して自分のメモを1件取得する。

    memo_id : 取得するメモの ID。
    見つかればメモを JSON で返し、自分のメモでない/無ければその旨を返す。
    """
    user = current_user()
    if not user:
        return _NO_USER_ERROR
    memo = get_memo_db(user, memo_id)
    if memo is None:
        return f"Memo id={memo_id} not found."
    return _dump(memo)


@mcp.tool
def list_memos(limit: int = 50) -> str:
    """
    自分のメモの一覧を新しい順 (更新日時の降順) に取得する。

    limit : 取得する最大件数 (デフォルト 50)。
    メモの配列を JSON で返す。
    """
    user = current_user()
    if not user:
        return _NO_USER_ERROR
    memos = list_memos_db(user, limit)
    if not memos:
        return "No memos found."
    return _dump(memos)


@mcp.tool
def search_memos(query: str, limit: int = 50) -> str:
    """
    自分のメモをタイトルの部分一致で検索する (大文字小文字を区別しない)。

    query : 検索キーワード。カンマ (,) 区切りで複数指定でき、いずれかに
            部分一致したメモを返す (OR 検索)。
    limit : 取得する最大件数 (デフォルト 50)。
    一致したメモの配列を JSON で返す。各メモは matched_keywords を持ち、
    どのキーワードに一致したかを明示する。
    """
    user = current_user()
    if not user:
        return _NO_USER_ERROR
    seen: set[str] = set()
    keywords: list[str] = []
    for part in query.split(","):
        kw = part.strip()
        if kw and kw not in seen:
            seen.add(kw)
            keywords.append(kw)
    if not keywords:
        return "Error: query is required."
    memos = search_memos_db(user, keywords, limit)
    if not memos:
        return f"No memos matched any of: {', '.join(keywords)}."
    return _dump(memos)


@mcp.tool
def update_memo(memo_id: int, title: str | None = None, summary: str | None = None) -> str:
    """
    自分のメモを更新する。指定したフィールドのみ変更する。

    memo_id : 更新するメモの ID。
    title   : 新しいタイトル (省略時は変更しない)。
    summary : 新しい概要 (省略時は変更しない)。
    成功時は短いメッセージを返し、自分のメモでない/無ければその旨を返す。
    """
    user = current_user()
    if not user:
        return _NO_USER_ERROR
    memo = update_memo_db(
        user,
        memo_id,
        title.strip() if title is not None else None,
        summary.strip() if summary is not None else None,
    )
    if memo is None:
        return f"Memo id={memo_id} not found."
    return f"Updated memo id={memo_id}."


@mcp.tool
def delete_memo(memo_id: int) -> str:
    """
    自分のメモを削除する。

    memo_id : 削除するメモの ID。
    """
    user = current_user()
    if not user:
        return _NO_USER_ERROR
    deleted = delete_memo_db(user, memo_id)
    if not deleted:
        return f"Memo id={memo_id} not found."
    return f"Deleted memo id={memo_id}."

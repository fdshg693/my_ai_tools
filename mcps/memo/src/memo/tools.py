"""メモ管理の MCP ツール定義 (CRUD + タイトル部分一致検索)。"""

import json

from memo.database import (
    create_memo_db,
    delete_memo_db,
    get_memo_db,
    list_memos_db,
    search_memos_db,
    update_memo_db,
)
from memo.main import mcp


def _dump(obj) -> str:
    """結果を読みやすい JSON 文字列にして返す (日本語をエスケープしない)。"""
    return json.dumps(obj, ensure_ascii=False, indent=2)


@mcp.tool
def create_memo(title: str, summary: str = "") -> str:
    """
    新しいメモを作成する。

    title   : メモのタイトル (必須)。
    summary : メモの概要 (任意)。
    作成されたメモ (id・title・summary・作成/更新日時) を JSON で返す。
    """
    title = title.strip()
    if not title:
        return "Error: title is required."
    memo = create_memo_db(title, summary.strip())
    return _dump(memo)


@mcp.tool
def get_memo(memo_id: int) -> str:
    """
    ID を指定してメモを1件取得する。

    memo_id : 取得するメモの ID。
    見つかればメモを JSON で返し、無ければその旨を返す。
    """
    memo = get_memo_db(memo_id)
    if memo is None:
        return f"Memo id={memo_id} not found."
    return _dump(memo)


@mcp.tool
def list_memos(limit: int = 50) -> str:
    """
    メモの一覧を新しい順 (更新日時の降順) に取得する。

    limit : 取得する最大件数 (デフォルト 50)。
    メモの配列を JSON で返す。
    """
    memos = list_memos_db(limit)
    if not memos:
        return "No memos found."
    return _dump(memos)


@mcp.tool
def search_memos(query: str, limit: int = 50) -> str:
    """
    タイトルの部分一致でメモを検索する (大文字小文字を区別しない)。

    query : タイトルに含まれる文字列。
    limit : 取得する最大件数 (デフォルト 50)。
    一致したメモの配列を JSON で返す。
    """
    query = query.strip()
    if not query:
        return "Error: query is required."
    memos = search_memos_db(query, limit)
    if not memos:
        return f"No memos matched title containing '{query}'."
    return _dump(memos)


@mcp.tool
def update_memo(memo_id: int, title: str | None = None, summary: str | None = None) -> str:
    """
    既存のメモを更新する。指定したフィールドのみ変更する。

    memo_id : 更新するメモの ID。
    title   : 新しいタイトル (省略時は変更しない)。
    summary : 新しい概要 (省略時は変更しない)。
    更新後のメモを JSON で返し、対象が無ければその旨を返す。
    """
    memo = update_memo_db(
        memo_id,
        title.strip() if title is not None else None,
        summary.strip() if summary is not None else None,
    )
    if memo is None:
        return f"Memo id={memo_id} not found."
    return _dump(memo)


@mcp.tool
def delete_memo(memo_id: int) -> str:
    """
    メモを削除する。

    memo_id : 削除するメモの ID。
    """
    deleted = delete_memo_db(memo_id)
    if not deleted:
        return f"Memo id={memo_id} not found."
    return f"Deleted memo id={memo_id}."

"""メモ管理の MCP ツール定義 (CRUD + タイトル部分一致検索 + セマンティック検索)。

各ツールは冒頭で ``authz.resolve_caller()`` を呼び、識別・登録チェックを通過した
``(user, is_admin)`` を得る。``error`` があればそのまま返して中断する。
メモ操作は原則「接続中ユーザー自身のメモ」に限られるが、admin は ``is_admin`` を
repository へ渡すことで全ユーザー (``user=''`` の孤立メモ含む) のメモを操作できる。
"""

import json

from memo.authz import resolve_caller
from memo.embedding import EmbeddingError
from memo.main import mcp
from memo.repository.memo import (
    create_memo_db,
    delete_memo_db,
    get_memo_db,
    list_memos_db,
    search_memos_db,
    update_memo_db,
)
from memo.service import semantic_search


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
    user, _is_admin, error = resolve_caller()
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
    user, is_admin, error = resolve_caller()
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
    user, is_admin, error = resolve_caller()
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
    user, is_admin, error = resolve_caller()
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
def semantic_search_memos(query: str, limit: int = 5) -> str:
    """
    メモを概要 (summary) の意味的な近さで検索する (セマンティック検索)。

    query : 検索したい内容を表す文字列 (自然文で可)。
    limit : 返す最大件数 (デフォルト 5)。
    タイトル部分一致の search_memos と違い、概要の内容が query に意味的に
    近いメモを類似度の高い順に返す。各メモには query との類似度
    (similarity, 0〜1) を付与する。概要が空のメモは対象外。
    通常は自分のメモのみ、admin は全ユーザーのメモを対象にする。
    埋め込みに OpenAI API を使うため環境変数 OPENAI_API_KEY が必要。
    """
    user, is_admin, error = resolve_caller()
    if error:
        return error
    query = query.strip()
    if not query:
        return "Error: query is required."
    try:
        results = semantic_search(user, query, limit, is_admin=is_admin)
    except EmbeddingError as e:
        return f"Error: {e}"
    if not results:
        return "No memos to rank (概要を持つメモがありません)。"
    return _dump(results)


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
    user, is_admin, error = resolve_caller()
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
    user, is_admin, error = resolve_caller()
    if error:
        return error
    deleted = delete_memo_db(user, memo_id, is_admin=is_admin)
    if not deleted:
        return f"Memo id={memo_id} not found."
    return f"Deleted memo id={memo_id}."

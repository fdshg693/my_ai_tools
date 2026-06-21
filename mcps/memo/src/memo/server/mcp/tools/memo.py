"""メモ管理の MCP ツール定義 (CRUD + タイトル部分一致検索 + セマンティック検索)。

各ツールは冒頭で ``authz.resolve_caller()`` を呼び、識別・登録チェックを通過した
``(user, is_admin)`` を得る。``error`` があればそのまま返して中断する。
メモ操作は原則「接続中ユーザー自身のメモ」に限られるが、admin は ``is_admin`` を
repository へ渡すことで全ユーザー (``user=''`` の孤立メモ含む) のメモを操作できる。
"""

import json

from memo.infra.embedding import EmbeddingError
from memo.server.mcp.app import mcp
from memo.server.mcp.authz import resolve_caller
from memo.service.memo import (
    TitleRequired,
    semantic_search,
    create_memo as create_memo_service,
    delete_memo as delete_memo_service,
    get_memo as get_memo_service,
    list_memos as list_memos_service,
    search_memos as search_memos_service,
    update_memo as update_memo_service,
)


def _dump(obj) -> str:
    """結果を読みやすい JSON 文字列にして返す (日本語をエスケープしない)。"""
    return json.dumps(obj, ensure_ascii=False, indent=2)


@mcp.tool(
    description=(
        "新しいメモを作成する。作成者は接続中ユーザーとして記録される。\n\n"
        "title    : メモのタイトル (必須)。\n"
        "summary  : メモの概要 (任意)。\n"
        "category : メモのカテゴリ (任意)。省略すると OTHERS に分類される。\n"
        "           カテゴリ名は大文字に正規化して保存される (work→WORK)。\n"
        "成功時は作成したメモの id を含む短いメッセージを返す。"
    )
)
def create_memo(title: str, summary: str = "", category: str = "") -> str:
    """resolve_caller() の接続ユーザーを所有者として service.create_memo に渡す。

    title 必須 (空なら ``TitleRequired``) と category 正規化 (空→OTHERS) は
    service / repository 側で行う。
    """
    user, _is_admin, error = resolve_caller()
    if error:
        return error
    try:
        memo = create_memo_service(user, title, summary, category)
    except TitleRequired:
        return "Error: title is required."
    return f"Created memo id={memo['id']} (category={memo['category']})."


@mcp.tool(
    description=(
        "ID を指定してメモを1件取得する。\n\n"
        "memo_id : 取得するメモの ID。\n"
        "通常は自分のメモのみ取得できる。admin は所有者を問わず取得できる。\n"
        "見つかればメモを JSON で返し、無ければその旨を返す。"
    )
)
def get_memo(memo_id: int) -> str:
    """is_admin を repository へ渡し、admin は所有者を問わず参照する。"""
    user, is_admin, error = resolve_caller()
    if error:
        return error
    memo = get_memo_service(user, memo_id, is_admin=is_admin)
    if memo is None:
        return f"Memo id={memo_id} not found."
    return _dump(memo)


@mcp.tool(
    description=(
        "メモの一覧を新しい順 (更新日時の降順) に取得する。\n\n"
        "limit    : 取得する最大件数 (デフォルト 50)。\n"
        "category : カテゴリ (任意)。指定すると同一カテゴリのメモだけに絞る\n"
        "           (省略すると全カテゴリ)。大文字小文字は区別しない。\n"
        "通常は自分のメモのみ。admin は全ユーザーのメモを取得する。\n"
        "メモの配列を JSON で返す。"
    )
)
def list_memos(limit: int = 50, category: str = "") -> str:
    """category.strip() or None を filter として渡す。admin は is_admin で全件。"""
    user, is_admin, error = resolve_caller()
    if error:
        return error
    memos = list_memos_service(
        user, limit, is_admin=is_admin, category=category.strip() or None
    )
    if not memos:
        return "No memos found."
    return _dump(memos)


@mcp.tool(
    description=(
        "メモをタイトルの部分一致で検索する (大文字小文字を区別しない)。\n\n"
        "query    : 検索キーワード。カンマ (,) 区切りで複数指定でき、いずれかに\n"
        "           部分一致したメモを返す (OR 検索)。\n"
        "limit    : 取得する最大件数 (デフォルト 50)。\n"
        "category : カテゴリ (任意)。指定すると同一カテゴリのメモだけに絞る\n"
        "           (省略すると全カテゴリ)。大文字小文字は区別しない。\n"
        "通常は自分のメモのみ。admin は全ユーザーのメモを対象に検索する。\n"
        "一致したメモの配列を JSON で返す。各メモは matched_keywords を持ち、\n"
        "どのキーワードに一致したかを明示する。"
    )
)
def search_memos(query: str, limit: int = 50, category: str = "") -> str:
    """query をカンマ分割し重複除去したキーワード列で部分一致検索 (service 経由)。"""
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
    memos = search_memos_service(
        user, keywords, limit, is_admin=is_admin, category=category.strip() or None
    )
    if not memos:
        return f"No memos matched any of: {', '.join(keywords)}."
    return _dump(memos)


@mcp.tool(
    description=(
        "メモを概要 (summary) の意味的な近さで検索する (セマンティック検索)。\n\n"
        "query    : 検索したい内容を表す文字列 (自然文で可)。\n"
        "limit    : 返す最大件数 (デフォルト 5)。\n"
        "category : カテゴリ (任意)。指定すると同一カテゴリのメモだけを対象にする\n"
        "           (省略すると全カテゴリ)。大文字小文字は区別しない。\n"
        "タイトル部分一致の search_memos と違い、概要の内容が query に意味的に\n"
        "近いメモを類似度の高い順に返す。各メモには query との類似度\n"
        "(similarity, 0〜1) を付与する。概要が空のメモは対象外。\n"
        "通常は自分のメモのみ、admin は全ユーザーのメモを対象にする。\n"
        "埋め込みに OpenAI API を使うため環境変数 OPENAI_API_KEY が必要。"
    )
)
def semantic_search_memos(query: str, limit: int = 5, category: str = "") -> str:
    """service.memo.semantic_search を呼び、EmbeddingError を Error 文字列に変換する。

    network を伴うのはこの経路のみ (repository は SQLite のみ)。
    """
    user, is_admin, error = resolve_caller()
    if error:
        return error
    query = query.strip()
    if not query:
        return "Error: query is required."
    try:
        results = semantic_search(
            user, query, limit, is_admin=is_admin, category=category.strip() or None
        )
    except EmbeddingError as e:
        return f"Error: {e}"
    if not results:
        return "No memos to rank (概要を持つメモがありません)。"
    return _dump(results)


@mcp.tool(
    description=(
        "メモを更新する。指定したフィールドのみ変更する。\n\n"
        "memo_id  : 更新するメモの ID。\n"
        "title    : 新しいタイトル (省略時は変更しない)。\n"
        "summary  : 新しい概要 (省略時は変更しない)。\n"
        "category : 新しいカテゴリ (省略時は変更しない)。空文字を渡すと OTHERS に戻る。\n"
        "           カテゴリ名は大文字に正規化される。\n"
        "通常は自分のメモのみ更新できる。admin は所有者を問わず更新できる。\n"
        "成功時は短いメッセージを返し、無ければその旨を返す。"
    )
)
def update_memo(
    memo_id: int,
    title: str | None = None,
    summary: str | None = None,
    category: str | None = None,
) -> str:
    """指定フィールドのみ更新。title 必須チェック (空→TitleRequired) と trim は service、
    category の None=変更しない / 空文字=OTHERS は repository 側。

    is_admin を service/repository へ渡し、admin は所有者を問わず更新する。
    """
    user, is_admin, error = resolve_caller()
    if error:
        return error
    try:
        memo = update_memo_service(
            user,
            memo_id,
            title,
            summary,
            is_admin=is_admin,
            category=category,  # None=変更しない / "" は repository が OTHERS に正規化
        )
    except TitleRequired:
        return "Error: title is required."
    if memo is None:
        return f"Memo id={memo_id} not found."
    return f"Updated memo id={memo_id}."


@mcp.tool(
    description=(
        "メモを削除する。\n\n"
        "memo_id : 削除するメモの ID。\n"
        "通常は自分のメモのみ削除できる。admin は所有者を問わず削除できる。"
    )
)
def delete_memo(memo_id: int) -> str:
    """is_admin を repository へ渡し、admin は所有者を問わず削除する。"""
    user, is_admin, error = resolve_caller()
    if error:
        return error
    deleted = delete_memo_service(user, memo_id, is_admin=is_admin)
    if not deleted:
        return f"Memo id={memo_id} not found."
    return f"Deleted memo id={memo_id}."

"""メモのドメイン操作 (CRUD オーケストレーション + セマンティック検索)。

トランスポート端 (MCP ツール / Web UI) は ``repository.memo`` を直接呼ばず、
必ずこの service 層を経由する (エッジ → service → repository の一方向)。
plain CRUD は薄いラッパだが、両エッジに重複していたドメイン不変条件
(title 必須 + trim) をここ一箇所に集約し、``TitleRequired`` を送出する
(``service.user`` の ``NameRequired`` と同じ方針)。各エッジはこの例外を自分の
表現へ翻訳する (MCP → メッセージ文字列 / Web → HTTP 400)。

repository 層は純粋な SQLite アクセスに保つため、ネットワーク呼び出し
(``embed_text``) と類似度計算・並べ替え (セマンティック検索) もこの service 層に
置く。``category`` の正規化 (空→OTHERS) は repository 側 (``normalize_category``)
が担うので、ここでは category を素通しする。認可 (admin 判定) はここに入れない
(呼び出し元が解決した ``is_admin`` を受け取るだけ)。

依存方向: ``tools`` / ``web`` → ``service`` → ``repository`` / ``embedding`` 。
"""

import hashlib
import math

from memo.infra.embedding import MODEL, embed_text
from memo.repository.embedding import get_cached_embedding, upsert_embedding
from memo.repository.memo import (
    count_memos_db,
    create_memo_db,
    delete_memo_db,
    get_memo_db,
    list_memos_db,
    search_memos_db,
    update_memo_db,
)

#: ランキング対象に取り込むメモの上限 (更新日時の新しい順)。
_CANDIDATE_CAP = 1000


class MemoError(Exception):
    """メモ操作のドメイン例外の基底。"""


class TitleRequired(MemoError):
    """``title`` が空 (trim 後) のときに送出する。"""


def create_memo(
    user: str, title: str, summary: str = "", category: str | None = None
) -> dict:
    """メモを新規作成して作成レコードを返す。所有者は ``user``。

    ``title`` 必須 (trim 後に空なら ``TitleRequired``)。``summary`` は trim する。
    ``category`` は repository が正規化する (未指定/空 → ``OTHERS``)。
    """
    title = title.strip()
    if not title:
        raise TitleRequired()
    return create_memo_db(user, title, summary.strip(), category)


def get_memo(user: str, memo_id: int, is_admin: bool = False) -> dict | None:
    """ID でメモを1件取得する (所有者外/不在は ``None``、admin は所有者を問わない)。"""
    return get_memo_db(user, memo_id, is_admin=is_admin)


def list_memos(
    user: str,
    limit: int = 50,
    is_admin: bool = False,
    offset: int = 0,
    category: str | None = None,
) -> list[dict]:
    """メモを新しい順に取得する (user 絞り込み・admin・category・paging は repository)。"""
    return list_memos_db(
        user, limit=limit, is_admin=is_admin, offset=offset, category=category
    )


def count_memos(
    user: str, is_admin: bool = False, category: str | None = None
) -> int:
    """メモの総件数を返す (ページング用)。"""
    return count_memos_db(user, is_admin=is_admin, category=category)


def search_memos(
    user: str,
    keywords: list[str],
    limit: int = 50,
    is_admin: bool = False,
    category: str | None = None,
) -> list[dict]:
    """タイトル部分一致でメモを検索する (キーワードの OR、各メモに matched_keywords)。"""
    return search_memos_db(
        user, keywords, limit, is_admin=is_admin, category=category
    )


def update_memo(
    user: str,
    memo_id: int,
    title: str | None = None,
    summary: str | None = None,
    is_admin: bool = False,
    category: str | None = None,
) -> dict | None:
    """メモを部分更新して更新後レコードを返す (対象が無ければ ``None``)。

    ``title`` を指定 (``None`` でない) した場合は trim し、空なら ``TitleRequired``。
    ``summary`` を指定した場合は trim する。いずれも ``None`` は「変更しない」。
    ``category`` の None=変更しない / 空文字=OTHERS は repository が解釈する。
    """
    if title is not None:
        title = title.strip()
        if not title:
            raise TitleRequired()
    if summary is not None:
        summary = summary.strip()
    return update_memo_db(
        user, memo_id, title, summary, is_admin=is_admin, category=category
    )


def delete_memo(user: str, memo_id: int, is_admin: bool = False) -> bool:
    """メモを削除する (削除できたら True、対象が無ければ False)。"""
    return delete_memo_db(user, memo_id, is_admin=is_admin)


def _cosine(a: list[float], b: list[float]) -> float:
    """2ベクトルのコサイン類似度。いずれかがゼロベクトルなら 0.0。"""
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def _summary_hash(summary: str) -> str:
    """概要テキストのハッシュ (キャッシュの鮮度判定に使う)。"""
    return hashlib.sha256(summary.encode("utf-8")).hexdigest()


def _embedding_for_memo(memo: dict) -> list[float]:
    """メモの概要の埋め込みを返す。キャッシュが古い/無ければ計算して保存する。"""
    summary_hash = _summary_hash(memo["summary"])
    cached = get_cached_embedding(memo["id"])
    if cached and cached["summary_hash"] == summary_hash and cached["model"] == MODEL:
        return cached["vector"]
    vector = embed_text(memo["summary"])
    upsert_embedding(memo["id"], summary_hash, MODEL, vector)
    return vector


def semantic_search(
    user: str,
    query: str,
    limit: int = 5,
    is_admin: bool = False,
    category: str | None = None,
) -> list[dict]:
    """概要 (summary) の意味的な近さでメモを検索し、類似度の高い順に返す。

    通常は ``user`` のメモのみ、``is_admin=True`` なら全ユーザーのメモが対象
    (user 絞り込み・admin 挙動は ``list_memos_db`` に集約)。``category`` を渡すと
    同一カテゴリのメモだけを対象にする (``None`` は全カテゴリ)。概要が空のメモは
    対象外。各メモには query との ``similarity`` (0〜1) を付与する。
    埋め込み API の失敗は ``EmbeddingError`` がそのまま伝播する。
    """
    query_vec = embed_text(query)
    candidates = list_memos_db(
        user, limit=_CANDIDATE_CAP, is_admin=is_admin, category=category
    )

    scored: list[dict] = []
    for memo in candidates:
        if not memo["summary"].strip():
            continue
        scored_memo = dict(memo)
        scored_memo["similarity"] = round(
            _cosine(query_vec, _embedding_for_memo(memo)), 6
        )
        scored.append(scored_memo)

    scored.sort(key=lambda m: m["similarity"], reverse=True)
    return scored[:limit]

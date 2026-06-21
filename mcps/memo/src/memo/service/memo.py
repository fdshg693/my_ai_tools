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
が担う。ただし「メモは自分の登録済みカテゴリにしか紐づけられない」という
クロス実体のドメイン不変条件はここで検証する (未登録カテゴリは ``UnknownCategory``)。
メモはユーザー単位で完全に分離され、admin も他人のメモは操作できない
(``is_admin`` の横断挙動は持たない)。

依存方向: ``tools`` / ``web`` → ``service`` → ``repository`` / ``embedding`` 。
"""

import hashlib
import math

from memo.infra.database import OTHERS_CATEGORY
from memo.infra.embedding import MODEL, embed_text
from memo.repository.category import category_exists_db, normalize_category
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


class UnknownCategory(MemoError):
    """指定カテゴリがそのユーザーに登録されていないときに送出する。"""

    def __init__(self, category: str):
        self.category = category
        super().__init__(f"category '{category}' is not registered")


def _require_known_category(user_id: int, category: str | None) -> None:
    """``category`` がそのユーザーの登録済みカテゴリであることを確認する。

    正規化後が ``OTHERS`` (既定・常に存在) の場合は検証不要。それ以外で
    未登録なら ``UnknownCategory`` を送出する。``None`` の判定は呼び出し側で行う。
    """
    normalized = normalize_category(category)
    if normalized == OTHERS_CATEGORY:
        return
    if not category_exists_db(user_id, normalized):
        raise UnknownCategory(normalized)


def create_memo(
    user_id: int, title: str, summary: str = "", category: str | None = None
) -> dict:
    """メモを新規作成して作成レコードを返す。所有者は ``user_id``。

    ``title`` 必須 (trim 後に空なら ``TitleRequired``)。``summary`` は trim する。
    ``category`` は repository が正規化する (未指定/空 → ``OTHERS``)。指定カテゴリ
    がそのユーザーに未登録なら ``UnknownCategory`` (先にカテゴリ作成が必要)。
    """
    title = title.strip()
    if not title:
        raise TitleRequired()
    _require_known_category(user_id, category)
    return create_memo_db(user_id, title, summary.strip(), category)


def get_memo(user_id: int, memo_id: int) -> dict | None:
    """ID でメモを1件取得する (所有者外/不在は ``None``)。"""
    return get_memo_db(user_id, memo_id)


def list_memos(
    user_id: int,
    limit: int = 50,
    offset: int = 0,
    category: str | None = None,
) -> list[dict]:
    """メモを新しい順に取得する (user_id 絞り込み・category・paging は repository)。"""
    return list_memos_db(user_id, limit=limit, offset=offset, category=category)


def count_memos(user_id: int, category: str | None = None) -> int:
    """メモの総件数を返す (ページング用)。"""
    return count_memos_db(user_id, category=category)


def search_memos(
    user_id: int,
    keywords: list[str],
    limit: int = 50,
    category: str | None = None,
) -> list[dict]:
    """タイトル部分一致でメモを検索する (キーワードの OR、各メモに matched_keywords)。"""
    return search_memos_db(user_id, keywords, limit, category=category)


def update_memo(
    user_id: int,
    memo_id: int,
    title: str | None = None,
    summary: str | None = None,
    category: str | None = None,
) -> dict | None:
    """メモを部分更新して更新後レコードを返す (対象が無ければ ``None``)。

    ``title`` を指定 (``None`` でない) した場合は trim し、空なら ``TitleRequired``。
    ``summary`` を指定した場合は trim する。いずれも ``None`` は「変更しない」。
    ``category`` の None=変更しない / 空文字=OTHERS は repository が解釈する。
    ``category`` を指定し未登録 (OTHERS 以外) なら ``UnknownCategory``。
    """
    if title is not None:
        title = title.strip()
        if not title:
            raise TitleRequired()
    if summary is not None:
        summary = summary.strip()
    if category is not None:
        _require_known_category(user_id, category)
    return update_memo_db(user_id, memo_id, title, summary, category=category)


def delete_memo(user_id: int, memo_id: int) -> bool:
    """メモを削除する (削除できたら True、対象が無ければ False)。"""
    return delete_memo_db(user_id, memo_id)


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
    user_id: int,
    query: str,
    limit: int = 5,
    category: str | None = None,
) -> list[dict]:
    """概要 (summary) の意味的な近さでメモを検索し、類似度の高い順に返す。

    ``user_id`` のメモのみが対象 (user 絞り込みは ``list_memos_db`` に集約)。
    ``category`` を渡すと同一カテゴリのメモだけを対象にする (``None`` は全カテゴリ)。
    概要が空のメモは対象外。各メモには query との ``similarity`` (0〜1) を付与する。
    埋め込み API の失敗は ``EmbeddingError`` がそのまま伝播する。
    """
    query_vec = embed_text(query)
    candidates = list_memos_db(user_id, limit=_CANDIDATE_CAP, category=category)

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

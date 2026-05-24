"""セマンティック検索のオーケストレーション (埋め込み呼び出し + ランキング)。

repository 層は純粋な SQLite アクセスに保つため、ネットワーク呼び出し
(``embed_text``) と類似度計算・並べ替えはこの service 層に置く。tool は
これを呼んで JSON 化するだけの薄いラッパにする。

依存方向: ``tools`` → ``service`` → ``repository`` / ``embedding`` 。
"""

import hashlib
import math

from memo.embedding import MODEL, embed_text
from memo.repository.embedding import get_cached_embedding, upsert_embedding
from memo.repository.memo import list_memos_db

#: ランキング対象に取り込むメモの上限 (更新日時の新しい順)。
_CANDIDATE_CAP = 1000


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
    user: str, query: str, limit: int = 5, is_admin: bool = False
) -> list[dict]:
    """概要 (summary) の意味的な近さでメモを検索し、類似度の高い順に返す。

    通常は ``user`` のメモのみ、``is_admin=True`` なら全ユーザーのメモが対象
    (user 絞り込み・admin 挙動は ``list_memos_db`` に集約)。概要が空のメモは
    対象外。各メモには query との ``similarity`` (0〜1) を付与する。
    埋め込み API の失敗は ``EmbeddingError`` がそのまま伝播する。
    """
    query_vec = embed_text(query)
    candidates = list_memos_db(user, limit=_CANDIDATE_CAP, is_admin=is_admin)

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

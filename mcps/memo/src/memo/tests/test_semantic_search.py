"""service.semantic_search の単体テスト (ランキング・キャッシュ・分離)。

埋め込み API を叩かないよう ``memo.service.embed_text`` を monkeypatch し、
既知の文字列を固定ベクトルに写す fake を使う。これによりネットワークも
OPENAI_API_KEY も不要でテストできる。
"""

import pytest

from memo.service import memo as service
from memo.repository.memo import create_memo_db, update_memo_db
from memo.repository.user import create_user_db

#: テスト中の alice / bob の user_id (autouse フィクスチャで毎テスト設定する)。
A: int = 0
B: int = 0


@pytest.fixture(autouse=True)
def _register_owners(clean_tables):
    """外部キー有効化により、メモ所有者は users に登録済みでなければならない。"""
    global A, B
    A = create_user_db("alice")["id"]
    B = create_user_db("bob")["id"]

# 既知の概要 / クエリ → 固定ベクトル。
# クエリ「ペットについて」と概要「犬と猫のペット」は同方向 (cosine=1.0)、
# 概要「株式投資の話」は直交 (cosine=0.0)。
_VECTORS = {
    "ペットについて": [1.0, 0.0, 0.0],
    "犬と猫のペット": [1.0, 0.0, 0.0],
    "株式投資の話": [0.0, 1.0, 0.0],
}


@pytest.fixture
def fake_embed(monkeypatch):
    """埋め込みを固定ベクトルに差し替え、呼ばれたテキストを記録する。"""
    calls: list[str] = []

    def _embed(text: str) -> list[float]:
        calls.append(text)
        return _VECTORS.get(text, [0.0, 0.0, 1.0])

    monkeypatch.setattr(service, "embed_text", _embed)
    return calls


def test_ranks_by_similarity_descending(fake_embed):
    a = create_memo_db(A, "ペットの話", "犬と猫のペット")
    b = create_memo_db(A, "投資の話", "株式投資の話")
    results = service.semantic_search(A, "ペットについて")
    assert [m["id"] for m in results] == [a["id"], b["id"]]
    assert results[0]["similarity"] == 1.0
    assert results[1]["similarity"] == 0.0


def test_respects_limit(fake_embed):
    for i in range(3):
        create_memo_db(A, f"m{i}", "犬と猫のペット")
    results = service.semantic_search(A, "ペットについて", limit=2)
    assert len(results) == 2


def test_skips_empty_summary(fake_embed):
    create_memo_db(A, "空概要", "")
    create_memo_db(A, "有概要", "犬と猫のペット")
    results = service.semantic_search(A, "ペットについて")
    assert {m["title"] for m in results} == {"有概要"}


def test_cache_avoids_recomputing_memo_embeddings(fake_embed):
    create_memo_db(A, "m", "犬と猫のペット")
    service.semantic_search(A, "ペットについて")
    service.semantic_search(A, "ペットについて")
    # 概要の埋め込みは初回だけ計算され、2回目はキャッシュ命中
    assert fake_embed.count("犬と猫のペット") == 1
    # クエリは毎回計算される
    assert fake_embed.count("ペットについて") == 2


def test_summary_change_triggers_one_recompute(fake_embed):
    m = create_memo_db(A, "m", "犬と猫のペット")
    service.semantic_search(A, "ペットについて")
    update_memo_db(A, m["id"], summary="株式投資の話")
    service.semantic_search(A, "ペットについて")
    # 概要が変わった分だけ再計算される (ハッシュ不一致)
    assert fake_embed.count("犬と猫のペット") == 1
    assert fake_embed.count("株式投資の話") == 1


def test_user_isolation(fake_embed):
    create_memo_db(A, "alice のメモ", "犬と猫のペット")
    create_memo_db(B, "bob のメモ", "犬と猫のペット")
    # admin も含め他人のメモは検索対象に入らない (完全分離)
    results = service.semantic_search(A, "ペットについて")
    assert {m["user_id"] for m in results} == {A}

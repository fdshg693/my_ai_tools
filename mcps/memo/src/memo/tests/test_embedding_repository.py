"""repository.embedding の単体テスト (埋め込みキャッシュの get / upsert)。"""

from memo.repository.embedding import (
    delete_embedding,
    get_cached_embedding,
    upsert_embedding,
)


def test_get_missing_returns_none():
    assert get_cached_embedding(9999) is None


def test_upsert_then_get_roundtrips_vector():
    upsert_embedding(1, "hash-a", "text-embedding-3-small", [0.1, 0.2, 0.3])
    cached = get_cached_embedding(1)
    assert cached["summary_hash"] == "hash-a"
    assert cached["model"] == "text-embedding-3-small"
    # JSON 経由でも float のリストとして round-trip する
    assert cached["vector"] == [0.1, 0.2, 0.3]


def test_upsert_twice_updates_in_place():
    upsert_embedding(1, "hash-a", "model-x", [1.0, 0.0])
    upsert_embedding(1, "hash-b", "model-y", [0.0, 1.0])
    cached = get_cached_embedding(1)
    # 1メモ1行で上書きされる
    assert cached["summary_hash"] == "hash-b"
    assert cached["model"] == "model-y"
    assert cached["vector"] == [0.0, 1.0]


def test_delete_removes_row():
    upsert_embedding(1, "hash-a", "model-x", [1.0])
    delete_embedding(1)
    assert get_cached_embedding(1) is None

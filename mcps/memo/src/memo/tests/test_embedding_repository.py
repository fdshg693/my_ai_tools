"""repository.embedding の単体テスト (埋め込みキャッシュの get / upsert)。

外部キー (memo_embeddings.memo_id → memos.id) 有効化により、埋め込みは実在する
メモにしか紐づけられない。各テストは ``memo_id`` フィクスチャで作った実メモの
id を使う。
"""

import pytest

from memo.repository.embedding import (
    delete_embedding,
    get_cached_embedding,
    upsert_embedding,
)
from memo.repository.memo import create_memo_db
from memo.repository.user import create_user_db

@pytest.fixture
def memo_id(clean_tables):
    """埋め込みの紐づけ先となる実メモを1件作り、その id を返す。"""
    alice_id = create_user_db("alice")["id"]
    return create_memo_db(alice_id, "embedding 対象メモ")["id"]


def test_get_missing_returns_none():
    assert get_cached_embedding(9999) is None


def test_upsert_then_get_roundtrips_vector(memo_id):
    upsert_embedding(memo_id, "hash-a", "text-embedding-3-small", [0.1, 0.2, 0.3])
    cached = get_cached_embedding(memo_id)
    assert cached["summary_hash"] == "hash-a"
    assert cached["model"] == "text-embedding-3-small"
    # JSON 経由でも float のリストとして round-trip する
    assert cached["vector"] == [0.1, 0.2, 0.3]


def test_upsert_twice_updates_in_place(memo_id):
    upsert_embedding(memo_id, "hash-a", "model-x", [1.0, 0.0])
    upsert_embedding(memo_id, "hash-b", "model-y", [0.0, 1.0])
    cached = get_cached_embedding(memo_id)
    # 1メモ1行で上書きされる
    assert cached["summary_hash"] == "hash-b"
    assert cached["model"] == "model-y"
    assert cached["vector"] == [0.0, 1.0]


def test_delete_removes_row(memo_id):
    upsert_embedding(memo_id, "hash-a", "model-x", [1.0])
    delete_embedding(memo_id)
    assert get_cached_embedding(memo_id) is None

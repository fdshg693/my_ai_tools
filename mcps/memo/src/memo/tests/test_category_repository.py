"""repository.category の単体テスト (正規化 + 第一級カテゴリ CRUD)。

カテゴリはユーザーごとの ``categories`` テーブルで管理される第一級の実体で、
所有者は不変の ``user_id`` で持つ。正規化・作成・存在判定・既定シード・リネーム
(メモへカスケード)・削除 (メモを OTHERS へ付け替え) を確認する。admin 横断は
存在しない (ユーザー単位)。
"""

import pytest

from memo.infra.database import OTHERS_CATEGORY
from memo.repository.category import (
    category_exists_db,
    create_category_db,
    delete_category_db,
    ensure_default_category_db,
    get_category_db,
    list_categories_db,
    normalize_category,
    rename_category_db,
)
from memo.repository.memo import create_memo_db, get_memo_db, list_memos_db
from memo.repository.user import create_user_db

#: テスト中の alice / bob の user_id (autouse フィクスチャで毎テスト設定する)。
A: int = 0
B: int = 0


@pytest.fixture(autouse=True)
def _register_owners(clean_tables):
    """外部キー有効化により、カテゴリ/メモの所有者は users に登録済みであること。

    各テストが使う alice / bob を先に登録し、その id を ``A`` / ``B`` に入れる
    (clean_tables の後に走るよう依存)。既定カテゴリ OTHERS は付けない
    (各テストが期待するカテゴリ一覧を汚さないため)。
    """
    global A, B
    A = create_user_db("alice")["id"]
    B = create_user_db("bob")["id"]


def _names(user_id):
    return [c["name"] for c in list_categories_db(user_id)]


def test_normalize_category_rules():
    assert normalize_category(None) == OTHERS_CATEGORY
    assert normalize_category("") == OTHERS_CATEGORY
    assert normalize_category("   ") == OTHERS_CATEGORY
    assert normalize_category("  work ") == "WORK"
    assert normalize_category("Work") == "WORK"


def test_create_and_list_normalized():
    created = create_category_db(A, "work")
    assert created["name"] == "WORK"
    assert created["user_id"] == A
    assert created["id"] > 0
    assert _names(A) == ["WORK"]


def test_create_duplicate_returns_none():
    assert create_category_db(A, "work") is not None
    # 正規化後が同じなら重複 → None
    assert create_category_db(A, "WORK") is None
    assert create_category_db(A, " Work ") is None


def test_list_sorted_and_per_user():
    create_category_db(A, "work")
    create_category_db(A, "private")
    create_category_db(B, "finance")  # 他人のは出ない
    assert _names(A) == ["PRIVATE", "WORK"]  # 名前順
    assert _names(B) == ["FINANCE"]


def test_list_empty_for_unknown_user():
    assert list_categories_db(999999) == []


def test_category_exists():
    create_category_db(A, "work")
    assert category_exists_db(A, "work") is True
    assert category_exists_db(A, "WORK") is True  # 正規化して照合
    assert category_exists_db(A, "missing") is False
    assert category_exists_db(B, "work") is False  # ユーザー単位


def test_ensure_default_seeds_others_idempotent():
    ensure_default_category_db(A)
    ensure_default_category_db(A)  # 2回でも重複しない
    assert _names(A) == [OTHERS_CATEGORY]


def test_get_category_by_id_scoped():
    created = create_category_db(A, "work")
    assert get_category_db(A, created["id"])["name"] == "WORK"
    # 他人からは取得できない
    assert get_category_db(B, created["id"]) is None
    assert get_category_db(A, 9999) is None


def test_rename_cascades_to_memos():
    create_category_db(A, "work")
    m1 = create_memo_db(A, "m1", "", category="work")
    m2 = create_memo_db(A, "m2", "", category="work")
    other = create_memo_db(A, "o", "")  # OTHERS は影響を受けない

    rename_category_db(A, "work", "job")

    assert _names(A) == ["JOB"]
    assert get_memo_db(A, m1["id"])["category"] == "JOB"
    assert get_memo_db(A, m2["id"])["category"] == "JOB"
    assert get_memo_db(A, other["id"])["category"] == OTHERS_CATEGORY


def test_rename_does_not_touch_other_users_memos():
    create_category_db(A, "work")
    create_category_db(B, "work")
    bob_memo = create_memo_db(B, "bob", "", category="work")
    rename_category_db(A, "work", "job")
    # bob の同名カテゴリ・メモは無関係
    assert get_memo_db(B, bob_memo["id"])["category"] == "WORK"
    assert _names(B) == ["WORK"]


def test_delete_reassigns_memos_to_others():
    create_category_db(A, "work")
    m = create_memo_db(A, "m", "", category="work")
    delete_category_db(A, "work")
    assert "WORK" not in _names(A)
    assert get_memo_db(A, m["id"])["category"] == OTHERS_CATEGORY
    # OTHERS で絞ると付け替わったメモが見える
    assert {x["title"] for x in list_memos_db(A, category="OTHERS")} == {"m"}

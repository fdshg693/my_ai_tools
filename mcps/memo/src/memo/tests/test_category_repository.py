"""repository.category の単体テスト (正規化 + 第一級カテゴリ CRUD)。

カテゴリはユーザーごとの ``categories`` テーブルで管理される第一級の実体。
正規化・作成・存在判定・既定シード・リネーム (メモへカスケード)・削除
(メモを OTHERS へ付け替え) を確認する。admin 横断は存在しない (ユーザー単位)。
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

ALICE = "alice"
BOB = "bob"


@pytest.fixture(autouse=True)
def _register_owners(clean_tables):
    """外部キー有効化により、カテゴリ/メモの所有者は users に登録済みであること。

    各テストが使う alice / bob を先に登録する (clean_tables の後に走るよう依存)。
    既定カテゴリ OTHERS は付けない (各テストが期待するカテゴリ一覧を汚さないため)。
    """
    create_user_db(ALICE)
    create_user_db(BOB)


def _names(user):
    return [c["name"] for c in list_categories_db(user)]


def test_normalize_category_rules():
    assert normalize_category(None) == OTHERS_CATEGORY
    assert normalize_category("") == OTHERS_CATEGORY
    assert normalize_category("   ") == OTHERS_CATEGORY
    assert normalize_category("  work ") == "WORK"
    assert normalize_category("Work") == "WORK"


def test_create_and_list_normalized():
    created = create_category_db(ALICE, "work")
    assert created["name"] == "WORK"
    assert created["user"] == ALICE
    assert created["id"] > 0
    assert _names(ALICE) == ["WORK"]


def test_create_duplicate_returns_none():
    assert create_category_db(ALICE, "work") is not None
    # 正規化後が同じなら重複 → None
    assert create_category_db(ALICE, "WORK") is None
    assert create_category_db(ALICE, " Work ") is None


def test_list_sorted_and_per_user():
    create_category_db(ALICE, "work")
    create_category_db(ALICE, "private")
    create_category_db(BOB, "finance")  # 他人のは出ない
    assert _names(ALICE) == ["PRIVATE", "WORK"]  # 名前順
    assert _names(BOB) == ["FINANCE"]


def test_list_empty_for_unknown_user():
    assert list_categories_db("nobody") == []


def test_category_exists():
    create_category_db(ALICE, "work")
    assert category_exists_db(ALICE, "work") is True
    assert category_exists_db(ALICE, "WORK") is True  # 正規化して照合
    assert category_exists_db(ALICE, "missing") is False
    assert category_exists_db(BOB, "work") is False  # ユーザー単位


def test_ensure_default_seeds_others_idempotent():
    ensure_default_category_db(ALICE)
    ensure_default_category_db(ALICE)  # 2回でも重複しない
    assert _names(ALICE) == [OTHERS_CATEGORY]


def test_get_category_by_id_scoped():
    created = create_category_db(ALICE, "work")
    assert get_category_db(ALICE, created["id"])["name"] == "WORK"
    # 他人からは取得できない
    assert get_category_db(BOB, created["id"]) is None
    assert get_category_db(ALICE, 9999) is None


def test_rename_cascades_to_memos():
    create_category_db(ALICE, "work")
    m1 = create_memo_db(ALICE, "m1", "", category="work")
    m2 = create_memo_db(ALICE, "m2", "", category="work")
    other = create_memo_db(ALICE, "o", "")  # OTHERS は影響を受けない

    rename_category_db(ALICE, "work", "job")

    assert _names(ALICE) == ["JOB"]
    assert get_memo_db(ALICE, m1["id"])["category"] == "JOB"
    assert get_memo_db(ALICE, m2["id"])["category"] == "JOB"
    assert get_memo_db(ALICE, other["id"])["category"] == OTHERS_CATEGORY


def test_rename_does_not_touch_other_users_memos():
    create_category_db(ALICE, "work")
    create_category_db(BOB, "work")
    bob_memo = create_memo_db(BOB, "bob", "", category="work")
    rename_category_db(ALICE, "work", "job")
    # bob の同名カテゴリ・メモは無関係
    assert get_memo_db(BOB, bob_memo["id"])["category"] == "WORK"
    assert _names(BOB) == ["WORK"]


def test_delete_reassigns_memos_to_others():
    create_category_db(ALICE, "work")
    m = create_memo_db(ALICE, "m", "", category="work")
    delete_category_db(ALICE, "work")
    assert "WORK" not in _names(ALICE)
    assert get_memo_db(ALICE, m["id"])["category"] == OTHERS_CATEGORY
    # OTHERS で絞ると付け替わったメモが見える
    assert {x["title"] for x in list_memos_db(ALICE, category="OTHERS")} == {"m"}

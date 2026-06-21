"""service.category / service.memo / service.user のカテゴリ関連ドメインルール。

- カテゴリ CRUD のドメイン不変条件 (必須・重複・OTHERS 保護・衝突・カスケード)。
- メモ作成/更新で未登録カテゴリを拒否する (UnknownCategory)。
- 新規ユーザー作成で既定カテゴリ OTHERS だけがシードされる。
"""

import pytest

from memo.infra.database import OTHERS_CATEGORY
from memo.repository.category import create_category_db, list_categories_db
from memo.service.category import (
    CategoryAlreadyExists,
    CategoryNameRequired,
    CategoryNotFound,
    CannotModifyOthers,
    create_category,
    delete_category,
    list_categories,
    rename_category,
)
from memo.service.memo import UnknownCategory, create_memo, get_memo, update_memo
from memo.service.user import create_user, delete_user

ALICE = "alice"


def _names(user):
    return [c["name"] for c in list_categories_db(user)]


# --- カテゴリ CRUD のドメインルール -----------------------------------------


def test_create_requires_name():
    with pytest.raises(CategoryNameRequired):
        create_category(ALICE, "   ")


def test_create_duplicate_raises():
    create_category(ALICE, "work")
    with pytest.raises(CategoryAlreadyExists):
        create_category(ALICE, "WORK")


def test_list_returns_dicts():
    create_category(ALICE, "work")
    names = [c["name"] for c in list_categories(ALICE)]
    assert names == ["WORK"]


def test_rename_others_forbidden():
    with pytest.raises(CannotModifyOthers):
        rename_category(ALICE, OTHERS_CATEGORY, "general")


def test_rename_missing_raises():
    with pytest.raises(CategoryNotFound):
        rename_category(ALICE, "missing", "x")


def test_rename_collision_raises():
    create_category(ALICE, "work")
    create_category(ALICE, "private")
    with pytest.raises(CategoryAlreadyExists):
        rename_category(ALICE, "work", "private")


def test_rename_to_same_name_allowed():
    create_category(ALICE, "work")
    # 自分自身への (正規化後同一) リネームは衝突扱いしない
    result = rename_category(ALICE, "work", "WORK")
    assert result["name"] == "WORK"


def test_delete_others_forbidden():
    with pytest.raises(CannotModifyOthers):
        delete_category(ALICE, OTHERS_CATEGORY)


def test_delete_missing_raises():
    with pytest.raises(CategoryNotFound):
        delete_category(ALICE, "missing")


# --- メモ作成/更新のカテゴリ検証 --------------------------------------------


def test_create_memo_rejects_unknown_category():
    with pytest.raises(UnknownCategory):
        create_memo(ALICE, "メモ", "", category="work")


def test_create_memo_allows_registered_category():
    create_category(ALICE, "work")
    memo = create_memo(ALICE, "メモ", "", category="work")
    assert memo["category"] == "WORK"


def test_create_memo_allows_others_without_registration():
    # OTHERS は常に存在扱い (登録不要)
    memo = create_memo(ALICE, "メモ")
    assert memo["category"] == OTHERS_CATEGORY


def test_update_memo_rejects_unknown_category():
    memo = create_memo(ALICE, "メモ")
    with pytest.raises(UnknownCategory):
        update_memo(ALICE, memo["id"], category="work")


def test_update_memo_empty_category_allowed():
    create_category(ALICE, "work")
    memo = create_memo(ALICE, "メモ", "", category="work")
    updated = update_memo(ALICE, memo["id"], category="")
    assert updated["category"] == OTHERS_CATEGORY


def test_update_memo_none_category_keeps_existing():
    create_category(ALICE, "work")
    memo = create_memo(ALICE, "メモ", "", category="work")
    updated = update_memo(ALICE, memo["id"], summary="更新")
    assert updated["category"] == "WORK"


# --- ユーザー作成時の OTHERS シード / 削除カスケード ------------------------


def test_create_user_seeds_only_others():
    create_user("dave")
    assert _names("dave") == [OTHERS_CATEGORY]


def test_delete_user_cascades_categories_and_memos():
    create_user("erin")
    create_category("erin", "work")
    memo = create_memo("erin", "メモ", "", category="work")
    delete_user("erin")
    # ユーザーのカテゴリ・メモが消える
    assert list_categories_db("erin") == []
    assert get_memo("erin", memo["id"]) is None

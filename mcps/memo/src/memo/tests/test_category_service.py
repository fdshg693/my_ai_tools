"""service.category / service.memo / service.user のカテゴリ関連ドメインルール。

- カテゴリ CRUD のドメイン不変条件 (必須・重複・OTHERS 保護・衝突・カスケード)。
- メモ作成/更新で未登録カテゴリを拒否する (UnknownCategory)。
- 新規ユーザー作成で既定カテゴリ OTHERS だけがシードされる。

カテゴリ/メモの service は不変の ``user_id`` で操作する。alice の id は ``A`` で
参照する。ユーザー作成/削除は名前ベース (service.user)。
"""

import pytest

from memo.infra.database import OTHERS_CATEGORY
from memo.repository.category import list_categories_db
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
from memo.repository.user import create_user_db
from memo.service.memo import UnknownCategory, create_memo, get_memo, update_memo
from memo.service.user import create_user, delete_user

#: テスト中の alice の user_id (autouse フィクスチャで毎テスト設定する)。
A: int = 0


@pytest.fixture(autouse=True)
def _register_alice(clean_tables):
    """外部キー有効化により、メモ/カテゴリの所有者 alice を先に登録する。

    OTHERS は付けない (カテゴリ一覧を期待値どおりに保つ)。dave / erin は
    各テストが service.create_user で登録する。
    """
    global A
    A = create_user_db("alice")["id"]


def _names(user_id):
    return [c["name"] for c in list_categories_db(user_id)]


# --- カテゴリ CRUD のドメインルール -----------------------------------------


def test_create_requires_name():
    with pytest.raises(CategoryNameRequired):
        create_category(A, "   ")


def test_create_duplicate_raises():
    create_category(A, "work")
    with pytest.raises(CategoryAlreadyExists):
        create_category(A, "WORK")


def test_list_returns_dicts():
    create_category(A, "work")
    names = [c["name"] for c in list_categories(A)]
    assert names == ["WORK"]


def test_rename_others_forbidden():
    with pytest.raises(CannotModifyOthers):
        rename_category(A, OTHERS_CATEGORY, "general")


def test_rename_missing_raises():
    with pytest.raises(CategoryNotFound):
        rename_category(A, "missing", "x")


def test_rename_collision_raises():
    create_category(A, "work")
    create_category(A, "private")
    with pytest.raises(CategoryAlreadyExists):
        rename_category(A, "work", "private")


def test_rename_to_same_name_allowed():
    create_category(A, "work")
    # 自分自身への (正規化後同一) リネームは衝突扱いしない
    result = rename_category(A, "work", "WORK")
    assert result["name"] == "WORK"


def test_delete_others_forbidden():
    with pytest.raises(CannotModifyOthers):
        delete_category(A, OTHERS_CATEGORY)


def test_delete_missing_raises():
    with pytest.raises(CategoryNotFound):
        delete_category(A, "missing")


# --- メモ作成/更新のカテゴリ検証 --------------------------------------------


def test_create_memo_rejects_unknown_category():
    with pytest.raises(UnknownCategory):
        create_memo(A, "メモ", "", category="work")


def test_create_memo_allows_registered_category():
    create_category(A, "work")
    memo = create_memo(A, "メモ", "", category="work")
    assert memo["category"] == "WORK"


def test_create_memo_allows_others_without_registration():
    # OTHERS は常に存在扱い (登録不要)
    memo = create_memo(A, "メモ")
    assert memo["category"] == OTHERS_CATEGORY


def test_update_memo_rejects_unknown_category():
    memo = create_memo(A, "メモ")
    with pytest.raises(UnknownCategory):
        update_memo(A, memo["id"], category="work")


def test_update_memo_empty_category_allowed():
    create_category(A, "work")
    memo = create_memo(A, "メモ", "", category="work")
    updated = update_memo(A, memo["id"], category="")
    assert updated["category"] == OTHERS_CATEGORY


def test_update_memo_none_category_keeps_existing():
    create_category(A, "work")
    memo = create_memo(A, "メモ", "", category="work")
    updated = update_memo(A, memo["id"], summary="更新")
    assert updated["category"] == "WORK"


# --- ユーザー作成時の OTHERS シード / 削除カスケード ------------------------


def test_create_user_seeds_only_others():
    dave = create_user("dave")
    assert _names(dave["id"]) == [OTHERS_CATEGORY]


def test_delete_user_cascades_categories_and_memos():
    erin = create_user("erin")
    create_category(erin["id"], "work")
    memo = create_memo(erin["id"], "メモ", "", category="work")
    delete_user("erin")
    # ユーザーのカテゴリ・メモが消える
    assert list_categories_db(erin["id"]) == []
    assert get_memo(erin["id"], memo["id"]) is None

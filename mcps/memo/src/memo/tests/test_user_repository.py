"""repository.user の単体テスト (ユーザー台帳の CRUD + 登録判定)。"""

from memo.infra.database import ADMIN_USER
from memo.repository.memo import create_memo_db, get_memo_db
from memo.repository.user import (
    create_user_db,
    delete_user_db,
    get_user_db,
    is_registered_user,
    list_users_db,
    update_user_db,
)

ALICE = "alice"
BOB = "bob"


def test_admin_is_seeded():
    # init_db / conftest が admin をシードしている
    assert is_registered_user(ADMIN_USER) is True


def test_create_and_get_user():
    user = create_user_db(ALICE, display_name="アリス", note="営業部")
    assert user["name"] == ALICE
    assert user["display_name"] == "アリス"
    assert user["note"] == "営業部"
    assert user["created_at"]
    assert user["updated_at"]
    assert get_user_db(ALICE) == user
    assert is_registered_user(ALICE) is True


def test_create_user_defaults():
    user = create_user_db(BOB)
    assert user["display_name"] == ""
    assert user["note"] == ""


def test_create_duplicate_user_returns_none():
    create_user_db(ALICE)
    assert create_user_db(ALICE) is None


def test_get_missing_user_returns_none():
    assert get_user_db("nobody") is None


def test_unregistered_user_is_not_registered():
    assert is_registered_user("nobody") is False


def test_list_users_sorted():
    create_user_db("charlie")
    create_user_db(ALICE)
    create_user_db(BOB)
    names = [u["name"] for u in list_users_db()]
    # admin (シード済み) も含めて名前順
    assert names == sorted([ADMIN_USER, ALICE, BOB, "charlie"])


def test_update_user_attributes():
    create_user_db(ALICE, display_name="旧名", note="旧メモ")
    updated = update_user_db(ALICE, display_name="新名", note="新メモ")
    assert updated["display_name"] == "新名"
    assert updated["note"] == "新メモ"
    # name (識別子) は不変
    assert updated["name"] == ALICE


def test_update_user_partial():
    create_user_db(ALICE, display_name="アリス", note="残す")
    updated = update_user_db(ALICE, display_name="改名のみ")
    assert updated["display_name"] == "改名のみ"
    assert updated["note"] == "残す"


def test_update_missing_user_returns_none():
    assert update_user_db("nobody", display_name="x") is None


def test_delete_user_keeps_memos():
    create_user_db(ALICE)
    memo = create_memo_db(ALICE, "alice のメモ", "")
    assert delete_user_db(ALICE) is True
    assert is_registered_user(ALICE) is False
    # メモは残り、admin だけが操作できる
    assert get_memo_db(ADMIN_USER, memo["id"], is_admin=True) is not None
    assert get_memo_db(ALICE, memo["id"]) is not None  # DB 層は user 一致なら取れる


def test_delete_missing_user_returns_false():
    assert delete_user_db("nobody") is False

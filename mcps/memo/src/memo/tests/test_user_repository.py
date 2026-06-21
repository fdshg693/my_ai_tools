"""repository.user の単体テスト (ユーザー台帳の CRUD + 登録判定 + is_admin)。"""

from memo.infra.database import ADMIN_USER
from memo.repository.category import (
    create_category_db,
    list_categories_db,
)
from memo.repository.embedding import get_cached_embedding, upsert_embedding
from memo.repository.memo import create_memo_db, get_memo_db
from memo.repository.user import (
    count_admins_db,
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
    # init_db / conftest が admin をシードしている (is_admin=True)
    assert is_registered_user(ADMIN_USER) is True
    assert get_user_db(ADMIN_USER)["is_admin"] is True
    assert count_admins_db() == 1


def test_create_and_get_user():
    user = create_user_db(ALICE, display_name="アリス", note="営業部")
    assert isinstance(user["id"], int)
    assert user["name"] == ALICE
    assert user["display_name"] == "アリス"
    assert user["note"] == "営業部"
    assert user["is_admin"] is False
    assert user["created_at"]
    assert user["updated_at"]
    assert get_user_db(ALICE) == user
    assert is_registered_user(ALICE) is True


def test_create_user_defaults():
    user = create_user_db(BOB)
    assert user["display_name"] == ""
    assert user["note"] == ""
    assert user["is_admin"] is False


def test_create_admin_user():
    user = create_user_db("root", is_admin=True)
    assert user["is_admin"] is True
    assert count_admins_db() == 2  # admin (seeded) + root


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
    # name (ログインハンドル) は不変
    assert updated["name"] == ALICE


def test_update_user_partial():
    create_user_db(ALICE, display_name="アリス", note="残す")
    updated = update_user_db(ALICE, display_name="改名のみ")
    assert updated["display_name"] == "改名のみ"
    assert updated["note"] == "残す"


def test_update_user_is_admin_toggle():
    create_user_db(ALICE)
    promoted = update_user_db(ALICE, is_admin=True)
    assert promoted["is_admin"] is True
    assert count_admins_db() == 2
    # display_name 等を触らず is_admin だけ外せる
    demoted = update_user_db(ALICE, is_admin=False)
    assert demoted["is_admin"] is False
    assert count_admins_db() == 1


def test_update_missing_user_returns_none():
    assert update_user_db("nobody", display_name="x") is None


def test_delete_user_cascades_memos_categories_embeddings():
    alice = create_user_db(ALICE)
    aid = alice["id"]
    create_category_db(aid, "work")
    memo = create_memo_db(aid, "alice のメモ", "concept", category="work")
    upsert_embedding(memo["id"], "hash", "model", [0.1, 0.2])

    assert delete_user_db(ALICE) is True
    assert is_registered_user(ALICE) is False
    # メモ・カテゴリ・埋め込みもカスケード削除される (孤立データを残さない)
    assert get_memo_db(aid, memo["id"]) is None
    assert list_categories_db(aid) == []
    assert get_cached_embedding(memo["id"]) is None


def test_delete_does_not_touch_other_users():
    create_user_db(ALICE)
    bob = create_user_db(BOB)
    bid = bob["id"]
    create_category_db(bid, "work")
    bob_memo = create_memo_db(bid, "bob のメモ", "", category="work")
    delete_user_db(ALICE)
    # bob のデータは無関係
    assert get_memo_db(bid, bob_memo["id"]) is not None
    assert [c["name"] for c in list_categories_db(bid)] == ["WORK"]


def test_delete_missing_user_returns_false():
    assert delete_user_db("nobody") is False

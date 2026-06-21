"""admin_server.py の REST エンドポイントの単体テスト。

conftest.py が DB を一時ファイルに差し替え、各テスト前に admin だけ残して
テーブルを空にする。Starlette の TestClient (httpx) でアプリを直接叩く。
"""

import pytest
from starlette.testclient import TestClient

from memo.repository.memo import create_memo_db
from memo.server.web.app import create_app


@pytest.fixture
def client():
    return TestClient(create_app())


def test_list_users_initially_only_admin(client):
    res = client.get("/api/users")
    assert res.status_code == 200
    users = res.json()
    assert [u["name"] for u in users] == ["admin"]


def test_create_user(client):
    res = client.post(
        "/api/users",
        json={"name": "alice", "display_name": "Alice", "note": "hello"},
    )
    assert res.status_code == 201
    body = res.json()
    assert body["name"] == "alice"
    assert body["display_name"] == "Alice"
    assert body["note"] == "hello"

    # 一覧にも反映され、名前順 (admin, alice) になる
    names = [u["name"] for u in client.get("/api/users").json()]
    assert names == ["admin", "alice"]


def test_create_user_requires_name(client):
    res = client.post("/api/users", json={"name": "  ", "display_name": "X"})
    assert res.status_code == 400


def test_create_duplicate_user_conflicts(client):
    client.post("/api/users", json={"name": "bob"})
    res = client.post("/api/users", json={"name": "bob"})
    assert res.status_code == 409


def test_get_user(client):
    client.post("/api/users", json={"name": "carol", "display_name": "C"})
    res = client.get("/api/users/carol")
    assert res.status_code == 200
    assert res.json()["display_name"] == "C"


def test_get_missing_user_404(client):
    res = client.get("/api/users/ghost")
    assert res.status_code == 404


def test_update_user(client):
    client.post("/api/users", json={"name": "dave", "display_name": "old"})
    res = client.put("/api/users/dave", json={"display_name": "new", "note": "n"})
    assert res.status_code == 200
    body = res.json()
    assert body["display_name"] == "new"
    assert body["note"] == "n"


def test_update_only_supplied_fields(client):
    client.post("/api/users", json={"name": "erin", "display_name": "keep", "note": "keep-note"})
    # note だけ更新。display_name は省略 → 変更しない
    res = client.put("/api/users/erin", json={"note": "changed"})
    assert res.status_code == 200
    body = res.json()
    assert body["display_name"] == "keep"
    assert body["note"] == "changed"


def test_update_missing_user_404(client):
    res = client.put("/api/users/ghost", json={"display_name": "x"})
    assert res.status_code == 404


def test_delete_user(client):
    client.post("/api/users", json={"name": "frank"})
    res = client.delete("/api/users/frank")
    assert res.status_code == 200
    assert res.json()["deleted"] == "frank"
    assert client.get("/api/users/frank").status_code == 404


def test_cannot_delete_admin(client):
    res = client.delete("/api/users/admin")
    assert res.status_code == 403
    # admin は残っている
    assert client.get("/api/users/admin").status_code == 200


def test_delete_missing_user_404(client):
    res = client.delete("/api/users/ghost")
    assert res.status_code == 404


def test_index_serves_html(client):
    res = client.get("/")
    assert res.status_code == 200
    assert "memo" in res.text.lower()


# ---------------------------------------------------------------------------
# ユーザーごとのメモ一覧 (ページング)
# ---------------------------------------------------------------------------


def test_list_user_memos_empty(client):
    client.post("/api/users", json={"name": "grace"})
    res = client.get("/api/users/grace/memos")
    assert res.status_code == 200
    body = res.json()
    assert body["user"] == "grace"
    assert body["items"] == []
    assert body["total"] == 0
    assert body["total_pages"] == 0


def test_list_user_memos_missing_user_404(client):
    res = client.get("/api/users/ghost/memos")
    assert res.status_code == 404


def test_list_user_memos_only_that_user(client):
    client.post("/api/users", json={"name": "heidi"})
    client.post("/api/users", json={"name": "ivan"})
    create_memo_db("heidi", "h-1")
    create_memo_db("heidi", "h-2")
    create_memo_db("ivan", "i-1")

    body = client.get("/api/users/heidi/memos").json()
    assert body["total"] == 2
    assert {m["title"] for m in body["items"]} == {"h-1", "h-2"}
    assert all(m["user"] == "heidi" for m in body["items"])


def test_list_user_memos_pagination(client):
    client.post("/api/users", json={"name": "judy"})
    for i in range(5):
        create_memo_db("judy", f"memo-{i}")

    page1 = client.get("/api/users/judy/memos?page=1&per_page=2").json()
    assert page1["total"] == 5
    assert page1["total_pages"] == 3
    assert len(page1["items"]) == 2

    page3 = client.get("/api/users/judy/memos?page=3&per_page=2").json()
    assert len(page3["items"]) == 1  # 最終ページは1件

    # ページ1とページ3で別のメモが返る (重複しない)
    ids1 = {m["id"] for m in page1["items"]}
    ids3 = {m["id"] for m in page3["items"]}
    assert ids1.isdisjoint(ids3)


def test_list_user_memos_per_page_capped(client):
    client.post("/api/users", json={"name": "ken"})
    body = client.get("/api/users/ken/memos?per_page=99999").json()
    assert body["per_page"] == 100  # MAX_PER_PAGE で頭打ち


def test_list_user_memos_invalid_params_fallback(client):
    client.post("/api/users", json={"name": "leo"})
    create_memo_db("leo", "only")
    body = client.get("/api/users/leo/memos?page=abc&per_page=xyz").json()
    assert body["page"] == 1
    assert body["per_page"] == 20  # DEFAULT_PER_PAGE


# ---------------------------------------------------------------------------
# ユーザーごとのメモ CRUD (作成 / 更新 / 削除)
# ---------------------------------------------------------------------------


def test_create_user_memo(client):
    client.post("/api/users", json={"name": "mona"})
    res = client.post(
        "/api/users/mona/memos", json={"title": "T", "summary": "S"}
    )
    assert res.status_code == 201
    body = res.json()
    assert body["title"] == "T"
    assert body["summary"] == "S"
    assert body["user"] == "mona"  # 所有者はパスのユーザーに固定

    # 一覧に反映される
    listing = client.get("/api/users/mona/memos").json()
    assert listing["total"] == 1


def test_create_user_memo_trims_and_defaults_summary(client):
    client.post("/api/users", json={"name": "nina"})
    res = client.post("/api/users/nina/memos", json={"title": "  hi  "})
    assert res.status_code == 201
    body = res.json()
    assert body["title"] == "hi"  # trim される
    assert body["summary"] == ""  # 省略時は空


def test_create_user_memo_requires_title(client):
    client.post("/api/users", json={"name": "omar"})
    res = client.post("/api/users/omar/memos", json={"title": "   "})
    assert res.status_code == 400


def test_create_user_memo_missing_user_404(client):
    res = client.post("/api/users/ghost/memos", json={"title": "x"})
    assert res.status_code == 404


def test_update_user_memo(client):
    client.post("/api/users", json={"name": "pam"})
    memo = create_memo_db("pam", "old", "old-summary")
    res = client.put(
        f"/api/users/pam/memos/{memo['id']}",
        json={"title": "new", "summary": "new-summary"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["title"] == "new"
    assert body["summary"] == "new-summary"


def test_update_user_memo_partial(client):
    client.post("/api/users", json={"name": "quinn"})
    memo = create_memo_db("quinn", "keep", "keep-summary")
    # summary だけ更新。title 省略 → 変更しない
    res = client.put(
        f"/api/users/quinn/memos/{memo['id']}", json={"summary": "changed"}
    )
    assert res.status_code == 200
    body = res.json()
    assert body["title"] == "keep"
    assert body["summary"] == "changed"


def test_update_user_memo_rejects_empty_title(client):
    client.post("/api/users", json={"name": "rita"})
    memo = create_memo_db("rita", "title")
    res = client.put(f"/api/users/rita/memos/{memo['id']}", json={"title": "  "})
    assert res.status_code == 400


def test_update_user_memo_other_user_404(client):
    client.post("/api/users", json={"name": "sam"})
    client.post("/api/users", json={"name": "tina"})
    memo = create_memo_db("tina", "tina-memo")
    # sam のパスで tina のメモを更新しようとしても見つからない (完全分離)
    res = client.put(
        f"/api/users/sam/memos/{memo['id']}", json={"title": "hack"}
    )
    assert res.status_code == 404
    # tina のメモは変わっていない
    body = client.get("/api/users/tina/memos").json()
    assert body["items"][0]["title"] == "tina-memo"


def test_update_user_memo_missing_404(client):
    client.post("/api/users", json={"name": "uma"})
    res = client.put("/api/users/uma/memos/99999", json={"title": "x"})
    assert res.status_code == 404


def test_delete_user_memo(client):
    client.post("/api/users", json={"name": "vic"})
    memo = create_memo_db("vic", "to-delete")
    res = client.delete(f"/api/users/vic/memos/{memo['id']}")
    assert res.status_code == 200
    assert res.json()["deleted"] == memo["id"]
    assert client.get("/api/users/vic/memos").json()["total"] == 0


def test_delete_user_memo_other_user_404(client):
    client.post("/api/users", json={"name": "wes"})
    client.post("/api/users", json={"name": "xena"})
    memo = create_memo_db("xena", "xena-memo")
    res = client.delete(f"/api/users/wes/memos/{memo['id']}")
    assert res.status_code == 404
    # xena のメモは残っている
    assert client.get("/api/users/xena/memos").json()["total"] == 1


def test_delete_user_memo_missing_404(client):
    client.post("/api/users", json={"name": "yan"})
    res = client.delete("/api/users/yan/memos/99999")
    assert res.status_code == 404


# ---------------------------------------------------------------------------
# カテゴリ: 作成時の指定・既定 OTHERS・更新・一覧の絞り込み
# ---------------------------------------------------------------------------


def test_create_user_memo_with_category(client):
    client.post("/api/users", json={"name": "cat-a"})
    client.post("/api/users/cat-a/categories", json={"name": "work"})
    res = client.post(
        "/api/users/cat-a/memos", json={"title": "T", "category": "work"}
    )
    assert res.status_code == 201
    assert res.json()["category"] == "WORK"  # 大文字に正規化


def test_create_user_memo_defaults_category_others(client):
    client.post("/api/users", json={"name": "cat-b"})
    res = client.post("/api/users/cat-b/memos", json={"title": "T"})
    assert res.json()["category"] == "OTHERS"


def test_create_user_memo_rejects_unregistered_category(client):
    client.post("/api/users", json={"name": "cat-x"})
    # カテゴリ未登録で指定すると 400 (先に作成が必要)
    res = client.post(
        "/api/users/cat-x/memos", json={"title": "T", "category": "work"}
    )
    assert res.status_code == 400


def test_update_user_memo_category(client):
    client.post("/api/users", json={"name": "cat-c"})
    client.post("/api/users/cat-c/categories", json={"name": "private"})
    memo = create_memo_db("cat-c", "T", "", category="work")
    res = client.put(
        f"/api/users/cat-c/memos/{memo['id']}", json={"category": "private"}
    )
    assert res.status_code == 200
    assert res.json()["category"] == "PRIVATE"


def test_list_user_memos_filters_by_category(client):
    client.post("/api/users", json={"name": "cat-d"})
    create_memo_db("cat-d", "w1", "", category="work")
    create_memo_db("cat-d", "p1", "", category="private")
    create_memo_db("cat-d", "o1")  # OTHERS

    work = client.get("/api/users/cat-d/memos?category=work").json()
    assert work["total"] == 1
    assert work["items"][0]["title"] == "w1"
    # 絞り込みなしは全件
    assert client.get("/api/users/cat-d/memos").json()["total"] == 3


# ---------------------------------------------------------------------------
# カテゴリ管理エンドポイント (一覧 / 作成 / リネーム / 削除)
# ---------------------------------------------------------------------------


def _cat_id(client, user, name):
    """指定ユーザーのカテゴリ一覧から name の id を引く。"""
    cats = client.get(f"/api/users/{user}/categories").json()
    return next(c["id"] for c in cats if c["name"] == name)


def test_list_categories_new_user_only_others(client):
    client.post("/api/users", json={"name": "kat-a"})
    res = client.get("/api/users/kat-a/categories")
    assert res.status_code == 200
    assert [c["name"] for c in res.json()] == ["OTHERS"]


def test_list_categories_missing_user_404(client):
    assert client.get("/api/users/ghost/categories").status_code == 404


def test_create_category(client):
    client.post("/api/users", json={"name": "kat-b"})
    res = client.post("/api/users/kat-b/categories", json={"name": "work"})
    assert res.status_code == 201
    assert res.json()["name"] == "WORK"  # 正規化
    names = [c["name"] for c in client.get("/api/users/kat-b/categories").json()]
    assert names == ["OTHERS", "WORK"]


def test_create_category_requires_name(client):
    client.post("/api/users", json={"name": "kat-c"})
    res = client.post("/api/users/kat-c/categories", json={"name": "  "})
    assert res.status_code == 400


def test_create_category_duplicate_409(client):
    client.post("/api/users", json={"name": "kat-d"})
    client.post("/api/users/kat-d/categories", json={"name": "work"})
    res = client.post("/api/users/kat-d/categories", json={"name": "WORK"})
    assert res.status_code == 409


def test_create_category_missing_user_404(client):
    res = client.post("/api/users/ghost/categories", json={"name": "work"})
    assert res.status_code == 404


def test_rename_category_cascades_to_memos(client):
    client.post("/api/users", json={"name": "kat-e"})
    client.post("/api/users/kat-e/categories", json={"name": "work"})
    memo = client.post(
        "/api/users/kat-e/memos", json={"title": "m", "category": "work"}
    ).json()
    cid = _cat_id(client, "kat-e", "WORK")

    res = client.put(f"/api/users/kat-e/categories/{cid}", json={"name": "job"})
    assert res.status_code == 200
    # メモのカテゴリも追従する
    listing = client.get("/api/users/kat-e/memos").json()
    moved = next(m for m in listing["items"] if m["id"] == memo["id"])
    assert moved["category"] == "JOB"


def test_rename_others_forbidden_403(client):
    client.post("/api/users", json={"name": "kat-f"})
    cid = _cat_id(client, "kat-f", "OTHERS")
    res = client.put(f"/api/users/kat-f/categories/{cid}", json={"name": "x"})
    assert res.status_code == 403


def test_rename_collision_409(client):
    client.post("/api/users", json={"name": "kat-g"})
    client.post("/api/users/kat-g/categories", json={"name": "work"})
    client.post("/api/users/kat-g/categories", json={"name": "private"})
    cid = _cat_id(client, "kat-g", "WORK")
    res = client.put(f"/api/users/kat-g/categories/{cid}", json={"name": "private"})
    assert res.status_code == 409


def test_rename_missing_category_404(client):
    client.post("/api/users", json={"name": "kat-h"})
    res = client.put("/api/users/kat-h/categories/99999", json={"name": "x"})
    assert res.status_code == 404


def test_delete_category_reassigns_memos_to_others(client):
    client.post("/api/users", json={"name": "kat-i"})
    client.post("/api/users/kat-i/categories", json={"name": "work"})
    memo = client.post(
        "/api/users/kat-i/memos", json={"title": "m", "category": "work"}
    ).json()
    cid = _cat_id(client, "kat-i", "WORK")

    res = client.delete(f"/api/users/kat-i/categories/{cid}")
    assert res.status_code == 200
    # カテゴリが消え、メモは OTHERS へ
    names = [c["name"] for c in client.get("/api/users/kat-i/categories").json()]
    assert names == ["OTHERS"]
    listing = client.get("/api/users/kat-i/memos").json()
    moved = next(m for m in listing["items"] if m["id"] == memo["id"])
    assert moved["category"] == "OTHERS"


def test_delete_others_forbidden_403(client):
    client.post("/api/users", json={"name": "kat-j"})
    cid = _cat_id(client, "kat-j", "OTHERS")
    res = client.delete(f"/api/users/kat-j/categories/{cid}")
    assert res.status_code == 403


def test_delete_missing_category_404(client):
    client.post("/api/users", json={"name": "kat-k"})
    res = client.delete("/api/users/kat-k/categories/99999")
    assert res.status_code == 404

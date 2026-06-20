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

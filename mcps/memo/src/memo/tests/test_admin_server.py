"""admin_server.py の REST エンドポイントの単体テスト。

conftest.py が DB を一時ファイルに差し替え、各テスト前に admin だけ残して
テーブルを空にする。Starlette の TestClient (httpx) でアプリを直接叩く。
"""

import pytest
from starlette.testclient import TestClient

from memo.admin_server import create_app


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

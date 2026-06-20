"""MCPクライアントでサーバーの利用可能なツールを確認するテスト。

サーバーはインプロセスで起動し、ネットワークを使わずにテストする。
スクリプトとしても (`python -m memo.tests.test_mcp_client`)、pytest としても実行できる。
pytest-asyncio に依存しないよう、各テストは同期関数内で asyncio.run() する。

インプロセス接続には HTTP リクエストコンテキストが無いため、ユーザーは
stdio と同じく `set_stdio_user()` で固定する。
"""

import asyncio
import json
import logging

from fastmcp import Client

from memo.infra.database import ADMIN_USER
from memo.infra.embedding import EmbeddingError
from memo.repository.memo import create_memo_db
from memo.repository.user import create_user_db
from memo.server.mcp import auth as auth_module
from memo.server.mcp.app import mcp  # init_db() はモジュール読み込み時に実行される
from memo.server.mcp.auth import set_stdio_user
from memo.service import memo as service

EXPECTED_TOOLS = {
    "create_memo",
    "get_memo",
    "list_memos",
    "search_memos",
    "semantic_search_memos",
    "update_memo",
    "delete_memo",
    "create_user",
    "get_user",
    "list_users",
    "update_user",
    "delete_user",
    "switch_user",
}


class _DummyRequest:
    """HTTP リクエストコンテキストを擬似する (query_params / headers のみ)。"""

    def __init__(self, query: dict, headers: dict | None = None):
        self.query_params = query  # dict は .get() を持つので Starlette QueryParams 代用可
        self.headers = headers or {}


def _patch_http(monkeypatch, query: dict, headers: dict | None = None) -> None:
    """auth.current_user 等が HTTP モードで振る舞うようにする。

    起動時に確定するトランスポート種別を HTTP に立て、get_http_request を
    ダミーリクエストへ差し替える (どちらも conftest が各テスト後に既定へ戻す)。
    """
    auth_module.set_http_transport(True)
    req = _DummyRequest(query, headers)
    monkeypatch.setattr(auth_module, "get_http_request", lambda: req)


async def _list_tool_names() -> set[str]:
    async with Client(mcp) as client:
        tools = await client.list_tools()
        return {t.name for t in tools}


async def _crud_roundtrip() -> tuple[str, str]:
    async with Client(mcp) as client:
        created = await client.call_tool(
            "create_memo", {"title": "会議メモ", "summary": "Q2 レビュー"}
        )
        searched = await client.call_tool("search_memos", {"query": "会議"})
        return created.data, searched.data


async def _call(tool: str, args: dict) -> str:
    async with Client(mcp) as client:
        result = await client.call_tool(tool, args)
        return result.data


def test_expected_tools_registered():
    names = asyncio.run(_list_tool_names())
    assert EXPECTED_TOOLS <= names


def test_crud_roundtrip():
    create_user_db("tester")  # 登録済みユーザーでないと拒否される
    set_stdio_user("tester")
    try:
        created, searched = asyncio.run(_crud_roundtrip())
    finally:
        set_stdio_user(None)
    # create は冗長なレコードではなく簡潔な成功メッセージを返す
    assert created.startswith("Created memo id=")
    # search はメモ本体と一致キーワードを返す
    assert "会議メモ" in searched
    assert "matched_keywords" in searched


def test_category_filter_roundtrip():
    create_user_db("catuser")
    set_stdio_user("catuser")
    try:
        created = asyncio.run(
            _call("create_memo", {"title": "仕事メモ", "category": "work"})
        )
        asyncio.run(_call("create_memo", {"title": "私用メモ", "category": "private"}))
        # 作成メッセージに正規化後のカテゴリが出る
        assert "category=WORK" in created
        # list は同一カテゴリだけに絞れる (大文字小文字は区別しない)
        listed = asyncio.run(_call("list_memos", {"category": "work"}))
        assert "仕事メモ" in listed
        assert "私用メモ" not in listed
        # search も同様に絞れる
        searched = asyncio.run(
            _call("search_memos", {"query": "メモ", "category": "private"})
        )
        assert "私用メモ" in searched
        assert "仕事メモ" not in searched
    finally:
        set_stdio_user(None)


def test_rejects_when_user_not_identified():
    set_stdio_user(None)
    result = asyncio.run(_call("create_memo", {"title": "誰のもの?"}))
    assert result.startswith("Error: user is not identified")


def test_rejects_unregistered_user():
    set_stdio_user("ghost")  # users 台帳に居ない
    try:
        result = asyncio.run(_call("create_memo", {"title": "幽霊のメモ"}))
    finally:
        set_stdio_user(None)
    assert "is not registered" in result


def test_user_management_is_admin_only():
    create_user_db("alice")
    set_stdio_user("alice")  # 登録済みだが admin ではない
    try:
        result = asyncio.run(_call("list_users", {}))
    finally:
        set_stdio_user(None)
    assert result == "Error: this tool is admin-only."


def test_admin_sees_all_users_memos():
    create_user_db("alice")
    create_memo_db("alice", "alice の会議メモ", "")
    set_stdio_user(ADMIN_USER)
    try:
        listed = asyncio.run(_call("list_memos", {}))
    finally:
        set_stdio_user(None)
    assert "alice の会議メモ" in listed


def test_admin_can_create_user():
    set_stdio_user(ADMIN_USER)
    try:
        result = asyncio.run(_call("create_user", {"name": "newbie"}))
    finally:
        set_stdio_user(None)
    assert result == "Created user 'newbie'."


def test_admin_cannot_delete_self():
    set_stdio_user(ADMIN_USER)
    try:
        result = asyncio.run(_call("delete_user", {"name": ADMIN_USER}))
    finally:
        set_stdio_user(None)
    assert "cannot delete the admin user" in result


def test_semantic_search_returns_ranked_results(monkeypatch):
    # 埋め込み API を叩かないよう固定ベクトルに差し替える
    vectors = {
        "ペットについて": [1.0, 0.0],
        "犬と猫": [1.0, 0.0],  # query と同方向 → 類似度高
        "株の話": [0.0, 1.0],  # query と直交 → 類似度 0
    }
    monkeypatch.setattr(service, "embed_text", lambda t: vectors.get(t, [0.0, 0.0]))
    create_user_db("alice")
    create_memo_db("alice", "ペットメモ", "犬と猫")
    create_memo_db("alice", "投資メモ", "株の話")
    set_stdio_user("alice")
    try:
        result = asyncio.run(_call("semantic_search_memos", {"query": "ペットについて"}))
    finally:
        set_stdio_user(None)
    data = json.loads(result)
    # 類似度の高いペットメモが先頭、各メモに similarity が付く
    assert data[0]["title"] == "ペットメモ"
    assert "similarity" in data[0]
    assert data[0]["similarity"] >= data[-1]["similarity"]


def test_semantic_search_reports_embedding_error(monkeypatch):
    def _boom(_text):
        raise EmbeddingError("OPENAI_API_KEY is not set.")

    monkeypatch.setattr(service, "embed_text", _boom)
    create_user_db("alice")
    create_memo_db("alice", "メモ", "本文")
    set_stdio_user("alice")
    try:
        result = asyncio.run(_call("semantic_search_memos", {"query": "x"}))
    finally:
        set_stdio_user(None)
    assert result.startswith("Error:")


def test_switch_user_stdio_changes_owner():
    create_user_db("alice")
    set_stdio_user(ADMIN_USER)
    try:
        switched = asyncio.run(_call("switch_user", {"target": "alice"}))
        # メモがまだ無いユーザーは「カテゴリを持つメモはまだありません」を添える
        assert switched.startswith("Switched user to 'alice'.")
        assert "まだありません" in switched
        # switch_user が _stdio_user を alice に書き換えたので、以後のメモは alice 所有
        created = asyncio.run(_call("create_memo", {"title": "alice の切替メモ"}))
        assert created.startswith("Created memo id=")
        # alice (非 admin) の list_memos は自分のメモだけ見える → 所有者が alice の証跡
        listed = asyncio.run(_call("list_memos", {}))
        assert "alice の切替メモ" in listed
    finally:
        set_stdio_user(None)


def test_switch_user_returns_target_categories():
    create_user_db("alice")
    # 切り替え先 alice のメモが持つカテゴリが切り替え結果に含まれる
    create_memo_db("alice", "仕事", "", category="work")
    create_memo_db("alice", "私用", "", category="private")
    set_stdio_user(ADMIN_USER)
    try:
        switched = asyncio.run(_call("switch_user", {"target": "alice"}))
    finally:
        set_stdio_user(None)
    assert "メモのカテゴリ:" in switched
    # 正規化済み (大文字)・名前順で列挙される
    assert "PRIVATE" in switched
    assert "WORK" in switched


def test_switch_user_rejects_unregistered_target():
    set_stdio_user(ADMIN_USER)
    try:
        result = asyncio.run(_call("switch_user", {"target": "ghost"}))
    finally:
        set_stdio_user(None)
    assert "is not registered" in result


def test_switch_user_rejects_unidentified_caller():
    set_stdio_user(None)
    result = asyncio.run(_call("switch_user", {"target": "alice"}))
    assert result.startswith("Error: user is not identified")


def test_http_client_id_registers_initial_user(monkeypatch):
    _patch_http(monkeypatch, {"user": "alice", "client_id": "c1"})
    assert auth_module.current_user() == "alice"
    assert auth_module._http_user_by_client["c1"] == "alice"


def test_http_setdefault_keeps_first_user(monkeypatch):
    _patch_http(monkeypatch, {"user": "alice", "client_id": "c1"})
    auth_module.current_user()
    # 同じ client_id で別の ?user= が来ても setdefault で初回値を保持する
    _patch_http(monkeypatch, {"user": "bob", "client_id": "c1"})
    assert auth_module.current_user() == "alice"


def test_http_switch_then_current_user(monkeypatch):
    _patch_http(monkeypatch, {"user": "alice", "client_id": "c1"})
    auth_module.current_user()
    auth_module.switch_http_user("c1", "bob")
    assert auth_module.current_user() == "bob"


def test_http_no_client_id_is_backward_compatible(monkeypatch):
    _patch_http(monkeypatch, {"user": "alice"})  # client_id 無し → 従来通り ?user=
    assert auth_module.current_user() == "alice"
    assert auth_module._http_user_by_client == {}


def test_audit_log_emits_info_line_per_tool_call(caplog):
    create_user_db("logwatcher")
    set_stdio_user("logwatcher")
    try:
        with caplog.at_level(logging.INFO, logger="memo.server.mcp.logging_middleware"):
            asyncio.run(_call("create_memo", {"title": "ログ確認"}))
    finally:
        set_stdio_user(None)
    msgs = [r.getMessage() for r in caplog.records if r.name == "memo.server.mcp.logging_middleware"]
    assert any("tool=create_memo" in m and "user=logwatcher" in m for m in msgs)


def test_audit_log_debug_includes_initialize(caplog):
    set_stdio_user(ADMIN_USER)
    try:
        with caplog.at_level(logging.DEBUG, logger="memo.server.mcp.logging_middleware"):
            asyncio.run(_list_tool_names())  # 接続時に initialize が走る
    finally:
        set_stdio_user(None)
    msgs = [r.getMessage() for r in caplog.records if r.name == "memo.server.mcp.logging_middleware"]
    assert any("method=initialize" in m for m in msgs)


async def _main():
    set_stdio_user(ADMIN_USER)  # admin はシード済みなので必ず接続できる
    async with Client(mcp) as client:
        print("=== Server Info ===")
        print(f"Name: {client.initialize_result.serverInfo.name}")
        print()

        tools = await client.list_tools()
        print(f"=== Tools ({len(tools)}) ===")
        for tool in tools:
            print(f"  - {tool.name}")
            if tool.description:
                first_line = tool.description.strip().splitlines()[0]
                print(f"    {first_line}")
            if tool.inputSchema and tool.inputSchema.get("properties"):
                params = ", ".join(tool.inputSchema["properties"].keys())
                print(f"    params: {params}")
            print()


if __name__ == "__main__":
    asyncio.run(_main())

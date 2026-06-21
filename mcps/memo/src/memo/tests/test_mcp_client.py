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

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from memo.infra.database import ADMIN_USER
from memo.infra.embedding import EmbeddingError
from memo.repository.category import create_category_db
from memo.repository.memo import create_memo_db
from memo.repository.user import create_user_db
from memo.server.mcp import auth as auth_module
from memo.server.mcp.app import mcp  # init_db() はモジュール読み込み時に実行される
from memo.server.mcp.auth import set_stdio_user
from memo.service import memo as service

# admin タグの付いた管理ツール。admin に切り替わった接続でのみ公開される。
ADMIN_TOOLS = {
    "create_user",
    "get_user",
    "list_users",
    "update_user",
    "delete_user",
}

# 常に公開されるツール (admin ゲートの対象外)。switch_user は admin 専用ではない。
NON_ADMIN_TOOLS = {
    "create_memo",
    "get_memo",
    "list_memos",
    "search_memos",
    "semantic_search_memos",
    "update_memo",
    "delete_memo",
    "create_category",
    "list_categories",
    "switch_user",
}

EXPECTED_TOOLS = NON_ADMIN_TOOLS | ADMIN_TOOLS


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


async def _switch_then_list(target: str) -> set[str]:
    """同一セッション内で target に switch_user してからツール一覧を取得する。

    admin タグのツールはセッション単位で有効化されるため、switch_user と list_tools は
    必ず同じ接続 (Client コンテキスト) 内で行う必要がある。
    """
    async with Client(mcp) as client:
        await client.call_tool("switch_user", {"target": target})
        tools = await client.list_tools()
        return {t.name for t in tools}


async def _switch_then_call(target: str, tool: str, args: dict) -> str:
    """同一セッション内で target に switch_user してから tool を呼ぶ。"""
    async with Client(mcp) as client:
        await client.call_tool("switch_user", {"target": target})
        result = await client.call_tool(tool, args)
        return result.data


def test_fresh_session_hides_admin_tools():
    # サーバーレベルの既定で、switch する前のどの接続でも admin タグのツールは出ない。
    set_stdio_user(ADMIN_USER)  # admin で始めても switch 前は非公開
    try:
        names = asyncio.run(_list_tool_names())
    finally:
        set_stdio_user(None)
    assert NON_ADMIN_TOOLS <= names
    assert not (ADMIN_TOOLS & names)


def test_switch_to_admin_enables_admin_tools():
    # admin に切り替わった接続でだけ admin タグのツールが公開される (セッションレベル)。
    set_stdio_user(ADMIN_USER)
    try:
        names = asyncio.run(_switch_then_list(ADMIN_USER))
    finally:
        set_stdio_user(None)
    assert EXPECTED_TOOLS <= names


def test_switch_away_from_admin_hides_admin_tools():
    # admin から別ユーザーへ切り替えると、その接続では admin タグのツールが再び消える。
    create_user_db("alice")
    set_stdio_user(ADMIN_USER)
    try:
        names = asyncio.run(_switch_then_list("alice"))
    finally:
        set_stdio_user(None)
    assert NON_ADMIN_TOOLS <= names
    assert not (ADMIN_TOOLS & names)


def test_admin_tools_stay_hidden_when_auto_enable_disabled(monkeypatch):
    # 自動有効化を env で無効化すると、admin に切り替えても管理ツールは公開されない。
    monkeypatch.setenv("MEMO_ADMIN_TOOLS_AUTO_ENABLE", "false")
    set_stdio_user(ADMIN_USER)
    try:
        names = asyncio.run(_switch_then_list(ADMIN_USER))
    finally:
        set_stdio_user(None)
    assert NON_ADMIN_TOOLS <= names
    assert not (ADMIN_TOOLS & names)


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


def test_create_category_and_list():
    create_user_db("newcatuser")
    set_stdio_user("newcatuser")
    try:
        created = asyncio.run(_call("create_category", {"name": "work"}))
        assert created == "Created category 'WORK'."
        listed = asyncio.run(_call("list_categories", {}))
        assert "WORK" in listed
        # 重複はその旨を返す
        dup = asyncio.run(_call("create_category", {"name": "WORK"}))
        assert "already exists" in dup
    finally:
        set_stdio_user(None)


def test_create_memo_rejects_unregistered_category():
    create_user_db("rejectcat")
    set_stdio_user("rejectcat")
    try:
        # 未登録カテゴリでのメモ作成は拒否される (先に create_category が必要)
        result = asyncio.run(
            _call("create_memo", {"title": "メモ", "category": "work"})
        )
        assert "is not registered" in result
    finally:
        set_stdio_user(None)


def test_category_filter_roundtrip():
    create_user_db("catuser")
    set_stdio_user("catuser")
    try:
        # 先にカテゴリを登録してからメモを作る (未登録カテゴリは拒否されるため)
        asyncio.run(_call("create_category", {"name": "work"}))
        asyncio.run(_call("create_category", {"name": "private"}))
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


def test_disabled_admin_tool_call_is_rejected_for_non_admin():
    # admin タグのツールはサーバーレベルで無効なので、非 admin が名指しで呼ぶと
    # FastMCP が「Unknown tool」で拒否する (一覧に出ないので存在も漏らさない)。
    create_user_db("alice")
    set_stdio_user("alice")  # 登録済みだが admin ではない
    try:
        with pytest.raises(ToolError) as excinfo:
            asyncio.run(_call("list_users", {}))
    finally:
        set_stdio_user(None)
    assert "Unknown tool" in str(excinfo.value)


def test_admin_tool_callable_after_switch_to_admin():
    # admin に切り替えた同一セッションでは admin タグのツールを呼び出せる。
    set_stdio_user(ADMIN_USER)
    try:
        result = asyncio.run(_switch_then_call(ADMIN_USER, "list_users", {}))
    finally:
        set_stdio_user(None)
    assert ADMIN_USER in result  # admin ユーザーが一覧に含まれる


def test_admin_tool_stays_uncallable_when_auto_enable_disabled(monkeypatch):
    # 自動有効化を無効にすると、admin に切り替えても呼び出しは拒否されたまま。
    monkeypatch.setenv("MEMO_ADMIN_TOOLS_AUTO_ENABLE", "off")
    set_stdio_user(ADMIN_USER)
    try:
        with pytest.raises(ToolError) as excinfo:
            asyncio.run(_switch_then_call(ADMIN_USER, "list_users", {}))
    finally:
        set_stdio_user(None)
    assert "Unknown tool" in str(excinfo.value)


def test_admin_cannot_see_other_users_memos():
    # admin は通常ユーザーと同じく自分のメモしか見えない (完全分離)。
    create_user_db("alice")
    create_memo_db("alice", "alice の会議メモ", "")
    set_stdio_user(ADMIN_USER)
    try:
        listed = asyncio.run(_call("list_memos", {}))
    finally:
        set_stdio_user(None)
    assert "alice の会議メモ" not in listed


def test_admin_can_create_user():
    set_stdio_user(ADMIN_USER)
    try:
        # admin タグのツールはセッションで有効化してから呼ぶ (switch_user 経由)。
        result = asyncio.run(_switch_then_call(ADMIN_USER, "create_user", {"name": "newbie"}))
    finally:
        set_stdio_user(None)
    assert result == "Created user 'newbie'."


def test_admin_cannot_delete_self():
    set_stdio_user(ADMIN_USER)
    try:
        result = asyncio.run(
            _switch_then_call(ADMIN_USER, "delete_user", {"name": ADMIN_USER})
        )
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
    # 切り替え先 alice が持つカテゴリが切り替え結果に含まれる
    create_category_db("alice", "work")
    create_category_db("alice", "private")
    set_stdio_user(ADMIN_USER)
    try:
        switched = asyncio.run(_call("switch_user", {"target": "alice"}))
    finally:
        set_stdio_user(None)
    assert "カテゴリ:" in switched
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

        # admin タグのツールはセッションで有効化してから一覧に出る (switch_user 経由)。
        await client.call_tool("switch_user", {"target": ADMIN_USER})
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

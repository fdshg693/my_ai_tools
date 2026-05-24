"""MCPクライアントでサーバーの利用可能なツールを確認するテスト。

サーバーはインプロセスで起動し、ネットワークを使わずにテストする。
スクリプトとしても (`python -m memo.tests.test_mcp_client`)、pytest としても実行できる。
pytest-asyncio に依存しないよう、各テストは同期関数内で asyncio.run() する。

インプロセス接続には HTTP リクエストコンテキストが無いため、ユーザーは
stdio と同じく `set_stdio_user()` で固定する。
"""

import asyncio

from fastmcp import Client

from memo.auth import set_stdio_user
from memo.database import ADMIN_USER, create_memo_db, create_user_db
from memo.main import mcp  # init_db() はモジュール読み込み時に実行される

EXPECTED_TOOLS = {
    "create_memo",
    "get_memo",
    "list_memos",
    "search_memos",
    "update_memo",
    "delete_memo",
    "create_user",
    "get_user",
    "list_users",
    "update_user",
    "delete_user",
}


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

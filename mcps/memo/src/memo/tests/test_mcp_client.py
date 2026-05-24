"""MCPクライアントでサーバーの利用可能なツールを確認するテスト。

サーバーはインプロセスで起動し、ネットワークを使わずにテストする。
スクリプトとしても (`python -m memo.tests.test_mcp_client`)、pytest としても実行できる。
pytest-asyncio に依存しないよう、各テストは同期関数内で asyncio.run() する。
"""

import asyncio

from fastmcp import Client

from memo.main import mcp  # init_db() はモジュール読み込み時に実行される

EXPECTED_TOOLS = {
    "create_memo",
    "get_memo",
    "list_memos",
    "search_memos",
    "update_memo",
    "delete_memo",
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


def test_expected_tools_registered():
    names = asyncio.run(_list_tool_names())
    assert EXPECTED_TOOLS <= names


def test_crud_roundtrip():
    created, searched = asyncio.run(_crud_roundtrip())
    assert "会議メモ" in created
    assert "会議メモ" in searched


async def _main():
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

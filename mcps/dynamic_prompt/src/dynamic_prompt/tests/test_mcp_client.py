"""MCPクライアントを使ってサーバーの利用可能なツール・リソース・プロンプトを確認するテスト。

サーバーはインプロセスで起動し、ネットワークを使わずにテストする。
"""

import asyncio

from fastmcp import Client

from dynamic_prompt.main import mcp  # init_db() はモジュール読み込み時に実行される


async def main():

    async with Client(mcp) as client:
        print("=== Server Info ===")
        print(f"Name: {client.initialize_result.serverInfo.name}")
        print()

        # ツール一覧
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

        # リソース一覧
        resources = await client.list_resources()
        print(f"=== Resources ({len(resources)}) ===")
        if resources:
            for resource in resources:
                print(f"  - {resource.name}: {resource.uri}")
        else:
            print("  (none)")
        print()

        # プロンプト一覧
        prompts = await client.list_prompts()
        print(f"=== Prompts ({len(prompts)}) ===")
        if prompts:
            for prompt in prompts:
                print(f"  - {prompt.name}: {prompt.description or '(no description)'}")
        else:
            print("  (none)")
        print()

        # ツール呼び出しテスト: get_instruction (description に instruction 一覧が埋め込まれていることを確認)
        print("=== get_instruction description ===")
        gi = next(t for t in tools if t.name == "get_instruction")
        print(gi.description)


if __name__ == "__main__":
    asyncio.run(main())

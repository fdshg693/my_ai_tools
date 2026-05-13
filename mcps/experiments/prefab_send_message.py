# ボタンを押すと、MCPホストに「Hi」というメッセージを送るサンプルです。
# Github Copilot では入力欄に直接入ったものの、自動送信までは行われなかった

from fastmcp import FastMCP

from prefab_ui.actions.mcp import SendMessage
from prefab_ui.app import PrefabApp
from prefab_ui.components import Button, Column, Heading

mcp = FastMCP("Send Message Demo")


@mcp.tool(app=True)
def say_hi() -> PrefabApp:
    """Show a button that sends 'Hi' to the MCP host."""
    with Column(gap=4, css_class="p-6") as view:
        Heading("Send Message Demo")
        Button("Say Hi", on_click=SendMessage("Hi"))

    return PrefabApp(view=view)


def main():
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()

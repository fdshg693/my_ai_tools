# 参考: https://prefab.prefect.io/docs/running/fastmcp#calling-back-to-the-server
# 人が手動で入力しても結果が反映されないが、CallToolを直接使うと結果が表示される。

import logging
from pathlib import Path

from prefab_ui.actions import SetState
from prefab_ui.actions.mcp import CallTool
from prefab_ui.rx import RESULT
from prefab_ui.components import Input, Column, Slot, ForEach, Text

from fastmcp import FastMCP

from prefab_ui.app import PrefabApp

LOG_FILE = Path(__file__).parent / "debug.log"
logging.basicConfig(
    filename=str(LOG_FILE),
    level=logging.DEBUG,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    force=True,
)
logger = logging.getLogger(__name__)

mcp = FastMCP("My App Server")


original_call_tool = mcp.call_tool


async def _logging_call_tool(name, arguments=None, **kwargs):
    logger.info(">>> TOOL CALLED: %s args=%s", name, arguments)
    return await original_call_tool(name, arguments, **kwargs)


mcp.call_tool = _logging_call_tool

ITEMS = [
    {"name": "Apple"},
    {"name": "Banana"},
    {"name": "Cherry"},
    {"name": "Date"},
    {"name": "Elderberry"},
    {"name": "Fig"},
    {"name": "Grape"},
]


@mcp.tool(app=True)
def custom_browse() -> PrefabApp:
    logger.debug("custom_browse() called")
    with Column(gap=4) as view:
        Input(
            name="q",
            placeholder="custom_search...",
            on_change=[
                SetState("q", "{{ $event }}"),
                CallTool(
                    "custom_search",
                    arguments={"q": "{{ $event }}"},
                    on_success=SetState("results", RESULT),
                ),
            ],
        )
        Slot("results")
    app = PrefabApp(view=view, state={"q": "", "results": None})
    logger.debug("custom_browse() returning: %s", app.to_json())
    return app


@mcp.tool
def custom_search(q: str = "") -> PrefabApp:
    logger.debug("custom_search() called with q=%r", q)
    matches = [i for i in ITEMS if q.lower() in i["name"].lower()] if q else ITEMS
    logger.debug("custom_search() matches: %s", matches)

    # パターン1: 単純なTextだけ返す（Slotが機能するかの最小テスト）
    result_text = ", ".join(m["name"] for m in matches) if matches else "(no results)"
    view = Text(result_text)
    app = PrefabApp(view=view)
    logger.debug("custom_search() returning: %s", app.to_json())
    return app


def main():
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()

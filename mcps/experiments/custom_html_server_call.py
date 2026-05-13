# prefab_server_call.py と同等の機能をカスタムHTMLで実装
# 参考: https://gofastmcp.com/apps/low-level

import json
import logging
from pathlib import Path

from fastmcp import FastMCP
from fastmcp.server.apps import AppConfig, ResourceCSP

LOG_FILE = Path(__file__).parent / "debug.log"
logging.basicConfig(
    filename=str(LOG_FILE),
    level=logging.DEBUG,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    force=True,
)
logger = logging.getLogger(__name__)

mcp = FastMCP("My App Server (Custom HTML)")

ITEMS = [
    {"name": "Apple"},
    {"name": "Banana"},
    {"name": "Cherry"},
    {"name": "Date"},
    {"name": "Elderberry"},
    {"name": "Fig"},
    {"name": "Grape"},
]

VIEW_URI = "ui://custom_search-app/view.html"


@mcp.tool(app=AppConfig(resource_uri=VIEW_URI))
def custom_browse() -> str:
    """検索UIを表示する。初期状態では全アイテムを返す。"""
    logger.debug("custom_browse() called")
    matches = ITEMS
    result = json.dumps({"query": "", "results": matches})
    logger.debug("custom_browse() returning: %s", result)
    return result


@mcp.tool(app=AppConfig(visibility=["app"]))
def custom_search(q: str = "") -> str:
    """クエリに一致するアイテムを返す。UIからのみ呼び出し可能。"""
    logger.debug("custom_search() called with q=%r", q)
    matches = [i for i in ITEMS if q.lower() in i["name"].lower()] if q else ITEMS
    logger.debug("custom_search() matches: %s", matches)
    result = json.dumps({"query": q, "results": matches})
    logger.debug("custom_search() returning: %s", result)
    return result


@mcp.resource(
    VIEW_URI,
    app=AppConfig(csp=ResourceCSP(resource_domains=["https://unpkg.com"])),
)
def view() -> str:
    """検索アプリのUI"""
    return """\
<!DOCTYPE html>
<html>
<head>
  <meta name="color-scheme" content="light dark">
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      padding: 16px;
      background: transparent;
      color: light-dark(#333, #eee);
    }
    input {
      width: 100%;
      padding: 8px 12px;
      font-size: 14px;
      border: 1px solid light-dark(#ccc, #555);
      border-radius: 6px;
      background: light-dark(#fff, #2a2a2a);
      color: inherit;
      outline: none;
    }
    input:focus { border-color: #5b9bd5; }
    .results {
      margin-top: 12px;
      display: flex;
      flex-direction: column;
      gap: 4px;
    }
    .item {
      padding: 8px 12px;
      background: light-dark(#f5f5f5, #2a2a2a);
      border-radius: 4px;
      font-size: 14px;
    }
    .no-results {
      padding: 8px 12px;
      color: light-dark(#999, #777);
      font-style: italic;
    }
  </style>
</head>
<body>
  <input id="custom_search" type="text" placeholder="custom_search..." />
  <div id="results" class="results"></div>

  <script type="module">
    import { App } from
      "https://unpkg.com/@modelcontextprotocol/ext-apps@0.4.0/app-with-deps";

    const app = new App({ name: "custom_search App", version: "1.0.0" });
    const resultsEl = document.getElementById("results");
    const custom_searchEl = document.getElementById("custom_search");

    function renderResults(data) {
      try {
        const parsed = typeof data === "string" ? JSON.parse(data) : data;
        const items = parsed.results || [];
        if (items.length === 0) {
          resultsEl.innerHTML = '<div class="no-results">(no results)</div>';
          return;
        }
        resultsEl.innerHTML = items
          .map(i => `<div class="item">${i.name}</div>`)
          .join("");
      } catch (e) {
        resultsEl.innerHTML = '<div class="no-results">Error: ' + e.message + '</div>';
      }
    }

    // ツール結果を受け取って描画
    app.ontoolresult = ({ content }) => {
      const text = content?.find(c => c.type === "text");
      if (text) {
        renderResults(text.text);
      }
    };

    // 入力変更時にcustom_searchツールを呼び出す
    let debounceTimer;
    custom_searchEl.addEventListener("input", (e) => {
      clearTimeout(debounceTimer);
      debounceTimer = setTimeout(async () => {
        const result = await app.callServerTool({ name: "custom_search", arguments: { q: e.target.value } });
        const text = result?.content?.find(c => c.type === "text");
        if (text) {
          renderResults(text.text);
        }
      }, 200);
    });

    await app.connect();
  </script>
</body>
</html>"""


def main():
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()

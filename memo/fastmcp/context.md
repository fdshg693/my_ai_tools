# Context の依存性注入

公式: https://gofastmcp.com/servers/context
（確認に使った版: **fastmcp 3.1.1**）

ツール関数に `ctx: Context` 引数を足すと、FastMCP が **現在のリクエスト/セッションの
コンテキスト** を自動で注入する。クライアントはこの引数を渡さない（渡せない）。

```python
from fastmcp import Context

@mcp.tool
async def do_something(target: str, ctx: Context) -> str:
    # ctx 経由でセッション操作（可視性の変更など）ができる
    await ctx.enable_components(tags={"admin"})
    return f"done for {target}"
```

## 確認した事実（3.1.1）

- **引数名は `ctx` でなくてもよい**。判定は型注釈 `Context` で行われる
  （慣習として `ctx` を使う）。
- **クライアント向けスキーマに出ない**。`list_tools()` で得られるツールの
  `inputSchema.properties` に `ctx` は含まれない（上の例なら `target` だけ）。

  ```python
  # 検証: switch_user(target, ctx) → クライアントには target だけ見える
  props = tools["switch_user"].inputSchema["properties"].keys()
  # => ['target']
  ```

- `ctx` のセッション系メソッド（`enable_components` / `disable_components` /
  `reset_visibility` など）は **async**。よって `ctx` を使うツールは `async def` にして
  `await` する。同期ツールのままだと `await` できない。

## 主な用途（公式参照）

`Context` はセッション可視性の変更（→ [visibility.md](./visibility.md)）のほか、
ログ送信・進捗通知・リクエスト情報の取得など多くの機能を持つ。**使う前に公式の
Context ページで該当メソッドの存在とシグネチャを確認すること**（記憶で書かない）。

## 注意

- 注入されるのは **リクエストコンテキストの中だけ**。コンテキスト外で `Context` の
  リクエスト依存メソッドを呼ぶと例外になりうる。
- HTTP の「接続中ユーザー」を読むだけなら `get_http_request()` でクエリを見る方法もある
  （`mcps/memo` の `auth.py` はこちらを使い、識別は `Context` に依存していない）。
  目的に応じて使い分ける。

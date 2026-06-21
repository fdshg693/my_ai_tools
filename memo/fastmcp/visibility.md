# コンポーネント可視性（ツールの有効/無効）

公式: https://gofastmcp.com/servers/visibility
（確認に使った版: **fastmcp 3.1.1**）

ツール・リソース・プロンプトの「見える/呼べる」を、**サーバー全体**と**セッション単位**の
2 段で制御できる。ミドルウェアで `tools/list` を自作フィルタするのではなく、この公式 API を使う。

## タグを付ける

可視性 API はタグ単位でまとめて操作できる。ツールにタグを付ける:

```python
@mcp.tool(tags={"admin"})
def delete_user(name: str) -> str:
    ...
```

## サーバーレベル（起動時の既定）

`FastMCP` インスタンスのメソッドで、登録済みコンポーネントをまとめて有効/無効にする。
**ツールを登録した後**に呼ぶこと（タグが存在しないと対象にならない）。

```python
mcp.disable(tags={"admin"})                 # admin タグを全部無効化
mcp.disable(keys={"tool:delete_everything"})# 特定キーだけ無効化
mcp.enable(tags={"admin"})                   # 再度有効化
mcp.disable(keys={"tool:debug"}, tags={"dangerous"})  # 併用可
```

- 「**いずれか**の無効タグを持てば無効」。
- 許可リスト方式（`only=True`）：指定したものだけ有効、他は全部隠す。
  ```python
  mcp.enable(tags={"safe"}, only=True)
  ```
- `disable` のシグネチャ（3.1.1 で確認）:
  `disable(*, names=None, keys=None, version=None, tags=None, components=None)`
  （`components` は `{'tool','resource','template','prompt'}` の絞り込み）

無効化されたツールは **一覧に出ない**。それでも名指しで `call_tool` するとエラーになる:

```
fastmcp.exceptions.ToolError -> Unknown tool: 'admin_tool'
```

→ 「存在しない」扱いなので、ツールの存在自体を漏らさない。

## セッション単位（接続ごと）

ツールの中で `ctx: Context` を受け取り、`ctx` のメソッドで **その接続だけ** の可視性を変える。
サーバーレベルの既定を上書きでき、変更すると **`notifications/tools/list_changed` が自動送信**
されるので、クライアントはツール一覧を取り直して反映できる。

```python
from fastmcp import Context

@mcp.tool
async def unlock_premium(ctx: Context) -> str:
    await ctx.enable_components(tags={"premium"})   # このセッションで有効化
    return "unlocked"

@mcp.tool
async def lock(ctx: Context) -> str:
    await ctx.disable_components(tags={"premium"})  # このセッションで無効化
    return "locked"

@mcp.tool
async def reset(ctx: Context) -> str:
    await ctx.reset_visibility()                    # 既定に戻す
    return "reset"
```

- `enable_components` / `disable_components` の絞り込み引数:
  `names`, `keys`, `version`, `tags`, `components`, `match_all`。
- これらは **async**。呼ぶツールは `async def` にして `await` する。
- `ctx: Context` 引数は FastMCP が注入し、**クライアントに見えるスキーマには出ない**
  （`inputSchema.properties` に `ctx` は現れない）。

## 手元で確認した挙動（3.1.1）

`mcp.disable(tags={"admin"})` を効かせた状態で、インプロセス `Client` から観察:

| 操作 | 結果 |
|------|------|
| 新規セッションで `list_tools` | admin タグのツールは出ない（既定が効く）|
| 同一セッションで `enable_components(tags={"admin"})` 後に `list_tools` | admin ツールが出る |
| さらに同一セッションで再度 `list_tools` | 出たまま（セッション内で持続）|
| 同一セッションで `disable_components(...)` 後 | 再び消える |
| 別の新規セッションで `list_tools` | 既定（非表示）に戻っている |
| 無効状態のツールを名指しで `call_tool` | `ToolError: Unknown tool: ...` |

→ **セッションの可視化変更はその接続限定で、接続をまたがない**。新規接続は常に
サーバーレベルの既定から始まる。

## 落とし穴：ミドルウェアで自作しないこと

`on_list_tools` で一覧をフィルタする方式は一見動くが、

- 一覧を変えても **クライアントに `list_changed` 通知が飛ばない**ため、
  「あとから有効化したのにクライアント側に伝わらない」等の不整合が起きる。
- `on_call_tool` での拒否やタグ判定も自前で書くことになり、公式機能の二重実装になる。

可視性は公式の `mcp.disable/enable` ＋ `ctx.*_components` で実装する。ミドルウェアは
監査ログのような **横断的関心事** に限る。

## 実装例（このリポジトリ）

`mcps/memo` のユーザー管理ツール（admin 専用）でこの 2 段構えを使っている:

- 起動時に `mcp.disable(tags={"admin"})`（サーバーレベル既定 = 無効）。
- `switch_user` ツール（`async def ... ctx: Context`）が、admin に切り替わった接続だけ
  `ctx.enable_components(tags={"admin"})`、admin から離れたら `disable_components(...)`。
- 環境変数 `MEMO_ADMIN_TOOLS_AUTO_ENABLE` を falsy にすると、このセッション有効化を抑止
  （危険な自動有効化のオフスイッチ）。

コード: `mcps/memo/src/memo/server/mcp/admin_tools.py`
／設計メモ: `mcps/memo/claude/features/user.md`

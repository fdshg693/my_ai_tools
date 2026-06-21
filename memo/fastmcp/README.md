# FastMCP 学習メモ

[FastMCP](https://gofastmcp.com/) について学んだことをトピックごとにまとめた個人メモ。
公式ドキュメントを読みながら、**実際に手元の FastMCP で確認した事実**を中心に残す
（推測は残さない。確認方法も併記する）。

## 大原則：FastMCP は必ず公式ドキュメントを参照する

FastMCP の API はバージョンごとに具体的で、記憶や推測で書くと容易に間違える。
**新しい API を使う前に必ず公式ドキュメント（https://gofastmcp.com）の該当ページを読み、
インストール済みのバージョンで存在とシグネチャを確認する。**

確認の定番手順:

```bash
# バージョン確認
uv run python -c "import fastmcp; print(fastmcp.__version__)"

# シンボルの存在・シグネチャ確認
uv run python -c "
import inspect
from fastmcp import FastMCP, Context
m = FastMCP('t')
print(hasattr(m, 'disable'), inspect.signature(m.disable))
print(hasattr(Context, 'enable_components'))
"
```

実例の失敗：ツール一覧をミドルウェアで書き換えて「ツールの有効/無効」を実装しようとすると、
`notifications/tools/list_changed` がクライアントへ飛ばず、切り替えが反映されない。
公式の可視性 API（後述）はこの通知を自動で送る。**フレームワークが用意した機能を、
低レイヤーで自作しないこと。** → [visibility.md](./visibility.md)

## ファイル一覧

| ファイル | 内容 |
|---------|------|
| [LINKS.md](./LINKS.md) | 公式ドキュメント・GitHub・LLM 用テキスト等の参照リンク集 |
| [beginner.md](./beginner.md) | 最小構成（`@mcp.tool` / `mcp.run()`）と `run()` の内部（`anyio.run`）|
| [basic.md](./basic.md) | ツール説明文の明示指定と、可視性（サーバー/セッション）の入口リンク |
| [visibility.md](./visibility.md) | **コンポーネント可視性**（サーバーレベルの有効/無効 ＋ セッション単位の有効/無効）の詳細と検証結果 |
| [context.md](./context.md) | `Context` の依存性注入（`ctx: Context` 引数・非同期ツール・スキーマから隠れる挙動）|
| [PrefabApp.md](./PrefabApp.md) | PrefabApp の参照リンク |

## 関連する実装例

このメモの内容を実際に使った例が同リポジトリの `mcps/memo`（メモ管理 MCP サーバー）にある。
特にコンポーネント可視性は、ユーザー管理ツール（admin 専用）を「既定はサーバーレベルで無効、
`switch_user` で admin に切り替えた接続だけセッション単位で有効化」する形で使っている。
- 実装: `mcps/memo/src/memo/server/mcp/admin_tools.py`
- 設計メモ: `mcps/memo/claude/features/user.md` の「Admin tool visibility」節

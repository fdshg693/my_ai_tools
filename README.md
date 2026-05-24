# my_ai_tools

AI が利用するツールや AI エージェントをまとめていくリポジトリ。

現状の中身は MCP サーバーが中心。今後、別系統の MCP サーバーや AI エージェントを追加していく予定。

> **注**: 名前に `experiments` を含むディレクトリ (例: [mcps/experiments/](mcps/experiments/)) はすべて実験用で、他から参照されることは想定していない。

## リポジトリ構成

| パス | 内容 |
|------|------|
| [mcps/dynamic_prompt/](mcps/dynamic_prompt/) | 外国語学習用 MCP サーバー (後述) |
| [mcps/memo/](mcps/memo/) | シンプルなメモ管理 MCP サーバー (後述) |
| [mcps/experiments/](mcps/experiments/) | 実験用。他から使わない |
| [memo/](memo/) | 作業メモ・リンク集 |
| [pyproject.toml](pyproject.toml) | uv ワークスペース定義 (各 MCP サーバーを member として束ねる) |

uv のワークスペースとして管理しており、各 MCP サーバーは `mcps/<name>/` 配下に独立した Python パッケージとして配置する。

## 既存の MCP サーバー

### dynamic_prompt

AI に外国語学習を伴走させるための MCP サーバー。

- 会話で出てきた未知語を SQLite に蓄積し、`unlearned → wrong → memory_test` のステータス遷移で忘却対策の再出題を AI に行わせる
- 同プロセスで Starlette + SSE のクイズ Web UI を立ち上げ、AI が出題したクイズをローカルブラウザにリアルタイムで送り込む (選択式 / 自由回答の両対応)
- 言語ごとの教え方やユーザーの母語などは YAML で宣言的に管理し、`get_instruction` ツール経由で AI に渡す
- stdio (Claude Desktop) と HTTP + Google OAuth (Cloud Run) の両モードで動作

詳しい使い方・ツール一覧・デプロイ手順は [mcps/dynamic_prompt/README.md](mcps/dynamic_prompt/README.md) を参照。

### memo

タイトル・概要を持つメモを管理するシンプルな MCP サーバー。

- SQLite にメモ (タイトル + 概要) を保存する
- CRUD (作成・取得・一覧・更新・削除) を MCP ツールとして提供
- 検索はタイトルの**部分一致**で行う

詳しい使い方・ツール一覧は [mcps/memo/README.md](mcps/memo/README.md) を参照。

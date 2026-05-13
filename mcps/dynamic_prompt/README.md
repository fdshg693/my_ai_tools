# dynamic_prompt

AI に外国語学習を伴走させるための MCP サーバー。AI 単体では実現しにくい「単語の蓄積」「忘却対策のための復習」「ブラウザでのインタラクティブなクイズ」を MCP ツールとして提供する。

## ここが売り

- **学習語彙の永続化と忘却曲線**: 会話で出てきた知らない単語を SQLite に蓄積し、`unlearned → wrong → memory_test` のステータス遷移で「間違えた単語は時間を置いて再出題」を AI に自動でやらせる。
- **ブラウザクイズ UI 同梱**: MCP サーバーと同じプロセスで Web サーバー (Starlette + SSE) を立ち上げ、AI が出題したクイズをローカルブラウザにリアルタイムプッシュする。選択式と自由回答の両方に対応 (自由回答は AI が後から採点)。
- **YAML 駆動の指示テンプレート**: 言語ごとの教え方・ユーザーの母語・レベルなどを YAML で宣言的に書き、`get_instruction` ツールから AI に渡す。言語追加はファイル 1 枚追加するだけ。
- **stdio / HTTP 両対応**: ローカル (Claude Desktop など stdio) と Cloud Run (HTTP + OAuth) のどちらでも動く。

## 大まかな流れ

```
ユーザーが AI と外国語で雑談
  │
  ├─ AI が新出単語を save_words で DB に蓄積
  ├─ AI が send_quiz / send_free_quiz でブラウザにクイズを送信
  │     └─ ユーザーがブラウザで回答 → 結果が DB に保存
  ├─ AI が get_quiz_results / get_unscored_quizzes で結果を取得 (自由回答は AI が採点)
  └─ AI が answer_words で正誤を記録 → 単語ステータスが遷移
       (間違えた単語は memory_test_period_hours の間隠され、後で再出題)
```

提供される MCP ツールは 12 個。各ツールの役割と呼び出し順・依存関係は [TOOLS.md](TOOLS.md) にまとめている。

## 導入

### 1. ローカル実行 (stdio)

Claude Desktop など stdio で接続するクライアント向け。

```bash
uv run dynamic_prompt
```

- MCP サーバーと一緒にクイズ Web サーバー (`http://127.0.0.1:8765` 付近) が自動起動する。ポートは `8765–8767` のプールから空いているものを使う ([app_config.yaml](src/dynamic_prompt/prompts/app_config.yaml) で変更可)。
- SQLite DB は既定で [src/dynamic_prompt/vocab.db](src/dynamic_prompt/vocab.db)。`DB_PATH` 環境変数で差し替え可能。
- **注意**: `fastmcp run <path>` でファイルパスを渡すとツールが二重登録されて 0 個になる。エントリーポイント `dynamic_prompt` を直接呼ぶこと。

### 2. リモート実行 (HTTP + OAuth)

Claude Web (claude.ai) など HTTP で接続するクライアント向け。Cloud Run へのデプロイ手順は [infra/CLAUDE.md](infra/CLAUDE.md) を参照。

```bash
TRANSPORT=http PORT=8080 \
GOOGLE_CLIENT_ID=...  GOOGLE_CLIENT_SECRET=... \
SERVICE_URL=https://<your-host> \
uv run dynamic_prompt
```

| 環境変数 | 用途 |
|---------|------|
| `TRANSPORT` | `http` で HTTP モード。未設定 / `stdio` で stdio モード |
| `PORT` / `HOST` | uvicorn のバインド先 |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | 設定されていれば `/mcp` を Google OAuth で保護する。未設定なら認証なし (ローカル開発向け) |
| `SERVICE_URL` | OAuth コールバックの `base_url`。本番は公開 URL を指定 |
| `DB_PATH` | SQLite DB のパス。Cloud Run では GCS マウント上を指す |

HTTP モードでは単一ポートで以下を提供する。

| Path | 用途 |
|------|------|
| `/mcp` | MCP エンドポイント (OAuth 保護対象) |
| `/health` | ヘルスチェック (認証不要) |
| `/` `/events` `/api/*` `/static/*` | クイズ Web UI (認証不要) |

## このサーバー固有の認証フロー

**HTTP モードで `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` を設定したとき**は、FastMCP の `GoogleProvider` が `/mcp` を OAuth 2.1 で保護する。クライアント (Claude.ai 等) から見ると 2 段構えになる。

```
Claude.ai  ──(外側 OAuth)──>  dynamic_prompt  ──(内側 OAuth)──>  Google
```

- **外側**: クライアント ↔ dynamic_prompt。MCP エンドポイントへのアクセス制御。
- **内側**: dynamic_prompt ↔ Google。ユーザーの身元確認 (Google ログイン)。

クライアント (Claude.ai など) が **Dynamic Client Registration を自動で行わない**場合、初回に手動で登録する必要がある。

```bash
curl -X POST https://<SERVICE_URL>/register \
  -H "Content-Type: application/json" \
  -d '{
    "client_name": "claude-web",
    "redirect_uris": ["https://claude.ai/api/mcp/auth_callback"],
    "grant_types": ["authorization_code", "refresh_token"],
    "response_types": ["code"],
    "token_endpoint_auth_method": "client_secret_post"
  }'
```

返ってきた `client_id` / `client_secret` をクライアント側の MCP 接続設定に入力する。GCP Console 側では Authorized redirect URI に `{SERVICE_URL}/auth/callback` を必ず登録すること。

**永続化の注意**: FastMCP は登録済みクライアント情報をファイルシステム (`~/.local/share/fastmcp/oauth-proxy/`) に保存する。Cloud Run のようにディスクが揮発する環境では `FASTMCP_HOME` を永続ボリューム (GCS マウント等) に向けないと、再起動のたびに「Client Not Registered」エラーが出る。

完全なシーケンス図と各ステップの詳細は [infra/terraform/OAUTH_FLOW.md](infra/terraform/OAUTH_FLOW.md) を参照。

## 設定のカスタマイズ

YAML を編集するだけで挙動を変えられる。

| ファイル | 内容 |
|---------|------|
| [prompts/user_config.yaml](src/dynamic_prompt/prompts/user_config.yaml) | ユーザーの母語、復習までの待ち時間 (`memory_test_period_hours`) |
| [prompts/app_config.yaml](src/dynamic_prompt/prompts/app_config.yaml) | 一度に取得する単語数、クイズサーバーのポート |
| [prompts/instructions.yaml](src/dynamic_prompt/prompts/instructions.yaml) | AI に渡す指示テンプレート (`{variable}` プレースホルダ対応) |
| [prompts/languages/](src/dynamic_prompt/prompts/languages/) | 言語ごとの教え方プロファイル。新しい言語は `<code>.yaml` を追加 |

YAML を編集したら整合性チェックを走らせる。

```bash
uv run mcps/dynamic_prompt/src/dynamic_prompt/validate.py
```

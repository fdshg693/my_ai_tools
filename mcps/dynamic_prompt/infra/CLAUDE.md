# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Scope

This file covers `mcps/dynamic_prompt/infra/` — Docker, Cloud Build, Terraform による GCP Cloud Run デプロイ基盤。

## Commands

すべてのコマンドは `mcps/dynamic_prompt/infra/` ディレクトリの `justfile` から実行できる ([just](https://github.com/casey/just) が必要)。

```bash
cd mcps/dynamic_prompt/infra

just                # レシピ一覧表示 (default レシピ)

# Docker
just build          # Docker イメージをビルド
just run            # コンテナ起動 (http モード, localhost:8080)
just stop           # コンテナ停止・削除
just health         # ローカルヘルスチェック
just logs           # コンテナログ表示

# GCP Cloud Build
just cloud-build    # Cloud Build でイメージビルド & Artifact Registry にプッシュ

# Terraform
just tf-init        # terraform init
just tf-plan        # terraform plan (差分プレビュー)
just tf-apply       # terraform apply (インフラデプロイ)
just tf-output      # terraform output (URL 確認)
just tf-destroy     # terraform destroy (要確認)

# GCP 情報・動作確認
just cloud-info     # Cloud Run サービス詳細 (gcloud: リビジョン, イメージ, ステータス)
just cloud-health   # Cloud Run ヘルスチェック (認証不要)

# 一括
just deploy         # cloud-build → tf-apply の一括実行
```

Windows では文字化け対策として `justfile` 内で Git Bash (`C:/Program Files/Git/usr/bin/bash.exe`) を使用するよう `set windows-shell` で指定している。

## Architecture

### ディレクトリ構成

| Path | Description |
|------|-------------|
| `Dockerfile` | Python 3.13-slim + uv。ビルドコンテキストはリポジトリルート |
| `cloudbuild.yaml` | Cloud Build 定義。`_IMAGE` 置換変数でレジストリパスを指定 |
| `terraform/` | GCP インフラ一式 (Cloud Run, Artifact Registry, GCS, IAM) |

### Dockerfile のポイント

- ビルドコンテキスト: リポジトリルート (`fastmcp_mcps/`)。`-f` でこの Dockerfile を指定する
- 依存インストールとコードコピーを分離してキャッシュ効率化
- デフォルト環境変数: `TRANSPORT=http`, `HOST=0.0.0.0`, `PORT=8080`, `DB_PATH=/data/vocab.db`
- YAML 設定の取得先 (Cloud Run): `PROMPTS_URI=gs://${project_id}-dp-data/prompts`, TTL `CONFIG_TTL_SECONDS=60`。YAML は `just upload-prompts` で GCS に同期し、変更を即時反映するには MCP ツール `reload_config` を呼ぶ

### Terraform 構成

| File | Content |
|------|---------|
| `main.tf` | Provider, GCP API 有効化 |
| `variables.tf` | `project_id`, `region`, `image_tag`, `google_client_id`, `google_client_secret`, `service_url`, `allowed_emails` |
| `terraform.tfvars` | 変数の実値 |
| `registry.tf` | Artifact Registry (Docker) |
| `storage.tf` | GCS バケット (`prevent_destroy`) — SQLite 永続化用 |
| `cloud_run.tf` | Cloud Run v2 (`max_instance_count = 1`, GCS volume mount) |
| `iam.tf` | Cloud Run 未認証アクセス許可 (`allUsers` → `roles/run.invoker`) |
| `outputs.tf` | `service_url`, `mcp_endpoint`, `image_repo` |

### GCP 環境情報

- **Project**: `dynamic-prompt-mcp`
- **Region**: `asia-northeast1`
- **Cloud Run**: single instance (SQLite 単一書き込み制約)
- **永続化**: GCS バケットを `/data` にマウントして SQLite を保存
- **MCP endpoint**: `{service_url}/mcp`
- **Health check**: `GET /health`

### 認証方式

- **方式**: FastMCP `GoogleProvider` (OAuth 2.1) — アプリケーションレベルの認証
- **保護対象**: `/mcp` エンドポイントのみ。`/health` やクイズ UI は認証不要
- **Cloud Run IAM**: `allUsers` に `roles/run.invoker` を付与（未認証アクセス許可）
- **環境変数**: `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `SERVICE_URL`, `ALLOWED_EMAILS` を Cloud Run コンテナに設定
- **ユーザー絞り込み**: `ALLOWED_EMAILS` (terraform var: `allowed_emails`) にカンマ区切りで許可メールを指定。未指定なら全 Google アカウント許可
- **OAuth 同意画面・クレデンシャル**: GCP Console → API & Services で事前に作成が必要
  - Authorized redirect URI: `{SERVICE_URL}/auth/callback`

### 注意事項

- `terraform.tfvars` と `terraform.tfstate*` は `.gitignore` 対象にすること
- Cloud Run は `max_instance_count = 1` — SQLite の同時書き込みを防ぐため変更不可
- GCS バケットは `prevent_destroy` — `terraform destroy` では削除されない

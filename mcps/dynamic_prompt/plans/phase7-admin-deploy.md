# Phase 7: 管理WebのCloud Runデプロイ

## 目的

Phase 6 でローカル動作確認した Next.js 管理WebをCloud Runに別サービスとしてデプロイし、本番運用可能な状態にする。

## 前提

- Phase 5 が完了（MCPサービスがFirestoreで稼働中）
- Phase 6 が完了（admin-web がローカルで動作）
- GCP コンソールで管理ページ用の OAuth クライアント発行済み

## 完了基準

- Cloud Run service `dynamic-prompt-admin` がデプロイ済み
- 管理用 OAuth クライアントの Authorized redirect URIs に本番URLが追加されている
- 本番URLでサインイン → ダッシュボード/configs/vocabulary 全画面動作
- 許可リスト外メールは AccessDenied
- YAML編集→保存→MCPの reload-config 連携が本番で動く

## ステップ

### 7.1 Dockerfile

`mcps/dynamic_prompt/admin-web/Dockerfile`:
```dockerfile
# syntax=docker/dockerfile:1
FROM node:22-alpine AS deps
WORKDIR /app
COPY mcps/dynamic_prompt/admin-web/package.json mcps/dynamic_prompt/admin-web/package-lock.json* ./
RUN npm ci

FROM node:22-alpine AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY mcps/dynamic_prompt/admin-web/ ./
ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build

FROM node:22-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production
ENV PORT=8080
ENV HOSTNAME=0.0.0.0
ENV NEXT_TELEMETRY_DISABLED=1

RUN addgroup --system --gid 1001 nodejs && adduser --system --uid 1001 nextjs
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static
COPY --from=builder --chown=nextjs:nodejs /app/public ./public

USER nextjs
EXPOSE 8080
CMD ["node", "server.js"]
```

`admin-web/next.config.ts` に `output: "standalone"` を設定:
```ts
const config: NextConfig = {
  output: "standalone",
  reactStrictMode: true,
};
export default config;
```

### 7.2 Cloud Build設定

`infra/cloudbuild-admin-web.yaml`:
```yaml
steps:
  - name: gcr.io/cloud-builders/docker
    args:
      - build
      - -f
      - mcps/dynamic_prompt/admin-web/Dockerfile
      - -t
      - ${_IMAGE}
      - .
  - name: gcr.io/cloud-builders/docker
    args: [push, '${_IMAGE}']
images:
  - ${_IMAGE}
substitutions:
  _IMAGE: asia-northeast1-docker.pkg.dev/dynamic-prompt-mcp/dynamic-prompt/admin:latest
options:
  logging: CLOUD_LOGGING_ONLY
```

### 7.3 Terraform: 管理Web Cloud Run

`infra/terraform/cloud_run_admin.tf`:
```hcl
resource "google_service_account" "admin" {
  account_id   = "dynamic-prompt-admin"
  display_name = "Dynamic Prompt Admin Web"
}

resource "google_cloud_run_v2_service" "admin" {
  name     = "dynamic-prompt-admin"
  location = var.region
  project  = var.project_id

  template {
    service_account = google_service_account.admin.email
    scaling {
      max_instance_count = 5
    }
    containers {
      image = var.admin_image
      ports { container_port = 8080 }
      resources {
        limits = { cpu = "1", memory = "512Mi" }
      }
      env { name = "NODE_ENV"               value = "production" }
      env { name = "NEXTAUTH_URL"           value = var.admin_service_url }
      env { name = "NEXTAUTH_SECRET"        value = var.nextauth_secret }
      env { name = "GOOGLE_CLIENT_ID"       value = var.admin_google_client_id }
      env { name = "GOOGLE_CLIENT_SECRET"   value = var.admin_google_client_secret }
      env { name = "ALLOWED_EMAILS"         value = var.allowed_emails }
      env { name = "MCP_SERVICE_URL"        value = google_cloud_run_v2_service.app.uri }
      env { name = "MCP_ADMIN_TOKEN"        value = var.mcp_admin_token }
      env { name = "GOOGLE_CLOUD_PROJECT"   value = var.project_id }
      env { name = "PROMPTS_GCS_BUCKET"     value = "${var.project_id}-dp-data" }
      env { name = "PROMPTS_GCS_PREFIX"     value = "prompts" }
    }
  }
}
```

`infra/terraform/iam_admin.tf`:
```hcl
resource "google_cloud_run_v2_service_iam_member" "admin_public" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.admin.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

resource "google_project_iam_member" "admin_firestore" {
  project = var.project_id
  role    = "roles/datastore.user"
  member  = "serviceAccount:${google_service_account.admin.email}"
}

resource "google_storage_bucket_iam_member" "admin_prompts_bucket" {
  bucket = "${var.project_id}-dp-data"   # 既存storage.tfで定義済みのバケット名に合わせる
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.admin.email}"
}
```

`infra/terraform/variables.tf` に追加:
```hcl
variable "admin_image" {
  type    = string
  default = "asia-northeast1-docker.pkg.dev/dynamic-prompt-mcp/dynamic-prompt/admin:latest"
}
variable "nextauth_secret" {
  type      = string
  sensitive = true
}
variable "admin_google_client_id" {
  type      = string
  sensitive = true
}
variable "admin_google_client_secret" {
  type      = string
  sensitive = true
}
variable "admin_service_url" {
  type        = string
  description = "Cloud Run URL for admin service (set after first apply)"
  default     = "https://placeholder-set-after-first-apply"
}
```

`infra/terraform/outputs.tf` に追加:
```hcl
output "admin_service_url" {
  value = google_cloud_run_v2_service.admin.uri
}
```

`infra/terraform/terraform.tfvars.example` に例を追記。

### 7.4 justfile レシピ追加

`infra/justfile` 末尾に追記:
```just
# Admin Web image variables
admin_image := "asia-northeast1-docker.pkg.dev/dynamic-prompt-mcp/dynamic-prompt/admin:latest"

# Cloud Build for admin-web
cloud-build-admin:
    gcloud builds submit \
        --config {{ infra_dir }}/cloudbuild-admin-web.yaml \
        --substitutions=_IMAGE={{ admin_image }} \
        --project=dynamic-prompt-mcp \
        {{ repo_root }}

deploy-admin: cloud-build-admin tf-apply

cloud-admin-url:
    terraform -chdir={{ tf_dir }} output -raw admin_service_url

cloud-admin-health:
    @url=$(just cloud-admin-url); \
    curl -fsS "$url/api/health" && echo "OK"
```

（`{{ repo_root }}`, `{{ infra_dir }}`, `{{ tf_dir }}` などの変数名は既存justfileの命名に合わせる）

### 7.5 初回デプロイ手順（2段階apply）

```powershell
cd c:\CodeRoot\my_ai_tools\mcps\dynamic_prompt\infra

# 1. tfvars に新規変数を設定（admin_service_url は placeholder のまま）
# infra/terraform/terraform.tfvars を編集:
#   mcp_admin_token            = "..."
#   nextauth_secret            = "..."
#   admin_google_client_id     = "..."
#   admin_google_client_secret = "..."

# 2. Cloud Build でイメージpush
just cloud-build-admin

# 3. 初回 terraform apply (admin_service_url は placeholder で起動)
just tf-apply

# 4. 実際の URL を取得
$ADMIN_URL = just cloud-admin-url
echo $ADMIN_URL
# 例: https://dynamic-prompt-admin-abc123-an.a.run.app

# 5. terraform.tfvars を更新
# admin_service_url = "<上で取得したURL>"

# 6. 再度 tf-apply して NEXTAUTH_URL を正しい値に
just tf-apply
```

### 7.6 OAuth redirect URI 追加

GCPコンソール > APIs & Services > Credentials > 管理用OAuthクライアント編集:
- Authorized redirect URIs に追加: `https://<admin-service-url>/api/auth/callback/google`

### 7.7 本番スモークテスト

```powershell
$ADMIN_URL = just cloud-admin-url
Start-Process $ADMIN_URL
```

ブラウザで:
1. `/login` → "Sign in with Google" → 許可リスト内アカウントで認証
2. `/dashboard` カード表示
3. `/configs/user_config.yaml` 編集 → 保存 → 200確認
4. MCPサービスの `config_store` が新値を返すこと（MCPツール呼び出しで確認）
5. `/vocabulary` で実データ表示 → 1件編集 → リロード後保持
6. サインアウト → `/login` に戻る
7. 許可外メールでサインインを試行 → AccessDenied

### 7.8 監視・ロギング

```powershell
gcloud run services logs read dynamic-prompt-admin --limit=50 --project=dynamic-prompt-mcp
```

エラーが出ていないことを確認。必要に応じてアラートポリシー追加（個人利用なら後回し可）。

## ロールバック

- 問題発生時: `gcloud run services delete dynamic-prompt-admin --region=asia-northeast1` で削除
- または terraform で該当リソースだけ destroy
- 既存MCPサービスへの影響なし

## フォローアップ（v2候補）

- GCS楽観ロック（etag/generationベース）でYAML編集の競合検出
- 監査ログ専用Firestoreコレクション（`admin_audit/{auto_id}`）
- ダッシュボードのチャート化（grafana-likeな時系列）
- 言語追加UI（`languages/<code>.yaml` 新規作成）
- CIでLint/Build/型チェック自動化

# Phase 4: インフラ更新 — Firestore + IAM + 環境変数

## 目的

GCP上にFirestoreデータベースとインデックスをプロビジョニングし、既存MCPサービスのCloud Runランタイムを「Firestoreモード」に切り替える準備を整える。`MCP_ADMIN_TOKEN` などの新規環境変数もTerraformで管理。

このフェーズでは**コードはまだFirestoreモードで本番起動しない**（=Phase 5でデータ移行してから切替）。

## 前提

- Phase 2 と Phase 3 が完了している（コードはFirestore起動可能だがデフォルトはまだSQLite）
- `infra/` でterraformが既に動いている

## 完了基準

- `terraform plan` がエラーなく通る
- `terraform apply` でFirestore DB（asia-northeast1, Native mode）と複合インデックスがプロビジョン済み
- 新規変数 `mcp_admin_token` が Cloud Run の env にセットされている
- MCP Cloud Run のランタイムSAに `roles/datastore.user` が付与されている
- 既存MCPサービスは挙動変わらず（`DATA_BACKEND` env はまだ未セット、または `sqlite`）

## ステップ

### 4.1 Firestore初期化

GCPプロジェクト `dynamic-prompt-mcp` にFirestore Native modeを `asia-northeast1` でプロビジョン。

選択肢 A（推奨・Terraform管理）:

`infra/terraform/firestore.tf` 新規:
```hcl
resource "google_firestore_database" "default" {
  project     = var.project_id
  name        = "(default)"
  location_id = var.region   # "asia-northeast1"
  type        = "FIRESTORE_NATIVE"

  # データ保護
  delete_protection_state = "DELETE_PROTECTION_ENABLED"
}
```

選択肢 B（手動）:
```powershell
gcloud firestore databases create --location=asia-northeast1 --project=dynamic-prompt-mcp
```
※ Firestoreは**プロジェクト全体で1度しか作成できない**ため、既に作成済みなら `terraform import google_firestore_database.default projects/dynamic-prompt-mcp/databases/(default)` する。

### 4.2 複合インデックス

`infra/terraform/firestore_indexes.tf` 新規:
```hcl
resource "google_firestore_index" "unknown_words_review" {
  project    = var.project_id
  database   = "(default)"
  collection = "unknown_words"
  fields {
    field_path = "lang"
    order      = "ASCENDING"
  }
  fields {
    field_path = "status"
    order      = "ASCENDING"
  }
  fields {
    field_path = "reviewed_at"
    order      = "ASCENDING"
  }
  depends_on = [google_firestore_database.default]
}

resource "google_firestore_index" "unknown_words_admin" {
  collection = "unknown_words"
  fields {
    field_path = "lang"
    order      = "ASCENDING"
  }
  fields {
    field_path = "created_at"
    order      = "DESCENDING"
  }
  # 残りはabove同様
}

resource "google_firestore_index" "quiz_sessions_history" {
  collection = "quiz_sessions"
  fields {
    field_path = "lang"
    order      = "ASCENDING"
  }
  fields {
    field_path = "created_at"
    order      = "DESCENDING"
  }
}

resource "google_firestore_index" "quiz_sessions_unscored" {
  collection = "quiz_sessions"
  fields {
    field_path = "submitted_at"
    order      = "ASCENDING"
  }
  fields {
    field_path = "scored_at"
    order      = "ASCENDING"
  }
}

resource "google_firestore_index" "story_topics_recent" {
  collection = "story_topics"
  fields {
    field_path = "lang"
    order      = "ASCENDING"
  }
  fields {
    field_path = "created_at"
    order      = "DESCENDING"
  }
}
```

実装時に Phase 2 の Firestore実装で実際に必要になったクエリだけを残し、不要なインデックスは削除。

### 4.3 variables.tf 拡張

`infra/terraform/variables.tf` に追加:
```hcl
variable "mcp_admin_token" {
  description = "Bearer token for /admin/api/* endpoints"
  type        = string
  sensitive   = true
}
```

`infra/terraform/terraform.tfvars.example` に例を追記:
```
mcp_admin_token = "generate-strong-random-32-chars"
```

### 4.4 cloud_run.tf 修正（既存MCP）

[infra/terraform/cloud_run.tf](../infra/terraform/cloud_run.tf) の env ブロックに追加:
```hcl
env {
  name  = "MCP_ADMIN_TOKEN"
  value = var.mcp_admin_token
}
env {
  name  = "GOOGLE_CLOUD_PROJECT"
  value = var.project_id
}
# DATA_BACKEND はまだ追加しない（Phase 5でsqlite→firestore切替時に追加）
```

`max_instance_count = 1` は維持。`/data` ボリュームマウントも維持（FASTMCP_HOME用）。

### 4.5 IAM拡張

`infra/terraform/iam.tf` に追記:
```hcl
resource "google_project_iam_member" "mcp_firestore_user" {
  project = var.project_id
  role    = "roles/datastore.user"
  member  = "serviceAccount:${google_service_account.mcp.email}"
}
```

（既存のサービスアカウント名 `google_service_account.mcp` は実際の名前に合わせる）

### 4.6 apply実行

```powershell
cd c:\CodeRoot\my_ai_tools\mcps\dynamic_prompt\infra
just tf-plan
# 期待される変更:
#   + google_firestore_database.default
#   + google_firestore_index.* (複数)
#   + google_project_iam_member.mcp_firestore_user
#   ~ google_cloud_run_v2_service.app (env追加)
just tf-apply
```

### 4.7 動作確認

- `gcloud firestore databases describe --database='(default)' --project=dynamic-prompt-mcp` でDB存在確認
- Cloud Console > Firestore > インデックス で複合インデックスのビルド完了確認（数分かかる）
- Cloud Run > MCPサービス > 環境変数 で `MCP_ADMIN_TOKEN` 設定確認
- 既存MCPサービスがまだSQLiteで動いていることを確認（`/health` 200、MCPツール正常動作）

スモークテスト:
```powershell
$URL = just cloud-url
curl -i "$URL/health"
# → 200

curl -i -H "Authorization: Bearer $env:MCP_ADMIN_TOKEN" "$URL/admin/api/health"
# → 200
```

## ロールバック

- `terraform destroy -target=google_firestore_database.default` は **delete_protection で守られているため可逆性が低い**。一度作成したらFirestore自体はそのまま残しておく方針が安全。
- 必要なら env `MCP_ADMIN_TOKEN` だけ取り除いて再apply。
- IAMバインディングは独立して removeable。

## 注意

- Firestoreインデックスのビルドは非同期で数分かかる。Phase 5の本番切替前に必ずビルド完了を確認すること
- `mcp_admin_token` は強い乱数で生成（`openssl rand -hex 32` 等）し、Secret Managerで管理することも検討

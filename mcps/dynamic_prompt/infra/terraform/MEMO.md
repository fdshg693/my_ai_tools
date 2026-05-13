# FastMCP GoogleProvider OAuth 導入メモ

Cloud Run + FastMCP GoogleProvider で OAuth 2.1 認証を導入する際の躓きポイントと確認事項。

## 1. Cloud Build のビルドコンテキスト

- `REPO_ROOT` が Git リポジトリルートを指す場合、Dockerfile の `COPY mcps/...` パスと合わない
- **確認**: `cloudbuild.yaml` の `-f` パスと Dockerfile 内の `COPY` パスが、ビルドコンテキストからの相対パスとして整合しているか
- **対処**: Makefile の `REPO_ROOT` を Dockerfile が期待するルートに合わせる

## 2. Cloud Run の OAuth ストレージ永続化

- FastMCP はクライアント登録データをローカルファイルシステム (`~/.local/share/fastmcp/oauth-proxy/`) にデフォルト保存する
- Cloud Run はインスタンス再起動でファイルが消えるため、登録済みクライアントが "Client Not Registered" になる
- **確認**: `FASTMCP_HOME` 環境変数が永続ボリューム (GCS マウント等) 上のパスを指しているか
- **対処**: `FASTMCP_HOME=/data/.fastmcp` を Cloud Run の環境変数に設定し、GCS マウント上に永続化する

## 3. Claude.ai からの接続には手動 DCR が必要

- Claude.ai は Dynamic Client Registration (DCR) を自動で行わず、`client_id` の入力が必須
- Google OAuth Client ID を入力しても動作しない (FastMCP の DCR client_id とは別物)
- **確認**: `/register` エンドポイントに POST して取得した UUID 形式の `client_id` と `client_secret` を使っているか
- **対処**: 以下で手動登録し、返された `client_id` / `client_secret` を Claude.ai に入力する
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

## 4. Google OAuth の redirect_uri_mismatch

- FastMCP は `{base_url}/auth/callback` を Google へのリダイレクト URI として使う
- GCP Console の OAuth クライアント設定と完全一致が必要 (大文字小文字、末尾スラッシュ含む)
- **確認**: GCP Console → API & Services → Credentials → OAuth 2.0 Client ID → Authorized redirect URIs に `https://<SERVICE_URL>/auth/callback` が登録されているか
- **対処**: 一文字でもずれていたら修正する。よくある間違い:
  - 末尾に `/` がある/ない
  - `http` vs `https`
  - パスが `/callback` になっている (`/auth/callback` が正しい)

## 5. Terraform の循環参照

- `cloud_run.tf` の環境変数に `google_cloud_run_v2_service.app.uri` を使うと自己参照で循環エラーになる
- **対処**: `service_url` を別変数として `terraform.tfvars` で直接指定する

## 6. IAM の切り替え

- OAuth 導入後は Cloud Run の IAM を `allUsers` → `roles/run.invoker` にして未認証アクセスを許可する
- **確認**: `terraform plan` で旧 `invoker_members` リソースが削除され、新 `allUsers` リソースが作成されること
- **注意**: 旧リソース名 (`google_cloud_run_v2_service_iam_member.invokers`) と新リソース名 (`...public`) が異なるため、`terraform state` に旧リソースが残っていないか確認する

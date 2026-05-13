# Claude Web (claude.ai) での OAuth 2.1 フロー

FastMCP `GoogleProvider` + Cloud Run 構成における、Claude Web から MCP サーバーへの接続時の OAuth フロー。

## 全体像

```
Claude.ai  ──(外側OAuth)──>  FastMCP (Cloud Run)  ──(内側OAuth)──>  Google
```

OAuth が 2 層ある点がこのアーキテクチャの特徴。

| 層 | 誰 → 誰 | Client ID | 目的 |
|---|---------|-----------|------|
| **外側** | Claude.ai → FastMCP | 手動 DCR で取得した UUID | MCP エンドポイントへのアクセス制御 |
| **内側** | FastMCP → Google | GCP Console の OAuth Client ID | ユーザーの身元確認 (Google ログイン) |

---

## ステップ 0: 手動クライアント登録 (DCR)

Claude.ai は Dynamic Client Registration を**自動で行わない**ため、事前に手動登録が必要。

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

FastMCP が UUID 形式の `client_id` と `client_secret` を返す。これを Claude.ai の MCP 接続設定画面に入力する。

> **注意**: ここで返る `client_id` は Google OAuth の Client ID とは全くの別物。FastMCP が内部管理する OAuth クライアント ID。

---

## ステップ 1: Claude.ai → FastMCP — 認可リクエスト

Claude.ai がユーザーの代わりに認可フローを開始する。

```
GET https://<SERVICE_URL>/authorize
  ?response_type=code
  &client_id=<手動登録で取得した UUID>
  &redirect_uri=https://claude.ai/api/mcp/auth_callback
  &scope=openid email profile
  &state=<ランダム文字列>
  &code_challenge=<PKCE チャレンジ>
  &code_challenge_method=S256
```

---

## ステップ 2: FastMCP → Google — Google OAuth リダイレクト

FastMCP の `GoogleProvider` が Google の認可エンドポイントにリダイレクトする。

```
302 → https://accounts.google.com/o/oauth2/v2/auth
  ?response_type=code
  &client_id=<GOOGLE_CLIENT_ID>
  &redirect_uri=https://<SERVICE_URL>/auth/callback
  &scope=openid email profile
  &state=<FastMCP 内部ステート>
```

`GOOGLE_CLIENT_ID` は `main.py` で `GoogleProvider` に渡された GCP Console の OAuth Client ID。

---

## ステップ 3: ユーザー → Google — ログイン・同意

ブラウザに Google のログイン画面が表示される。ユーザーがアクセスを許可する。

---

## ステップ 4: Google → FastMCP — 認可コード返却

Google が FastMCP のコールバックに認可コードを返す。

```
302 → https://<SERVICE_URL>/auth/callback
  ?code=<Google 認可コード>
  &state=<FastMCP 内部ステート>
```

> **注意**: このリダイレクト URI は GCP Console の「Authorized redirect URIs」と完全一致が必要。MEMO.md §4 を参照。

---

## ステップ 5: FastMCP → Google — トークン交換 (バックチャネル)

FastMCP がサーバー間通信で Google にトークンを要求する。

```
POST https://oauth2.googleapis.com/token

  grant_type=authorization_code
  &code=<Google 認可コード>
  &redirect_uri=https://<SERVICE_URL>/auth/callback
  &client_id=<GOOGLE_CLIENT_ID>
  &client_secret=<GOOGLE_CLIENT_SECRET>
```

Google が `id_token` + `access_token` を返す。FastMCP はこれでユーザーを認証する。

---

## ステップ 6: FastMCP → Claude.ai — 認可コード返却

FastMCP は Google 認証成功を確認した後、**FastMCP 自身の認可コード**を生成し、Claude.ai のコールバックにリダイレクトする。

```
302 → https://claude.ai/api/mcp/auth_callback
  ?code=<FastMCP の認可コード>
  &state=<ステップ 1 の state>
```

---

## ステップ 7: Claude.ai → FastMCP — トークン交換

Claude.ai がバックチャネルで FastMCP にトークンを要求する。

```
POST https://<SERVICE_URL>/token

  grant_type=authorization_code
  &code=<FastMCP の認可コード>
  &redirect_uri=https://claude.ai/api/mcp/auth_callback
  &client_id=<手動登録 UUID>
  &client_secret=<手動登録で取得した secret>
  &code_verifier=<PKCE verifier>
```

FastMCP が `access_token` + `refresh_token` を返す。

---

## ステップ 8: Claude.ai → FastMCP — MCP 通信開始

以降、Claude.ai は Bearer トークンで `/mcp` にリクエストを送る。

```
POST https://<SERVICE_URL>/mcp
  Authorization: Bearer <access_token>

  {"method": "tools/list", ...}
```

---

## シーケンス図

```
 Claude.ai              FastMCP (Cloud Run)         Google OAuth           ブラウザ
    │                         │                         │                    │
    │  ── GET /authorize ──>  │                         │                    │
    │                         │  ── 302 accounts.google ──────────────────>  │
    │                         │                         │  <── ログイン ──   │
    │                         │                         │  ── 許可 ──>       │
    │                         │  <── /auth/callback ──  │                    │
    │                         │  ── POST /token ──────> │                    │
    │                         │  <── id_token ────────  │                    │
    │  <── /auth_callback ──  │                         │                    │
    │  ── POST /token ──────> │                         │                    │
    │  <── access_token ────  │                         │                    │
    │                         │                         │                    │
    │  ── POST /mcp ────────> │  (Bearer token)         │                    │
    │  <── MCP response ────  │                         │                    │
```

---

## 永続化に関する注意

FastMCP はクライアント登録データをファイルシステム (`~/.local/share/fastmcp/oauth-proxy/`) に保存する。Cloud Run はインスタンス再起動でファイルが消えるため、`FASTMCP_HOME=/data/.fastmcp` を GCS マウント上に設定して永続化する必要がある。未設定だと再起動のたびに「Client Not Registered」エラーが発生する。詳細は MEMO.md §2 を参照。

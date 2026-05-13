# Phase 6: Next.js管理Web実装（ローカル動作確認まで）

## 目的

`mcps/dynamic_prompt/admin-web/` にNext.js 15プロジェクトを作成し、Google認証付きで以下が動くようにする:
- `/dashboard`: Firestore統計表示
- `/configs`: GCS上のYAML一覧 + Monacoエディタで編集 + 保存
- `/vocabulary`: Firestoreの語彙CRUD

ローカル（Firestoreエミュレータ + localhost MCP）で全シナリオ動作確認するところまで。デプロイはPhase 7。

## 前提

- Phase 2（Firestore実装）と Phase 3（reload-config API）が完了
- Node.js 22+ がインストールされている
- ローカルでGoogle OAuthのテスト用クライアントが利用可能（開発用redirect URI登録済み）

## 完了基準

- `npm run dev` で `http://localhost:3000` 起動
- Googleサインイン（許可リスト内メール）でダッシュボード遷移
- 許可リスト外メールは AccessDenied 表示
- `/configs/user_config.yaml` を編集 → 保存 → MCPの `config_store.reload()` が呼ばれ即時反映
- `/vocabulary` で語彙のフィルタ、編集、削除が可能
- ローカルテストで一通りのCRUDがエミュレータFirestoreに反映される

## ステップ

### 6.1 プロジェクト初期化

```powershell
cd c:\CodeRoot\my_ai_tools\mcps\dynamic_prompt
npx create-next-app@latest admin-web --typescript --tailwind --app --no-src-dir
# 質問:
#   ESLint: Yes
#   src/ directory: Yes (上書き)
#   import alias: 既定の @/*
```

`admin-web/` に作成された雛形を整理し、`src/` 以下にAppRouter構成で配置。

依存追加:
```powershell
cd admin-web
npm install next-auth@beta @monaco-editor/react js-yaml zod firebase-admin @google-cloud/storage
npm install -D @types/js-yaml
```

### 6.2 環境変数定義

`admin-web/.env.example`:
```
NEXTAUTH_URL=http://localhost:3000
NEXTAUTH_SECRET=
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
ALLOWED_EMAILS=
MCP_SERVICE_URL=http://localhost:8080
MCP_ADMIN_TOKEN=dev
GOOGLE_CLOUD_PROJECT=dynamic-prompt-mcp
PROMPTS_GCS_BUCKET=dynamic-prompt-mcp-dp-data
PROMPTS_GCS_PREFIX=prompts
# ローカル開発時:
# FIRESTORE_EMULATOR_HOST=127.0.0.1:8085
```

`admin-web/src/env.ts` でzodで検証:
```ts
import { z } from "zod";

const schema = z.object({
  NEXTAUTH_SECRET: z.string().min(16),
  GOOGLE_CLIENT_ID: z.string(),
  GOOGLE_CLIENT_SECRET: z.string(),
  ALLOWED_EMAILS: z.string(),
  MCP_SERVICE_URL: z.string().url(),
  MCP_ADMIN_TOKEN: z.string().min(1),
  GOOGLE_CLOUD_PROJECT: z.string(),
  PROMPTS_GCS_BUCKET: z.string(),
  PROMPTS_GCS_PREFIX: z.string(),
  FIRESTORE_EMULATOR_HOST: z.string().optional(),
});
export const env = schema.parse(process.env);
```

### 6.3 許可リストヘルパ

`admin-web/src/lib/allowlist.ts`:
```ts
import { env } from "@/env";

const allowed = new Set(
  env.ALLOWED_EMAILS.split(",").map(e => e.trim().toLowerCase()).filter(Boolean),
);

export function isAllowed(email: string | null | undefined): boolean {
  if (!email) return false;
  if (allowed.size === 0) return false;  // MCPと違い、空なら全拒否
  return allowed.has(email.toLowerCase());
}
```

### 6.4 Auth.js v5 設定

`admin-web/src/auth.ts`:
```ts
import NextAuth from "next-auth";
import Google from "next-auth/providers/google";
import { isAllowed } from "@/lib/allowlist";
import { env } from "@/env";

export const { handlers, auth, signIn, signOut } = NextAuth({
  providers: [
    Google({
      clientId: env.GOOGLE_CLIENT_ID,
      clientSecret: env.GOOGLE_CLIENT_SECRET,
    }),
  ],
  session: { strategy: "jwt" },
  callbacks: {
    async signIn({ profile }) {
      const email = profile?.email?.toLowerCase();
      if (!isAllowed(email)) {
        console.warn("Rejecting sign-in: %s not in allowlist", email);
        return false;
      }
      return true;
    },
    async jwt({ token, profile }) {
      if (profile?.email) token.email = profile.email.toLowerCase();
      return token;
    },
    async session({ session, token }) {
      if (session.user && typeof token.email === "string") {
        session.user.email = token.email;
      }
      return session;
    },
  },
  pages: { signIn: "/login", error: "/login" },
});
```

`admin-web/src/app/api/auth/[...nextauth]/route.ts`:
```ts
import { handlers } from "@/auth";
export const { GET, POST } = handlers;
```

`admin-web/src/middleware.ts`:
```ts
export { auth as middleware } from "@/auth";
export const config = {
  matcher: ["/((?!login|api/auth|_next/static|_next/image|favicon).*)"],
};
```

### 6.5 Firestoreクライアント

`admin-web/src/lib/firestore.ts`:
```ts
import { initializeApp, getApps, cert, applicationDefault } from "firebase-admin/app";
import { getFirestore } from "firebase-admin/firestore";
import { env } from "@/env";

if (getApps().length === 0) {
  initializeApp({
    projectId: env.GOOGLE_CLOUD_PROJECT,
    credential: applicationDefault(),
  });
}

export const db = getFirestore();
```

エミュレータ利用時は `FIRESTORE_EMULATOR_HOST` 環境変数が自動で効く。

### 6.6 GCSクライアント

`admin-web/src/lib/gcs.ts`:
```ts
import { Storage } from "@google-cloud/storage";
import { env } from "@/env";

const storage = new Storage({ projectId: env.GOOGLE_CLOUD_PROJECT });
export const bucket = storage.bucket(env.PROMPTS_GCS_BUCKET);

export function configPath(rel: string): string {
  return `${env.PROMPTS_GCS_PREFIX}/${rel}`;
}
```

### 6.7 MCPクライアント

`admin-web/src/lib/mcp-client.ts`:
```ts
import { env } from "@/env";

export async function notifyReloadConfig(userEmail: string): Promise<void> {
  const r = await fetch(`${env.MCP_SERVICE_URL}/admin/api/reload-config`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${env.MCP_ADMIN_TOKEN}`,
      "X-User-Email": userEmail,
    },
  });
  if (!r.ok) {
    console.warn("reload-config returned %s", r.status);
  }
}
```

### 6.8 ページ実装

#### `/login` — `app/login/page.tsx`
- ログインフォーム（クライアントコンポーネント）
- `signIn("google")` 呼び出しボタン
- URLクエリ `?error=AccessDenied` のときトースト表示

#### `/(app)/layout.tsx`
- サーバコンポーネント
- `auth()` でsession取得 → なければ `redirect("/login")`
- サイドバー（dashboard/configs/vocabulary）+ サインアウトボタン

#### `/(app)/dashboard/page.tsx`
- サーバコンポーネント
- `db.collection("unknown_words").count().get()` 等で各statusの件数取得
- カードUI表示

#### `/(app)/configs/page.tsx`
- `bucket.getFiles({ prefix: env.PROMPTS_GCS_PREFIX })` でYAML一覧取得
- 各ファイルへのリンク（`/configs/[...path]`）

#### `/(app)/configs/[...path]/page.tsx`
- サーバコンポーネントでGCSから内容取得 → `<YamlEditor initialContent={...} path={...}>` (クライアントコンポーネント)
- `YamlEditor.tsx`: `@monaco-editor/react` でYAMLモード、保存ボタンで `fetch("/api/configs/<path>", {method: "PUT", body: ...})`

#### `/api/configs/[...path]/route.ts` (PUT)
```ts
import { NextRequest } from "next/server";
import yaml from "js-yaml";
import { auth } from "@/auth";
import { bucket, configPath } from "@/lib/gcs";
import { notifyReloadConfig } from "@/lib/mcp-client";

const ALLOWED_PREFIXES = ["user_config.yaml", "app_config.yaml", "instructions.yaml", "languages/"];

export async function PUT(req: NextRequest, { params }: { params: { path: string[] } }) {
  const session = await auth();
  if (!session?.user?.email) return Response.json({ error: "unauthorized" }, { status: 401 });

  const rel = params.path.join("/");
  if (!ALLOWED_PREFIXES.some(p => rel === p || rel.startsWith(p))) {
    return Response.json({ error: "forbidden path" }, { status: 400 });
  }
  if (rel.includes("..")) return Response.json({ error: "invalid path" }, { status: 400 });

  const { content } = await req.json();
  try {
    yaml.load(content);
  } catch (e: any) {
    return Response.json({ error: "yaml parse error", detail: e.message }, { status: 400 });
  }

  await bucket.file(configPath(rel)).save(content, { contentType: "application/yaml" });
  await notifyReloadConfig(session.user.email);
  return Response.json({ status: "saved" });
}
```

#### `/(app)/vocabulary/page.tsx`
- フィルタフォーム（lang/status/q）
- サーバコンポーネントで `db.collection("unknown_words").where(...).limit(50).get()`
- 各行に `<VocabTable />` (クライアント) でインライン編集ボタン
- 編集確定/削除は `/api/vocab/[id]/route.ts` 経由

#### `/api/vocab/[id]/route.ts` (PATCH, DELETE)
- `auth()` チェック
- `id` は `${lang}__${word}` 形式の自然キー
- PATCH: 許可フィールドのみ更新（`status`, `context`）
- DELETE: 単純削除

### 6.9 共通コンポーネント

- `YamlEditor.tsx`: Monaco editor wrapper、Ctrl+S で保存、エラー表示
- `VocabTable.tsx`: テーブル + 編集モーダル
- `Toast.tsx`: shadcn/ui の `sonner` でも、自前でもOK

### 6.10 ローカル動作確認

```powershell
# Terminal 1: Firestoreエミュレータ
gcloud beta emulators firestore start --host-port=127.0.0.1:8085

# Terminal 2: MCPサーバ (Phase 2の構成)
cd c:\CodeRoot\my_ai_tools\mcps\dynamic_prompt
$env:FIRESTORE_EMULATOR_HOST="127.0.0.1:8085"
$env:GOOGLE_CLOUD_PROJECT="dynamic-prompt-mcp"
$env:DATA_BACKEND="firestore"
$env:TRANSPORT="http"; $env:MCP_ADMIN_TOKEN="dev"; $env:PORT="8080"
uv run dynamic_prompt

# Terminal 3: Next.js
cd admin-web
copy .env.example .env.local
# .env.local を編集して GOOGLE_CLIENT_ID/SECRET, NEXTAUTH_SECRET, ALLOWED_EMAILS を入れる
$env:FIRESTORE_EMULATOR_HOST="127.0.0.1:8085"
npm run dev
```

確認手順:
1. `http://localhost:3000/login` → Googleサインイン
2. 許可外メールでサインイン → AccessDenied 表示
3. 許可済みメール → `/dashboard` 遷移、カードに件数表示
4. `/configs` → YAMLファイル一覧
5. `/configs/user_config.yaml` → Monacoで編集 → 保存 → MCPの reload-config が呼ばれる（MCPサーバログで確認）
6. 不正YAMLを保存 → 400エラー表示
7. `/vocabulary` → フィルタ・編集・削除一連動作

### 6.11 GCP OAuth設定（開発用）

新規OAuthクライアントID（管理ページ用）をGCPコンソールで発行:
1. APIs & Services > Credentials > "Create credentials" > "OAuth client ID"
2. Type: Web application
3. Authorized redirect URIs:
   - `http://localhost:3000/api/auth/callback/google`
4. Client ID / Secret を `.env.local` に設定

本番URIは Phase 7 で追加する。

## ロールバック

このフェーズはローカル作業のみ。本番影響なし。`admin-web/` フォルダごと削除すれば元通り。

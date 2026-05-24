# memo

タイトル・概要を持つメモを管理するシンプルな MCP サーバー。

- SQLite にメモ (タイトル + 概要 + 所有ユーザー) を保存する
- CRUD (作成・取得・一覧・更新・削除) を MCP ツールとして提供
- 検索はタイトルの**部分一致**で行う (大文字小文字を区別しない)。カンマ区切りで複数キーワードを OR 検索でき、各メモがどのキーワードに一致したかを返す
- **セマンティック検索**: 概要 (summary) の意味的な近さでメモを探す別ツールを提供。OpenAI の埋め込みを使い、クエリに最も近いメモを類似度の高い順に最大5件返す
- **ユーザーごとに完全分離**: メモには作成した接続ユーザーが所有者として記録され、他ユーザーは読み取りも含め一切操作できない
- **ユーザー登録制**: 接続ユーザーは `users` 台帳に登録されている必要があり、未登録の接続はすべてのツール呼び出しが拒否される
- **admin 特権**: ユーザー名が `admin` のときだけ、全ユーザー (所有者が空の孤立メモ含む) のメモを操作でき、ユーザー管理ツールで他ユーザーの登録・編集・削除ができる

## ユーザーの識別と登録

すべてのメモは「接続ユーザー」が所有する。ユーザーはトランスポートごとに異なる方法で渡す。

| トランスポート | 指定方法 | 例 |
|---------------|---------|----|
| stdio | 起動引数 `--user`（または環境変数 `MEMO_USER`）。プロセス全体でユーザーは1人に固定される | `uv run memo --user alice` |
| HTTP | MCP エンドポイントのクエリパラメータ `?user=` | `http://host:8080/mcp?user=alice` |

接続が許可されるのは `users` 台帳に**登録済みのユーザーのみ**。次のいずれかに当てはまる接続は、すべてのツール呼び出しがエラーで拒否される。

- ユーザーを識別できない (`--user` / `?user=` の指定が無い)
- 識別できても `users` 台帳に登録されていない

特権ユーザー `admin` は DB 初期化時に自動で登録される (ブートストラップ)。新しいユーザーは `admin` で接続して `create_user` ツールで登録する。

## admin 特権

ユーザー名が `admin` の接続だけが次のことを行える。

- **全ユーザーのメモを操作**: `get_memo` / `list_memos` / `search_memos` / `update_memo` / `delete_memo` が所有者を問わず全メモ (所有者が空の孤立メモ含む) を対象にする。
- **ユーザー管理**: `create_user` / `get_user` / `list_users` / `update_user` / `delete_user` でユーザー台帳を CRUD できる (admin 以外が呼ぶと `admin-only` エラー)。

`admin` 自身は削除できない。ユーザーを削除してもそのユーザーのメモは残り、以後は `admin` だけが操作できる (削除されたユーザーは未登録となり接続を拒否されるため)。

## 実行

```bash
# stdio トランスポート (Claude Desktop / VS Code はこの方式で接続する)
uv run memo --user alice

# HTTP トランスポート (デプロイ向け)。接続側は /mcp?user=NAME を指定する
TRANSPORT=http PORT=8080 uv run memo
```

DB ファイルの場所は環境変数 `MEMO_DB_PATH` で上書きできる (デフォルト: `src/memo/memo.db`)。

セマンティック検索 (`semantic_search_memos`) を使うには OpenAI の API キーを環境変数で渡す。`mcps/memo/.env` に書いておけば自動で読み込まれる (起動時に `mcps/memo/.env` をロードする。既に設定済みの環境変数が優先され、.env は上書きしない)。

```dotenv
# mcps/memo/.env
OPENAI_API_KEY=sk-...
# MEMO_EMBEDDING_MODEL=text-embedding-3-small   # 任意
```

| 環境変数 | 必須 | 説明 |
|---------|------|------|
| `OPENAI_API_KEY` | セマンティック検索を使う場合のみ | OpenAI 埋め込み API のキー。未設定時は `semantic_search_memos` がエラーを返す (他のツールには影響しない)。 |
| `MEMO_EMBEDDING_MODEL` | 任意 | 埋め込みモデル名。デフォルトは `text-embedding-3-small` (多言語対応)。 |

> `.env` は `.gitignore` 済みなので API キーはコミットされない。

## ツール一覧

### メモ管理

通常のユーザーは操作対象が「接続ユーザー自身のメモ」に限られる。他ユーザーのメモを ID 指定しても、存在を漏らさないため「not found」として扱われる。`admin` はすべてのメモを操作できる。

| ツール | 引数 | 説明 |
|--------|------|------|
| `create_memo` | `title`, `summary=""` | メモを新規作成する。`title` は必須。所有者は接続ユーザー (admin が作成すると所有者は admin)。成功時は作成した id を含む短いメッセージを返す。 |
| `get_memo` | `memo_id` | ID でメモを1件取得する。通常は自分のメモのみ、admin は所有者を問わない。 |
| `list_memos` | `limit=50` | メモを新しい順 (更新日時の降順) に一覧取得する。通常は自分のメモのみ、admin は全ユーザー。 |
| `search_memos` | `query`, `limit=50` | メモをタイトルの部分一致で検索する。`query` はカンマ区切りで複数キーワードを指定でき、いずれかに一致したメモを返す (OR 検索)。各メモに `matched_keywords` を付与する。通常は自分のメモのみ、admin は全ユーザー。 |
| `semantic_search_memos` | `query`, `limit=5` | メモを**概要 (summary) の意味的な近さ**で検索する (セマンティック検索)。`query` に意味的に近い概要のメモを類似度の高い順に返し、各メモに `similarity` (0〜1) を付与する。概要が空のメモは対象外。通常は自分のメモのみ、admin は全ユーザー。OpenAI API を使うため `OPENAI_API_KEY` が必要。 |
| `update_memo` | `memo_id`, `title=None`, `summary=None` | メモの指定したフィールドのみ更新する。通常は自分のメモのみ、admin は所有者を問わない。 |
| `delete_memo` | `memo_id` | メモを削除する。通常は自分のメモのみ、admin は所有者を問わない。 |

### ユーザー管理 (admin 専用)

いずれも接続ユーザーが `admin` でなければ `admin-only` エラーを返す。

| ツール | 引数 | 説明 |
|--------|------|------|
| `create_user` | `name`, `display_name=""`, `note=""` | ユーザーを新規登録する。`name` は必須・一意の識別子。既に存在すればその旨を返す。 |
| `get_user` | `name` | ユーザーを1件取得する。 |
| `list_users` | — | 登録済みユーザーを名前順に一覧取得する。 |
| `update_user` | `name`, `display_name=None`, `note=None` | ユーザーの属性 (表示名・メモ欄) を更新する。`name` (識別子) は変更できない。 |
| `delete_user` | `name` | ユーザーを台帳から削除する (メモは残す)。`admin` 自身は削除できない。 |

## データモデル

`memos` テーブル:

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER PK | Auto-increment |
| `user` | TEXT NOT NULL | 所有ユーザー名。全 CRUD・検索はこの値で絞り込む (admin は絞り込まない) |
| `title` | TEXT NOT NULL | タイトル |
| `summary` | TEXT NOT NULL DEFAULT '' | 概要 |
| `created_at` | TEXT NOT NULL | 作成日時 (`datetime('now')`) |
| `updated_at` | TEXT NOT NULL | 更新日時 (`datetime('now')`) |

`users` テーブル:

| Column | Type | Description |
|--------|------|-------------|
| `name` | TEXT PK | ユーザー名 (不変の識別子)。接続を許可する判定に使う |
| `display_name` | TEXT NOT NULL DEFAULT '' | 表示名 (admin が編集可) |
| `note` | TEXT NOT NULL DEFAULT '' | メモ・備考 (admin が編集可) |
| `created_at` | TEXT NOT NULL | 作成日時 |
| `updated_at` | TEXT NOT NULL | 更新日時 |

> 初期化時に `admin` ユーザーが自動でシードされる。既存 DB は起動時の `ALTER TABLE` で `user` カラムが追加される。`user` カラムが無かった時代の既存メモは `user=''` となり、通常ユーザーからはアクセスできないが、`admin` からは操作できる。

`memo_embeddings` テーブル (セマンティック検索の埋め込みキャッシュ):

| Column | Type | Description |
|--------|------|-------------|
| `memo_id` | INTEGER PK | 対象メモの id (1メモ1行) |
| `summary_hash` | TEXT NOT NULL | 埋め込み時の概要の SHA-256。概要が変わると不一致になり再計算される |
| `model` | TEXT NOT NULL | 埋め込みに使ったモデル名。モデルを変えると再計算される |
| `vector` | TEXT NOT NULL | 埋め込みベクトル (JSON 配列) |
| `created_at` | TEXT NOT NULL | 計算・保存日時 |

> 埋め込みは `semantic_search_memos` 実行時に**遅延計算**され、`summary_hash` と `model` が一致する間は再利用される (`create_memo`/`update_memo` では計算しない)。メモを削除してもキャッシュ行は残るが、検索候補は `memos` から取るため読まれず無害。

## テスト

```bash
# 単体テスト (DB の CRUD・検索・admin 特権・ユーザー台帳)
uv run --project mcps/memo pytest mcps/memo/src/memo/tests/ -v

# MCP クライアントでツール一覧を確認 (インプロセス接続)
uv run python -m memo.tests.test_mcp_client
```

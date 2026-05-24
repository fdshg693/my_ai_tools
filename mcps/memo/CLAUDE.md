# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Scope

This file covers `mcps/memo/` only — a FastMCP-based simple memo (title + summary) management MCP server. 検索はタイトル部分一致に加え、概要のセマンティック検索 (OpenAI 埋め込み) も持つ。

## Commands

```bash
# Run the MCP server (stdio transport — Claude Desktop / VS Code はこの方式で接続する)
# --user でこのプロセスの所有ユーザーを指定する (環境変数 MEMO_USER でも可)
uv run memo --user alice

# Run the MCP server (HTTP transport — デプロイ向け)。接続側は /mcp?user=NAME を指定する
TRANSPORT=http PORT=8080 uv run memo

# 単体テスト (DB の CRUD・検索・admin 特権・ユーザー台帳)
uv run --project mcps/memo pytest mcps/memo/src/memo/tests/ -v

# MCPクライアントでツール一覧を確認 (インプロセス接続)
uv run python -m memo.tests.test_mcp_client

# セマンティック検索を実環境で試す場合は OpenAI API キーが要る
OPENAI_API_KEY=sk-... uv run memo --user admin
```

## Architecture

The server exposes 12 MCP tools. **Memo tools (7):** `create_memo`, `get_memo`, `list_memos`, `search_memos`, `semantic_search_memos`, `update_memo`, `delete_memo`. **User management tools (5, admin-only):** `create_user`, `get_user`, `list_users`, `update_user`, `delete_user`.

### Module structure

ドメイン (memo / user) でファイルを分け、データアクセス (`repository`) ・認可 (`authz`) ・MCP インターフェース (`tools`) のレイヤーを分離している。

| Module | Responsibility |
|--------|---------------|
| `database.py` | 共有インフラのみ。SQLite connection factory (`_connect_db`)、`init_db()` (起動時スキーマ初期化 + `user` カラムの軽量マイグレーション + `users` / `memo_embeddings` テーブル作成 + `admin` シード)、定数 `ADMIN_USER = "admin"`。`DB_PATH` は環境変数 `MEMO_DB_PATH` で上書き可能。ドメインの CRUD は持たない |
| `repository/memo.py` | メモ (`memos`) の純粋なデータアクセス (`*_memo_db`)。get/list/search/update/delete は末尾に `is_admin` を取り、True のとき user 絞り込みを外して全メモ (孤立メモ含む) を対象にする。`_connect_db` を使うのみで認可は扱わない |
| `repository/user.py` | ユーザー台帳 (`users`) のデータアクセス (`*_user_db`) と登録判定 (`is_registered_user`)。`name` は不変の識別子、`display_name`/`note` が編集可能。ユーザー削除はメモを消さない |
| `repository/embedding.py` | 埋め込みキャッシュ (`memo_embeddings`) の純粋なデータアクセス。`get_cached_embedding` / `upsert_embedding` (UPSERT) / `delete_embedding`。vector は JSON 配列。ネットワーク・認可は扱わない |
| `embedding.py` | OpenAI 埋め込み API のラッパ (leaf)。`openai` を import し `OPENAI_API_KEY` を読むのはここだけ。`embed_text(text)`、定数 `MODEL` (`MEMO_EMBEDDING_MODEL` で上書き可)、例外 `EmbeddingError`。キーは呼び出し時に遅延取得。import 時に `python-dotenv` で `mcps/memo/.env` (`parents[2]/.env` 固定) を読み込む (既存の環境変数を優先・上書きしない) |
| `service.py` | セマンティック検索のオーケストレーション。`semantic_search(user, query, limit, is_admin)` がクエリ埋め込み → 候補取得 (`list_memos_db`) → 概要の埋め込みを get-or-compute (`_embedding_for_memo`) → コサイン類似度 (`_cosine`、純 Python) で降順ソート。**network を呼べる唯一のドメイン層** (repository はネットワーク禁止)。テストは `service.embed_text` を monkeypatch する |
| `auth.py` | 接続中ユーザーの**識別のみ**。`current_user()` が HTTP リクエストコンテキスト内ならクエリパラメータ `user` を、stdio なら起動時に `set_stdio_user()` で記録した値を返す。識別できなければ None |
| `authz.py` | **認可** (両ドメイン共通)。`resolve_caller()` が `current_user()` → 登録チェック (`is_registered_user`) を行い `(user, is_admin, error)` を返す。`error` があればツールはそれを返して中断。エラー定数 (`NO_USER_ERROR` / `ADMIN_ONLY_ERROR` / `not_registered_error`) もここ |
| `tools/__init__.py` | サブモジュール (`memo`, `user`) を読み込みツールを登録する side-effect import |
| `tools/memo.py` | メモ管理の 7 個の `@mcp.tool`。`resolve_caller()` で認可し、`is_admin` を `repository.memo` / `service` へ渡す。結果は JSON 文字列で返す。`semantic_search_memos` は `service.semantic_search` を呼び `EmbeddingError` を文言にして返す |
| `tools/user.py` | ユーザー管理の 5 個の `@mcp.tool` (admin 専用)。`resolve_caller()` の後 `is_admin` でなければ `ADMIN_ONLY_ERROR`。`delete_user` は `admin` 自身を拒否 |
| `main.py` | `mcp` FastMCP instance と entry point (`main()`)。`--user` 引数 (or `MEMO_USER`) を argparse で取り stdio 用に記録。`TRANSPORT` 環境変数で stdio / http を切り替え。`/health` ヘルスチェックを `@mcp.custom_route` で登録 |
| `tests/conftest.py` | pytest 共通設定。DB パスを一時ファイルに差し替え、各テスト前にテーブルを空にし `admin` を再シードする |
| `tests/test_memo_repository.py` | `repository.memo` の単体テスト (CRUD + 検索 + ユーザー分離 + admin 特権) |
| `tests/test_user_repository.py` | `repository.user` の単体テスト (ユーザー台帳 CRUD + 登録判定) |
| `tests/test_embedding_repository.py` | `repository.embedding` の単体テスト (キャッシュの get / upsert / 上書き / 削除) |
| `tests/test_semantic_search.py` | `service.semantic_search` の単体テスト。`service.embed_text` を monkeypatch して固定ベクトルにし、ランキング・キャッシュ命中・概要変更時の再計算・ユーザー分離・admin 横断を検証 (ネットワーク・API キー不要) |
| `tests/test_mcp_client.py` | MCP クライアント経由の結合テスト (ツール登録確認 + 認可 + admin 横断 + ユーザー管理 + セマンティック検索。`service.embed_text` を monkeypatch。pytest-asyncio に依存せず `asyncio.run()` で実行) |

`main.py` creates the `mcp` instance, then imports `memo.tools` via side-effect import; `tools/__init__.py` がサブモジュール (`tools.memo` / `tools.user`) を読み込み全ツールを登録する。`init_db()` はモジュールレベルで呼ばれるため、どの起動経路でも確実に DB 初期化される。

### レイヤーの依存方向

`tools/*` → `authz` → `repository/*` → `database` の一方向。`authz` は `auth` (識別) と `repository.user` (登録判定) を使う。`database` はどのドメイン層にも依存しない。新しいドメインを足すときは `repository/<domain>.py` と `tools/<domain>.py` を追加し、`tools/__init__.py` に読み込みを足す。

セマンティック検索はネットワーク (OpenAI 呼び出し) とランキングを伴うため、`repository` 層には置かず **`service` 層**を1段挟む: `tools/memo.py` → `service` → (`embedding` の OpenAI 呼び出し + `repository.embedding` / `repository.memo`)。`repository/*` は引き続き純 SQLite のみ・ネットワーク禁止という不変条件を保つ。

### Database

SQLite with WAL journaling (`memo.db`)。`init_db()` がサーバー起動時にスキーマ作成を行う (冪等)。ツール呼び出しごとにスレッド安全のため新しい接続を返す (`_connect_db`、`row_factory = sqlite3.Row`)。

**`memos` table:**

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER PK | Auto-increment |
| `user` | TEXT NOT NULL | 所有ユーザー名。`idx_memos_user` で索引付け |
| `title` | TEXT NOT NULL | タイトル |
| `summary` | TEXT NOT NULL DEFAULT '' | 概要 |
| `created_at` | TEXT NOT NULL | 作成日時 |
| `updated_at` | TEXT NOT NULL | 更新日時 (update 時に `datetime('now')` で更新) |

**`users` table:**

| Column | Type | Description |
|--------|------|-------------|
| `name` | TEXT PK | ユーザー名 (不変の識別子)。接続許可の判定に使う |
| `display_name` | TEXT NOT NULL DEFAULT '' | 表示名 (admin が編集可) |
| `note` | TEXT NOT NULL DEFAULT '' | メモ・備考 (admin が編集可) |
| `created_at` | TEXT NOT NULL | 作成日時 |
| `updated_at` | TEXT NOT NULL | 更新日時 |

**`memo_embeddings` table** (セマンティック検索の埋め込みキャッシュ):

| Column | Type | Description |
|--------|------|-------------|
| `memo_id` | INTEGER PK | 対象メモの id (1メモ1行)。FK は張らない (既存スキーマに倣う) |
| `summary_hash` | TEXT NOT NULL | 埋め込み時の概要の SHA-256。概要が変わると不一致 → 再計算 |
| `model` | TEXT NOT NULL | 埋め込みモデル名。モデルを変えると不一致 → 再計算 (次元不整合も防ぐ) |
| `vector` | TEXT NOT NULL | 埋め込みベクトル (JSON 配列) |
| `created_at` | TEXT NOT NULL | 計算・保存日時 |

### User isolation・登録制・admin 特権

メモは作成した接続ユーザーが所有する。通常 (`is_admin=False`) は全 `*_memo_db` ヘルパーが `WHERE user = ?` で絞り込むため、他ユーザーのメモは一覧・検索に出ず、`get`/`update`/`delete` で他人の ID を指定しても「対象なし」(None / False) となり、存在自体を漏らさない。

接続は `users` 台帳に登録されたユーザーのみ許可する。`_auth()` が未識別 (`current_user()` が None) と未登録 (`is_registered_user` が False) を両方拒否する。`admin` (`ADMIN_USER`) は `init_db()` で `INSERT OR IGNORE` により必ずシードされる固定ユーザーで、削除できない (`delete_user` がガード)。

`admin` 接続のときだけメモツールが `is_admin=True` で呼ばれ、user 絞り込みを外して全ユーザー (`user=''` の孤立メモ含む) を操作する。ユーザー管理ツール (`*_user`) は `is_admin` でなければ `admin-only` エラー。ユーザーを削除してもメモは残す (削除されたユーザーは未登録となり接続を拒否されるため、残ったメモは admin のみ操作可)。

`init_db()` は `user` カラムが無い既存 DB を `ALTER TABLE ADD COLUMN user TEXT NOT NULL DEFAULT ''` で移行する (旧メモは `user=''` となり通常ユーザーからはアクセス不能だが admin からは操作可能)。

### Search

`search_memos_db(keywords: list[str], limit)` はタイトルの部分一致 (`title LIKE '%kw%'`) で検索する。複数キーワードは `OR` で結合し、いずれかに一致したメモを返す。各メモには Python 側で `matched_keywords` (一致したキーワードのリスト) を付与する。LIKE のワイルドカード (`%` `_`) と `\` は `ESCAPE '\'` でリテラル化するため、ユーザー入力に含まれても全件マッチにならない。SQLite の `LIKE` は ASCII 範囲で大文字小文字を区別しない (`matched_keywords` の判定も `str.lower()` で揃える)。

`search_memos` ツールが `query` をカンマで分割し、空文字・重複を除いたキーワードリストにして DB 層へ渡す。

### Semantic Search

`semantic_search_memos(query, limit=5)` は**概要 (summary) の意味的な近さ**で検索する別ツール。`service.semantic_search` がクエリの埋め込みと各メモ概要の埋め込みのコサイン類似度を計算し、`similarity` (0〜1) を付けて降順で最大 `limit` 件返す。概要が空のメモは対象外。ユーザー分離・admin 横断は候補取得に `list_memos_db(..., is_admin=...)` を再利用して既存と同じ挙動にする。

埋め込みは OpenAI API (`text-embedding-3-small`、多言語) を使い、`OPENAI_API_KEY` が要る (`MEMO_EMBEDDING_MODEL` で上書き可)。キー未設定・API 失敗は `EmbeddingError` となり、ツールが `Error: ...` 文字列にして返す (他ツールには影響しない)。

埋め込みは検索時に**遅延計算**して `memo_embeddings` にキャッシュする (`create_memo`/`update_memo` では計算しない)。`summary_hash` と `model` が一致する間は再利用し、概要やモデルが変わったメモだけ再計算する。`_CANDIDATE_CAP` (=1000) で更新日時の新しい順に上限件数だけランキング対象にする。メモ削除時のキャッシュ行は残るが読まれず無害 (掃除したいときは `repository.embedding.delete_embedding`)。初回の未キャッシュ多数は N+1 回の API 呼び出しになる点に注意 (将来バッチ化の余地)。

### Tool result の冗長性

`create_memo` / `update_memo` はレコード全体ではなく `delete_memo` と同様の簡潔なメッセージ (`Created memo id=N.` / `Updated memo id=N.`) を返し、LLM のコンテキスト消費を抑える。レコードの中身が必要なときは `get_memo` / `list_memos` / `search_memos` を使う。

### スキーマを変更する場合

`init_db()` の `CREATE TABLE` を更新する。既存 DB に列を足す場合は、`user` カラムで使っている軽量パターン (`PRAGMA table_info` で存在確認 → 無ければ `ALTER TABLE ADD COLUMN`) を踏襲する。複数バージョンにまたがる本格的なマイグレーションが必要になれば `dynamic_prompt` の `_MIGRATIONS` 方式を参考にする。

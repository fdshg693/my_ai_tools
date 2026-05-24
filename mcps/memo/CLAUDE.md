# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Scope

This file covers `mcps/memo/` only — a FastMCP-based simple memo (title + summary) management MCP server.

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
```

## Architecture

The server exposes 11 MCP tools. **Memo tools (6):** `create_memo`, `get_memo`, `list_memos`, `search_memos`, `update_memo`, `delete_memo`. **User management tools (5, admin-only):** `create_user`, `get_user`, `list_users`, `update_user`, `delete_user`.

### Module structure

| Module | Responsibility |
|--------|---------------|
| `database.py` | SQLite connection factory (`_connect_db`), `init_db()` (起動時スキーマ初期化 + `user` カラムの軽量マイグレーション + `users` テーブル作成 + `admin` シード), メモの CRUD・検索ヘルパー (`*_memo_db`) とユーザー台帳の CRUD ヘルパー (`*_user_db` / `is_registered_user`)。メモ系の get/list/search/update/delete は末尾に `is_admin` を取り、True のとき user 絞り込みを外して全メモを対象にする。`ADMIN_USER = "admin"`。`DB_PATH` は環境変数 `MEMO_DB_PATH` で上書き可能 |
| `auth.py` | 接続中ユーザーの識別。`current_user()` が HTTP リクエストコンテキスト内ならクエリパラメータ `user` を、stdio なら起動時に `set_stdio_user()` で記録した値を返す。識別できなければ None。登録判定 (`is_registered_user`) と admin 判定は tools 側で行う |
| `tools.py` | 11 個の `@mcp.tool` 関数。共通の `_auth()` が `current_user()` → 登録チェック (`is_registered_user`) を行い `(user, is_admin, error)` を返す。`error` があればツールはそれを返して中断。メモツールは `is_admin` を DB 層へ渡す。ユーザー管理ツールは `is_admin` でなければ `admin-only` エラー。結果は JSON 文字列で返す |
| `main.py` | `mcp` FastMCP instance と entry point (`main()`)。`--user` 引数 (or `MEMO_USER`) を argparse で取り stdio 用に記録。`TRANSPORT` 環境変数で stdio / http を切り替え。`/health` ヘルスチェックを `@mcp.custom_route` で登録 |
| `tests/conftest.py` | pytest 共通設定。DB パスを一時ファイルに差し替え、各テスト前にテーブルを空にする |
| `tests/test_database.py` | DB 操作の単体テスト (CRUD + タイトル部分一致検索、LIKE ワイルドカードのエスケープ) |
| `tests/test_mcp_client.py` | MCPクライアントによるツール登録確認 + CRUD ラウンドトリップ (pytest-asyncio に依存せず `asyncio.run()` で実行) |

`main.py` creates the `mcp` instance, then `tools.py` imports it via side-effect import (`import memo.tools`) to register tool functions. `init_db()` はモジュールレベルで呼ばれるため、どの起動経路でも確実に DB 初期化される。

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

### User isolation・登録制・admin 特権

メモは作成した接続ユーザーが所有する。通常 (`is_admin=False`) は全 `*_memo_db` ヘルパーが `WHERE user = ?` で絞り込むため、他ユーザーのメモは一覧・検索に出ず、`get`/`update`/`delete` で他人の ID を指定しても「対象なし」(None / False) となり、存在自体を漏らさない。

接続は `users` 台帳に登録されたユーザーのみ許可する。`_auth()` が未識別 (`current_user()` が None) と未登録 (`is_registered_user` が False) を両方拒否する。`admin` (`ADMIN_USER`) は `init_db()` で `INSERT OR IGNORE` により必ずシードされる固定ユーザーで、削除できない (`delete_user` がガード)。

`admin` 接続のときだけメモツールが `is_admin=True` で呼ばれ、user 絞り込みを外して全ユーザー (`user=''` の孤立メモ含む) を操作する。ユーザー管理ツール (`*_user`) は `is_admin` でなければ `admin-only` エラー。ユーザーを削除してもメモは残す (削除されたユーザーは未登録となり接続を拒否されるため、残ったメモは admin のみ操作可)。

`init_db()` は `user` カラムが無い既存 DB を `ALTER TABLE ADD COLUMN user TEXT NOT NULL DEFAULT ''` で移行する (旧メモは `user=''` となり通常ユーザーからはアクセス不能だが admin からは操作可能)。

### Search

`search_memos_db(keywords: list[str], limit)` はタイトルの部分一致 (`title LIKE '%kw%'`) で検索する。複数キーワードは `OR` で結合し、いずれかに一致したメモを返す。各メモには Python 側で `matched_keywords` (一致したキーワードのリスト) を付与する。LIKE のワイルドカード (`%` `_`) と `\` は `ESCAPE '\'` でリテラル化するため、ユーザー入力に含まれても全件マッチにならない。SQLite の `LIKE` は ASCII 範囲で大文字小文字を区別しない (`matched_keywords` の判定も `str.lower()` で揃える)。

`search_memos` ツールが `query` をカンマで分割し、空文字・重複を除いたキーワードリストにして DB 層へ渡す。

### Tool result の冗長性

`create_memo` / `update_memo` はレコード全体ではなく `delete_memo` と同様の簡潔なメッセージ (`Created memo id=N.` / `Updated memo id=N.`) を返し、LLM のコンテキスト消費を抑える。レコードの中身が必要なときは `get_memo` / `list_memos` / `search_memos` を使う。

### スキーマを変更する場合

`init_db()` の `CREATE TABLE` を更新する。既存 DB に列を足す場合は、`user` カラムで使っている軽量パターン (`PRAGMA table_info` で存在確認 → 無ければ `ALTER TABLE ADD COLUMN`) を踏襲する。複数バージョンにまたがる本格的なマイグレーションが必要になれば `dynamic_prompt` の `_MIGRATIONS` 方式を参考にする。

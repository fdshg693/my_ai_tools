# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Scope

This file covers `mcps/memo/` only — a FastMCP-based simple memo (title + summary) management MCP server.

## Commands

```bash
# Run the MCP server (stdio transport — Claude Desktop / VS Code はこの方式で接続する)
uv run memo

# Run the MCP server (HTTP transport — デプロイ向け)
TRANSPORT=http PORT=8080 uv run memo

# 単体テスト (DB の CRUD・検索)
uv run --project mcps/memo pytest mcps/memo/src/memo/tests/ -v

# MCPクライアントでツール一覧を確認 (インプロセス接続)
uv run python -m memo.tests.test_mcp_client
```

## Architecture

The server exposes 6 MCP tools: `create_memo`, `get_memo`, `list_memos`, `search_memos`, `update_memo`, `delete_memo`.

### Module structure

| Module | Responsibility |
|--------|---------------|
| `database.py` | SQLite connection factory (`_connect_db`), `init_db()` (起動時スキーマ初期化), メモの CRUD・検索ヘルパー (`*_db` 関数群)。`DB_PATH` は環境変数 `MEMO_DB_PATH` で上書き可能 |
| `tools.py` | 6 個の `@mcp.tool` 関数。`database.py` のヘルパーを薄くラップし、結果を JSON 文字列で返す |
| `main.py` | `mcp` FastMCP instance と entry point (`main()`)。`TRANSPORT` 環境変数で stdio / http を切り替え。`/health` ヘルスチェックを `@mcp.custom_route` で登録 |
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
| `title` | TEXT NOT NULL | タイトル |
| `summary` | TEXT NOT NULL DEFAULT '' | 概要 |
| `created_at` | TEXT NOT NULL | 作成日時 |
| `updated_at` | TEXT NOT NULL | 更新日時 (update 時に `datetime('now')` で更新) |

### Search

`search_memos_db(keywords: list[str], limit)` はタイトルの部分一致 (`title LIKE '%kw%'`) で検索する。複数キーワードは `OR` で結合し、いずれかに一致したメモを返す。各メモには Python 側で `matched_keywords` (一致したキーワードのリスト) を付与する。LIKE のワイルドカード (`%` `_`) と `\` は `ESCAPE '\'` でリテラル化するため、ユーザー入力に含まれても全件マッチにならない。SQLite の `LIKE` は ASCII 範囲で大文字小文字を区別しない (`matched_keywords` の判定も `str.lower()` で揃える)。

`search_memos` ツールが `query` をカンマで分割し、空文字・重複を除いたキーワードリストにして DB 層へ渡す。

### Tool result の冗長性

`create_memo` / `update_memo` はレコード全体ではなく `delete_memo` と同様の簡潔なメッセージ (`Created memo id=N.` / `Updated memo id=N.`) を返し、LLM のコンテキスト消費を抑える。レコードの中身が必要なときは `get_memo` / `list_memos` / `search_memos` を使う。

### スキーマを変更する場合

`init_db()` の `CREATE TABLE` を更新する。既存 DB がある場合は `ALTER TABLE` によるマイグレーションが必要になるが、現状は単一テーブルのためマイグレーション機構は持たない (必要になれば `dynamic_prompt` の `_MIGRATIONS` 方式を参考にする)。

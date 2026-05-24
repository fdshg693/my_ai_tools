# memo

タイトル・概要を持つメモを管理するシンプルな MCP サーバー。

- SQLite にメモ (タイトル + 概要) を保存する
- CRUD (作成・取得・一覧・更新・削除) を MCP ツールとして提供
- 検索はタイトルの**部分一致**で行う (大文字小文字を区別しない)

## 実行

```bash
# stdio トランスポート (Claude Desktop / VS Code はこの方式で接続する)
uv run memo

# HTTP トランスポート (デプロイ向け)
TRANSPORT=http PORT=8080 uv run memo
```

DB ファイルの場所は環境変数 `MEMO_DB_PATH` で上書きできる (デフォルト: `src/memo/memo.db`)。

## ツール一覧

| ツール | 引数 | 説明 |
|--------|------|------|
| `create_memo` | `title`, `summary=""` | メモを新規作成し、作成したレコードを JSON で返す。`title` は必須。 |
| `get_memo` | `memo_id` | ID でメモを1件取得する。 |
| `list_memos` | `limit=50` | メモを新しい順 (更新日時の降順) に一覧取得する。 |
| `search_memos` | `query`, `limit=50` | タイトルの部分一致でメモを検索する。 |
| `update_memo` | `memo_id`, `title=None`, `summary=None` | 指定したフィールドのみ更新する。 |
| `delete_memo` | `memo_id` | メモを削除する。 |

## データモデル

`memos` テーブル:

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER PK | Auto-increment |
| `title` | TEXT NOT NULL | タイトル |
| `summary` | TEXT NOT NULL DEFAULT '' | 概要 |
| `created_at` | TEXT NOT NULL | 作成日時 (`datetime('now')`) |
| `updated_at` | TEXT NOT NULL | 更新日時 (`datetime('now')`) |

## テスト

```bash
# 単体テスト (DB の CRUD・検索)
uv run --project mcps/memo pytest mcps/memo/src/memo/tests/ -v

# MCP クライアントでツール一覧を確認 (インプロセス接続)
uv run python -m memo.tests.test_mcp_client
```

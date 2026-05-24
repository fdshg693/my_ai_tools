# memo

タイトル・概要を持つメモを管理するシンプルな MCP サーバー。

- SQLite にメモ (タイトル + 概要 + 所有ユーザー) を保存する
- CRUD (作成・取得・一覧・更新・削除) を MCP ツールとして提供
- 検索はタイトルの**部分一致**で行う (大文字小文字を区別しない)。カンマ区切りで複数キーワードを OR 検索でき、各メモがどのキーワードに一致したかを返す
- **ユーザーごとに完全分離**: メモには作成した接続ユーザーが所有者として記録され、他ユーザーは読み取りも含め一切操作できない

## ユーザーの識別

すべてのメモは「接続ユーザー」が所有する。ユーザーはトランスポートごとに異なる方法で渡す。

| トランスポート | 指定方法 | 例 |
|---------------|---------|----|
| stdio | 起動引数 `--user`（または環境変数 `MEMO_USER`）。プロセス全体でユーザーは1人に固定される | `uv run memo --user alice` |
| HTTP | MCP エンドポイントのクエリパラメータ `?user=` | `http://host:8080/mcp?user=alice` |

ユーザーを識別できない接続は、すべてのツール呼び出しがエラーで拒否される。

## 実行

```bash
# stdio トランスポート (Claude Desktop / VS Code はこの方式で接続する)
uv run memo --user alice

# HTTP トランスポート (デプロイ向け)。接続側は /mcp?user=NAME を指定する
TRANSPORT=http PORT=8080 uv run memo
```

DB ファイルの場所は環境変数 `MEMO_DB_PATH` で上書きできる (デフォルト: `src/memo/memo.db`)。

## ツール一覧

いずれのツールも操作対象は「接続ユーザー自身のメモ」に限られる。他ユーザーのメモを ID 指定しても、存在を漏らさないため「not found」として扱われる。

| ツール | 引数 | 説明 |
|--------|------|------|
| `create_memo` | `title`, `summary=""` | メモを新規作成する。`title` は必須。所有者は接続ユーザー。成功時は作成した id を含む短いメッセージを返す。 |
| `get_memo` | `memo_id` | ID で自分のメモを1件取得する。 |
| `list_memos` | `limit=50` | 自分のメモを新しい順 (更新日時の降順) に一覧取得する。 |
| `search_memos` | `query`, `limit=50` | 自分のメモをタイトルの部分一致で検索する。`query` はカンマ区切りで複数キーワードを指定でき、いずれかに一致したメモを返す (OR 検索)。各メモに `matched_keywords` を付与し、どのキーワードに一致したかを明示する。 |
| `update_memo` | `memo_id`, `title=None`, `summary=None` | 自分のメモの指定したフィールドのみ更新する。成功時は短いメッセージを返す。 |
| `delete_memo` | `memo_id` | 自分のメモを削除する。 |

## データモデル

`memos` テーブル:

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER PK | Auto-increment |
| `user` | TEXT NOT NULL | 所有ユーザー名。全 CRUD・検索はこの値で絞り込む |
| `title` | TEXT NOT NULL | タイトル |
| `summary` | TEXT NOT NULL DEFAULT '' | 概要 |
| `created_at` | TEXT NOT NULL | 作成日時 (`datetime('now')`) |
| `updated_at` | TEXT NOT NULL | 更新日時 (`datetime('now')`) |

> 既存 DB は起動時の `ALTER TABLE` で `user` カラムが追加される。`user` カラムが無かった時代の既存メモは `user=''` となり、どのユーザーからもアクセスできなくなる。

## テスト

```bash
# 単体テスト (DB の CRUD・検索)
uv run --project mcps/memo pytest mcps/memo/src/memo/tests/ -v

# MCP クライアントでツール一覧を確認 (インプロセス接続)
uv run python -m memo.tests.test_mcp_client
```

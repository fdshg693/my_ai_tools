# ツール早見表

各ユースケースの指示文では、以下のツールを名前で指定する。AI 側はこの対応を把握しておくこと。

| ツール | 用途 | 主な引数 |
|--------|------|----------|
| `switch_user` | 現在の接続ユーザーを切り替える (= ログイン)。結果に切替先のカテゴリ一覧を含む | `target` (登録済みユーザー名) |
| `create_memo` | メモを新規作成する | `title` (必須), `summary` (任意), `category` (任意・空欄は `OTHERS`) |
| `get_memo` | ID 指定で 1 件取得する | `memo_id` |
| `list_memos` | 新しい順に一覧する | `limit` (既定 50), `category` (任意・絞り込み) |
| `search_memos` | **タイトルの部分一致**で検索する (キーワード型) | `query` (カンマ区切りで OR 検索), `limit`, `category` (任意・絞り込み) |
| `semantic_search_memos` | **概要の意味的な近さ**で検索する (自然文型) | `query` (自然文可), `limit` (既定 5), `category` (任意・絞り込み) |
| `update_memo` | 既存メモを更新する (指定フィールドのみ) | `memo_id`, `title`, `summary`, `category` (省略=変更なし) |
| `delete_memo` | メモを削除する | `memo_id` |

> ユーザーの新規登録 (`create_user`)・一覧 (`list_users`) などの管理ツールは **admin 専用**。
> 全ツールの詳細は [../TOOLS.md](../TOOLS.md) を参照。

## 検索ツールの使い分け

- **既知の固有名詞・短いキーワードで探すとき** → `search_memos`。`query` をカンマで区切ると OR 検索になり、各メモに `matched_keywords` が付く。タイトルしか見ないため概要は対象外。
- **「○○に関する話題があったか」を意味で探すとき** → `semantic_search_memos`。概要の内容を埋め込みベクトルで比較し、`similarity` (0〜1) を付けて近い順に返す。自然文のクエリで構わない。概要が空のメモは対象外で、利用には `OPENAI_API_KEY` が必要。
- 迷う場合は両方を併用してよい。まず `semantic_search_memos` で当たりを付け、`get_memo` で本文を確認する流れが扱いやすい。

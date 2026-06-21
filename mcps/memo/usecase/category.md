# カテゴリの活用

各メモは 1 つのカテゴリに属する。カテゴリは**ユーザーごとに管理する独立した存在**で、カテゴリで会話の
文脈 (例: `WORK` / `PRIVATE` / `STUDY`) を分けておくと、検索・一覧で**同じ文脈のメモだけ**を見られ、
無関係なメモのノイズを減らせる。

- **正規化**: カテゴリ名は前後の空白を除いて**大文字化**して保存・照合される (`work` / `Work` / `WORK` は同一)。
  指示文で固定のカテゴリを使うときは大文字で書いておくと安全。
- **作成**: `create_category(name)` でそのユーザーのカテゴリを登録する。新規ユーザーは `OTHERS` だけを持つ。
- **付与**: `create_memo` / `update_memo` の `category` で指定する。省略すると `OTHERS`。**未登録のカテゴリを
  指定するとエラー**になるので、新しい文脈で書き始めるときは先に `create_category` で作る。
- **絞り込み**: `list_memos` / `search_memos` / `semantic_search_memos` の `category` を指定すると、
  そのカテゴリのメモだけが結果に出る (省略時は全カテゴリ)。
- **既存カテゴリの把握**: `list_categories()`、またはログイン (`switch_user`) の戻り値にその人の登録済み
  カテゴリ一覧が含まれる。メモ作成時のカテゴリ選びの参考にする。
- **改名・削除**: MCP からはできない (Web 画面 `memo-admin` から)。改名すると紐づくメモも追従し、削除すると
  紐づくメモは `OTHERS` に移る。`OTHERS` は改名・削除できない。

```
switch_user("alice")            → "Switched user to 'alice'. カテゴリ: OTHERS, PRIVATE, WORK"
create_category("WORK")                            ← 新しいカテゴリを登録 (既にあれば不要)
create_memo("立替精算", "...", category="WORK")   ← WORK として保存 (未登録ならエラー)
search_memos("精算", category="WORK")             ← WORK のメモだけから探す
list_memos(category="PRIVATE")                     ← PRIVATE のメモだけ一覧
```

> カテゴリは任意機能。文脈を分ける必要がなければ指定せず `OTHERS` のまま使ってよい。

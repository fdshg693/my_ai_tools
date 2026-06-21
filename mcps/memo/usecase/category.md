# カテゴリの活用

各メモは 1 つのカテゴリに属する。カテゴリで会話の文脈 (例: `WORK` / `PRIVATE` / `STUDY`) を分けておくと、
検索・一覧で**同じ文脈のメモだけ**を見られ、無関係なメモのノイズを減らせる。

- **正規化**: カテゴリ名は前後の空白を除いて**大文字化**して保存・照合される (`work` / `Work` / `WORK` は同一)。
  指示文で固定のカテゴリを使うときは大文字で書いておくと安全。
- **付与**: `create_memo` / `update_memo` の `category` で指定する。省略すると `OTHERS` に分類される。
- **絞り込み**: `list_memos` / `search_memos` / `semantic_search_memos` の `category` を指定すると、
  そのカテゴリのメモだけが結果に出る (省略時は全カテゴリ)。
- **既存カテゴリの把握**: ログイン (`switch_user`) の戻り値にその人のカテゴリ一覧が含まれる。
  そこに無いカテゴリを使うと事実上の新規カテゴリになるため、既存に寄せたいときは一覧を参考にする。

```
switch_user("alice")            → "Switched user to 'alice'. メモのカテゴリ: PRIVATE, WORK"
create_memo("立替精算", "...", category="WORK")   ← WORK として保存
search_memos("精算", category="WORK")             ← WORK のメモだけから探す
list_memos(category="PRIVATE")                     ← PRIVATE のメモだけ一覧
```

> カテゴリは任意機能。文脈を分ける必要がなければ指定せず `OTHERS` のまま使ってよい。

# MCP ツール一覧

memo が公開している 15 個の MCP ツールと、その使い方・注意点をまとめる。引数の細かい仕様は変わりやすいので、ここではツールの**役割**と**他ツールとの関係**を中心に扱う。実際のシグネチャは [tools/memo.py](src/memo/server/mcp/tools/memo.py) / [tools/category.py](src/memo/server/mcp/tools/category.py) / [tools/user.py](src/memo/server/mcp/tools/user.py) の docstring を参照すること。各ツールの内部挙動の詳細は [CLAUDE.md](./CLAUDE.md)、システムプロンプトへの組み込み例は [USECASE.md](./USECASE.md) を参照。

## カテゴリ別早見表

| カテゴリ | ツール |
|---------|--------|
| メモ CRUD | `create_memo`, `get_memo`, `list_memos`, `update_memo`, `delete_memo` |
| メモ検索 | `search_memos` (タイトル部分一致), `semantic_search_memos` (概要の意味検索) |
| カテゴリ (作成・閲覧のみ) | `create_category`, `list_categories` |
| ユーザー管理 (admin 専用) | `create_user`, `get_user`, `list_users`, `update_user`, `delete_user` |
| セッション | `switch_user` (現在ユーザーの切り替え。admin 専用ではない) |

## 前提: 接続ユーザーと権限

すべてのツールは呼び出し時にまず**接続ユーザーを識別・登録チェック**する (`authz.resolve_caller()`)。識別できない、または `users` 台帳に未登録の接続は、全ツールがエラーで拒否される。ユーザーの渡し方はトランスポートで異なる (stdio: 起動引数 `--user` / 環境変数 `MEMO_USER`、HTTP: クエリ `?user=`)。詳細は [README.md](./README.md)。

- **通常ユーザー**: 自分が作成したメモ・カテゴリだけを操作できる。他人のメモは一覧・検索に出ず、ID を直接指定しても「not found」になる (存在を漏らさない)。
- **管理者 (admin)**: 管理者は**ユーザー管理ツールを使えるだけ**で、他人のメモやカテゴリは一切操作できない (自分のメモ・カテゴリだけ)。**管理者かどうかは名前ではなく `is_admin` フラグで判定する** (名前が `admin` でなくてもフラグを立てれば管理者)。既定の管理者 `admin` (`is_admin=1`) は DB 初期化時に自動登録される。`is_admin` の付与・剥奪は管理 Web UI (`memo-admin`) からのみ行える。

```
未登録/未識別 ──► すべてのツールが拒否
通常ユーザー   ──► 自分のメモ・カテゴリのみ (メモ CRUD + 検索 + カテゴリ作成/一覧)
管理者(is_admin) ──► 上記に加えてユーザー管理ツール (他人のメモは操作不可)
```

---

## メモ CRUD

```
        create_memo ──┐
                      ▼
                  memos DB ◀── update_memo / delete_memo
                      ▲
        get_memo / list_memos / search_memos / semantic_search_memos
```

### `create_memo(title, summary="", category="")`

メモを新規作成する。作成者は接続中ユーザーとして記録される。

- **役割**: メモ蓄積の入口。`title` は必須、`summary` / `category` は任意。
- **カテゴリ**: 省略すると `OTHERS` に分類される。指定する場合は**自分が登録済みのカテゴリ**でなければならず、未登録の名前を渡すとエラーになる (先に `create_category` で作成する)。カテゴリ名は大文字に正規化される (`work`→`WORK`)。詳細は後述の「カテゴリ」。
- **返却**: 全文ではなく作成した id と正規化後カテゴリを含む短いメッセージ (`Created memo id=N (category=WORK).`)。内容が必要なら `get_memo` で取得する。
- **連携**: `summary` を埋めておくと後で `semantic_search_memos` で意味検索できる。

### `get_memo(memo_id)`

ID 指定で 1 件取得する。

- **役割**: 検索でヒットしたメモの本文を読み込む窓口。
- **権限**: 自分のメモのみ (admin も他人のメモは取得できない)。見つからなければその旨を返す。

### `list_memos(limit=50, category="")`

メモを新しい順 (更新日時の降順) に一覧する。

- **役割**: 会話冒頭で「既知の情報」を把握する用途に向く。件数が多ければ検索系で絞り込む。
- **カテゴリ絞り込み**: `category` を指定すると同一カテゴリのメモだけを返す (省略時は全カテゴリ・大文字小文字は区別しない)。
- **権限**: 自分のメモのみ (admin も他人のメモは見えない)。

### `update_memo(memo_id, title=None, summary=None, category=None)`

既存メモを更新する。**指定したフィールドのみ**変更する (省略したフィールドは据え置き)。

- **役割**: 既存メモへの追記・修正。新規作成の代わりに使うと検索しやすい粒度を保てる。
- **カテゴリ**: `category` を省略すると変更しない。空文字を渡すと `OTHERS` に戻る。それ以外を指定する場合は**登録済みカテゴリ**である必要があり、未登録ならエラー。指定した値は大文字に正規化される。
- **連携**: 更新で `summary` が変わると、次回の `semantic_search_memos` 時に埋め込みが再計算される。

### `delete_memo(memo_id)`

メモを削除する。

- **役割**: 誤りと判明した情報の除去。
- **権限**: 自分のメモのみ (admin も他人のメモは削除できない)。

---

## メモ検索

検索は 2 系統あり、目的で使い分ける。

### `search_memos(query, limit=50, category="")` — タイトル部分一致 (キーワード型)

タイトルの部分一致で検索する (大文字小文字を区別しない)。

- **使いどころ**: 既知の固有名詞・短いキーワードで探すとき。
- **OR 検索**: `query` をカンマ (`,`) で区切ると、いずれかに一致したメモを返す。各メモには一致した `matched_keywords` が付く。
- **カテゴリ絞り込み**: `category` を指定すると同一カテゴリのメモだけを対象にする (省略時は全カテゴリ)。
- **対象範囲**: タイトルのみ (概要は対象外)。

### `semantic_search_memos(query, limit=5, category="")` — 概要の意味検索 (自然文型)

概要 (summary) の意味的な近さで検索する。

- **使いどころ**: 「○○に関する話題があったか」を意味で探すとき。`query` は自然文で構わない。
- **カテゴリ絞り込み**: `category` を指定すると同一カテゴリのメモだけを対象にする (省略時は全カテゴリ)。
- **返却**: 概要を埋め込みベクトルで比較し、`similarity` (0〜1) を付けて近い順に返す。概要が空のメモは対象外。
- **必要要件**: OpenAI API を使うため `OPENAI_API_KEY` が必要 (`mcps/memo/.env` から読み込み可)。キーが無い・API 失敗時はこのツールだけが `Error: ...` を返し、他ツールは影響を受けない。
- **コスト注意**: 埋め込みは検索時に遅延計算してキャッシュされる。初回に未キャッシュのメモが多いと、その数だけ API を呼ぶ。

> 迷う場合は両方併用してよい。まず `semantic_search_memos` で当たりを付け、`get_memo` で本文を確認する流れが扱いやすい。

---

## カテゴリ

カテゴリは**各ユーザーが所有する独立した存在**で、メモは自分が登録済みのカテゴリにだけ紐づけられる。新規ユーザーは既定の `OTHERS` だけを持ち、必要なカテゴリを追加していく。MCP からは**作成・閲覧 (C/R) のみ**でき、改名・削除は Web 画面 (`memo-admin`) から行う。

- **正規化**: カテゴリ名は前後の空白を除いて**大文字化**して保存・照合する。`work` / `Work` / `WORK` は同じカテゴリになる。
- **登録 (C)**: `create_category(name)` でそのユーザーのカテゴリを作る。メモに新しいカテゴリを付けたいときは**先にこれで作成**する (未登録カテゴリでのメモ作成・更新はエラー)。
- **閲覧 (R)**: `list_categories()` で自分のカテゴリ一覧を取得する。`switch_user` の成功メッセージにも切り替え先のカテゴリ一覧が併記される。
- **絞り込み (読み取り)**: `list_memos` / `search_memos` / `semantic_search_memos` の `category` を指定すると、**同一カテゴリのメモだけ**が結果に出る。省略すると全カテゴリが対象。
- **改名・削除 (U/D)**: Web 画面から行う。改名するとそのカテゴリに紐づくメモも自動で追従し、削除すると紐づくメモは `OTHERS` に移る。既定の `OTHERS` は改名・削除できない。
- **使いどころ**: 仕事用・私用などメモを分けておき、検索時にカテゴリを添えて他カテゴリのノイズを除く。

```
create_category("work")                        ← まずカテゴリを登録
create_memo("立替精算", category="work")        ← WORK として保存 (未登録ならエラー)
search_memos("精算", category="work")           ← WORK のメモだけから探す (private 等は出ない)
list_memos(category="private")                  ← PRIVATE のメモだけ一覧
```

### `create_category(name)` / `list_categories()`

- `create_category`: 接続中ユーザーのカテゴリを 1 つ作る。`name` 必須・大文字に正規化。既に存在すればその旨を返す。
- `list_categories`: 接続中ユーザーのカテゴリを名前順に返す。

---

## ユーザー管理 (admin 専用)

**管理者 (`is_admin`) のユーザー**で接続したときだけ使える。それ以外の接続では `admin-only` エラーを返す。接続を許可するユーザーを管理するためのツール群。**管理者権限 (`is_admin`) の付与・剥奪はこれらのツールではできない**——管理 Web UI (`memo-admin`) からのみ編集できる。

```
  create_user ──► users 台帳 ──► (登録されたユーザーだけが接続を許可される)
                     ▲
  get_user / list_users / update_user / delete_user
```

### `create_user(name, display_name="", note="")`

新しい (非管理者の) ユーザーを登録する。登録されたユーザーだけが接続できるようになる。

- `name` は必須・一意。既に存在すればその旨を返す (no-op)。
- このツールで作るユーザーは常に非管理者。管理者にするには登録後、管理 Web UI で `is_admin` を立てる。
- 新しいユーザーを使い始めるには、まず管理者で接続してこのツールで登録する。

### `get_user(name)` / `list_users()`

ユーザーを 1 件取得 / 名前順に一覧する。

### `update_user(name, display_name=None, note=None)`

ユーザー属性 (表示名・備考) を更新する。**ユーザー名 (`name`) は変更できない。** 管理者権限 (`is_admin`) もこのツールでは変更できない (管理 Web UI から)。

### `delete_user(name)`

ユーザーを台帳から削除する (以後そのユーザーは接続できない)。

- そのユーザーのメモ・カテゴリ・埋め込みキャッシュも**まとめて削除される** (孤立データを残さない)。
- **最後の 1 人の管理者は削除できない** (管理者が居なくなるのを防ぐ)。

---

## セッション

### `switch_user(target)` — 現在ユーザーの切り替え (admin 専用ではない)

再接続やサーバー再起動なしに、現在の接続ユーザーを `target` に切り替える。登録済みユーザーなら誰でも呼べる (`admin` への切り替えも可能)。

- **役割**: クライアント側で接続を張り替えられない場合 (Claude アプリなど) に、ツール呼び出し 1 つでユーザーを切り替える。個人ローカル運用向けで、切り替えに認証は要らない。
- **カテゴリ一覧の返却**: 成功時のメッセージに、切り替え先ユーザーの**登録済みカテゴリ一覧**を併記する (例: `Switched user to 'alice'. カテゴリ: OTHERS, PRIVATE, WORK`)。メモ作成時のカテゴリ選びや、以降の `list_memos` / `search_memos` / `semantic_search_memos` を `category` で絞り込む際の手掛かりになる。カテゴリが無ければ「カテゴリはまだありません」と返す。
- **前提**: `target` は `users` 台帳に登録済みであること。未登録なら拒否される。
- **stdio**: そのプロセスの現在ユーザーを実行時に書き換える。
- **HTTP**: 接続時のクエリに `?client_id=` を付けておく必要がある。サーバーは `client_id` ごとに現在ユーザーを保持し、これを書き換える。`client_id` が無い接続では切り替え状態を保持できずエラーになる。詳細は [README.md](./README.md) の「ユーザーの切り替え」。

---

## 典型的な呼び出し順

**通常ユーザーの会話 (知識の蓄積・活用):**

```
1. list_memos(50)                 ← 既知の情報を把握 (件数が多ければ検索系で絞る)
2. semantic_search_memos("...")   ← 今回の話題に関係する過去メモを意味で探す
   (または search_memos で固有名詞検索)
3. get_memo(id)                   ← ヒットしたメモの本文を確認
   ─── 会話 ───
4. create_memo(title, summary)    ← 新しい内容を保存 (既存の続きなら update_memo)
```

**admin によるユーザー追加:**

```
1. admin で接続 (--user admin / ?user=admin)
2. create_user("alice", ...)      ← 接続を許可するユーザーを登録
3. 以後 alice は --user alice / ?user=alice で接続可能
```

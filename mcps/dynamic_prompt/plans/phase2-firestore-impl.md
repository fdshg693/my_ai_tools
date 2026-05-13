# Phase 2: Firestore実装 + 移行スクリプト

## 目的

Firestore版のリポジトリ実装を追加し、`DATA_BACKEND=firestore` で動かせるようにする。エミュレータで全テストが緑化するところまで。

## 前提

- Phase 1 完了（リポジトリ層が導入済み）
- ローカルに `gcloud` CLI と Firestore エミュレータがインストール済み

## 完了基準

- `DATA_BACKEND=firestore FIRESTORE_EMULATOR_HOST=127.0.0.1:8085 uv run dynamic_prompt` で起動し、MCPツール（`get_words`/`save_words`/`send_quiz`/`get_quiz_results`/`save_story_topic`/`get_past_topics`）がエミュレータ相手に動作
- Firestoreエミュレータ起動下で `pytest` 全緑
- 移行スクリプト（dry-run）が SQLite → Firestore の件数差を正しくレポート

## ステップ

### 2.1 依存追加

`pyproject.toml` に `google-cloud-firestore>=2.16.0` を追加。`uv sync`。

### 2.2 Firestore実装

新規ファイル: `src/dynamic_prompt/repo/firestore_repo.py`

クラス: `FirestoreVocabRepo`, `FirestoreQuizRepo`, `FirestoreTopicRepo`

**コレクション/ドキュメント設計**:

```
unknown_words/{lang}__{word}          # 自然ID
  fields: lang, word, context, status, reviewed_at(Timestamp|None), created_at(Timestamp)

quiz_sessions/{auto_id}
  fields: lang, title, created_at, submitted_at(Timestamp|None), scored_at(Timestamp|None)
  questions/{question_index}          # サブコレクション。doc IDは0始まりのインデックス文字列
    fields: question_text, choices(array<string>), correct_index,
            user_answer(int|None), is_correct(bool|None),
            question_type ('mc'|'free'), model_answer, user_answer_text

story_topics/{auto_id}
  fields: lang, topic, summary, created_at
```

**主要メソッドの実装ポイント**:

- `save_words`: `(lang+word)` の自然IDで `set(merge=True)` で upsert。`created_at` は新規時のみ `SERVER_TIMESTAMP`、既存ならtouchしない（`update_existing=False` で制御）。
- `get_review_pool`: `where("lang", "==", lang)` + `where("status", "in", ["unlearned", "wrong"])` で取り、Python側で `reviewed_at < cutoff` を含む `memory_test` 分も別途取得して結合 → ランダムサンプル → limit。Firestoreの `OR` クエリ制約に合わせて2回クエリ + Python側マージが素直。
- `update_status`: `lang+word` の doc を更新。`status` 変化時のみ `reviewed_at` を書き換え（既存 `database.py` の挙動を踏襲）。
- `create_mc_session` / `create_free_session`: `session_doc.set(...)` + 各 question を `questions/{i}.set(...)`。バッチで一括コミット。
- `get_pending`: `where("submitted_at", "==", None)` で取得しサブコレクション展開。
- `submit_*_answers`: トランザクションで session の `submitted_at` 更新 + question の `user_answer`/`is_correct`/`user_answer_text` 更新。
- `score_free_answers`: バッチで各 question の `is_correct` を更新し、session の `scored_at` を `SERVER_TIMESTAMP`。
- `get_recent_results`: `quiz_sessions` を `submitted_at` 降順で limit 取得 → サブコレクション展開。
- `save_topic`, `list_recent`: 単純な `add` / `where + order_by + limit`。

**初期化** (`init`): Firestoreはスキーマレスのため特に処理なし。エミュレータ接続確認のみログ出力。

### 2.3 RepoBundle ファクトリ拡張

`src/dynamic_prompt/repo/__init__.py` に追加:

```python
def build_firestore_repo(project: str | None = None) -> RepoBundle:
    from google.cloud import firestore
    client = firestore.Client(project=project)
    return RepoBundle(
        vocab=FirestoreVocabRepo(client),
        quiz=FirestoreQuizRepo(client),
        topic=FirestoreTopicRepo(client),
    )

def init_repo(backend: str = "sqlite") -> RepoBundle:
    if backend == "firestore":
        _repo = build_firestore_repo(os.environ.get("GOOGLE_CLOUD_PROJECT"))
    elif backend == "sqlite":
        _repo = build_sqlite_repo()
    ...
```

### 2.4 テストの二重化

`tests/conftest.py` を拡張し、`pytest --backend=firestore` または環境変数 `TEST_BACKEND` でリポジトリ実装を切り替え。デフォルトは `sqlite`（CI高速化のため）。

`FIRESTORE_EMULATOR_HOST` がセットされている場合のみ Firestore テストを実行（未設定なら `pytest.skip`）。

または `pytest.mark.parametrize("backend", ["sqlite", "firestore"])` 形式で各テスト関数を二重実行する方式も可。

具体的な実装方針:
- 既存テスト群（`test_database.py` → `test_repo.py` にリネーム検討）をリポジトリ非依存に書き換え、`get_repo()` 経由でデータ操作
- conftestで `init_repo(backend)` をパラメータ化したフィクスチャを提供
- Firestoreエミュレータが立っていない時は自動スキップ

### 2.5 移行スクリプト

新規ファイル: `src/dynamic_prompt/migrate_to_firestore.py`

```
uv run python -m dynamic_prompt.migrate_to_firestore \
    --source /path/to/vocab.db \
    --project dynamic-prompt-mcp \
    [--dry-run]
```

処理:
1. SQLite を読み込み、各テーブルの件数をログ
2. 各テーブルを Firestore に書き込み（500件バッチ）
   - `unknown_words` → `set(merge=False)` で自然IDに upsert
   - `quiz_sessions` → 新規 auto-id 割り当て。`questions` を `quiz_sessions/{new_id}/questions/{question_index}` へ
   - `story_topics` → 新規 auto-id でadd
3. `--dry-run` の場合は実際の書き込みをスキップし、書き込み予定件数だけレポート
4. 書き込み後、Firestore 側の件数を `aggregate_query.count()` で取得し SQLite 側と突き合わせ
5. 差分があればexit code 1

このスクリプトは Phase 5 で本番に対して使う。Phase 2 ではローカルSQLite→ローカルエミュレータで動作確認するのみ。

### 2.6 動作確認

```powershell
# エミュレータ起動
gcloud beta emulators firestore start --host-port=127.0.0.1:8085

# 別ターミナルで
$env:FIRESTORE_EMULATOR_HOST="127.0.0.1:8085"
$env:GOOGLE_CLOUD_PROJECT="dynamic-prompt-mcp-test"
$env:DATA_BACKEND="firestore"
cd c:\CodeRoot\my_ai_tools\mcps\dynamic_prompt

# テスト
uv run --project . pytest src/dynamic_prompt/tests/ -v

# 起動確認
$env:TRANSPORT="http"; $env:PORT="8080"
uv run dynamic_prompt
# 別ターミナルで curl http://localhost:8080/health → 200

# 移行スクリプトdry-run
uv run python -m dynamic_prompt.migrate_to_firestore --source src/dynamic_prompt/vocab.db --project dynamic-prompt-mcp-test --dry-run
```

## ロールバック

`DATA_BACKEND=sqlite` で起動すれば従来挙動。Firestore側にデータが入っても他に影響なし。

## 注意

- Firestore Pythonクライアントは同期APIを使う（既存コードベースが同期前提）。非同期版 `AsyncClient` は使わない
- `get_review_pool` のランダム性: SQLite版は `ORDER BY RANDOM()`。Firestore版は全候補取得 → Python `random.sample`。件数が膨大になると非効率だが、個人利用規模では問題なし
- タイムスタンプ比較: 既存DBはISO 8601文字列でリテラル比較していた。Firestoreは `Timestamp` 型で比較するため、`datetime.fromisoformat` で変換するヘルパを用意

# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Scope

This file covers `mcps/dynamic_prompt/` only — a FastMCP-based language learning MCP server.

## Commands

```bash
# Run the MCP server (stdio transport — Claude Desktop はこの方式で接続する)
# クイズWebサーバーも自動的に起動する (default: http://127.0.0.1:8765)
uv run dynamic_prompt

# Run the MCP server (HTTP transport — GCP Cloud Run 等のデプロイ向け)
TRANSPORT=http PORT=8080 uv run dynamic_prompt

# Validate YAML configuration consistency (checks template variables match dataclass fields)
uv run mcps/dynamic_prompt/src/dynamic_prompt/validate.py
```

### インフラ (Docker / Cloud Build / Terraform)

`mcps/dynamic_prompt/infra/` に `justfile` を用意している ([just](https://github.com/casey/just) が必要)。詳細は `infra/CLAUDE.md` を参照。

```bash
cd mcps/dynamic_prompt/infra

just                # レシピ一覧表示
just build          # Docker イメージをビルド
just run            # コンテナ起動 (localhost:8080)
just stop           # コンテナ停止・削除
just health         # ローカルヘルスチェック
just cloud-build    # Cloud Build でイメージビルド & プッシュ
just tf-init        # terraform init
just tf-plan        # terraform plan
just tf-apply       # terraform apply
just tf-output      # terraform output (URL 確認)
just cloud-health   # Cloud Run ヘルスチェック (認証不要)
just deploy         # cloud-build → tf-apply 一括
```

- **GCP プロジェクト**: `dynamic-prompt-mcp`
- **リージョン**: `asia-northeast1`
- **Cloud Run URL**: `https://dynamic-prompt-m2py3twbha-an.a.run.app`
- **MCP エンドポイント**: `https://dynamic-prompt-m2py3twbha-an.a.run.app/mcp`
- **Artifact Registry**: `asia-northeast1-docker.pkg.dev/dynamic-prompt-mcp/dynamic-prompt/server`

```bash
# MCPクライアントでサーバーの動作確認（インプロセス接続）
uv run python -m dynamic_prompt.tests.test_mcp_client
```

```bash
# 単体テストを実行（pytest — ステータス遷移・テンプレート解決・DB操作）
uv run --project mcps/dynamic_prompt pytest mcps/dynamic_prompt/src/dynamic_prompt/tests/ -v
```

The validator (`validate.py`) and unit tests are the primary correctness checks.

## Architecture

The server exposes 13 MCP tools: `determine_language`, `get_instruction`, `get_words`, `save_words`, `answer_words`, `send_quiz`, `send_free_quiz`, `get_quiz_results`, `get_unscored_quizzes`, `score_free_answers`, `get_past_topics`, `save_story_topic`, `reload_config`.

### Module structure

`src/dynamic_prompt/` is split by responsibility:

| Module | Responsibility |
|--------|---------------|
| `models.py` | Dataclasses (`Language`, `UserConfig`, `AppConfig`, `Instruction`) — すべて `frozen=True` |
| `config_source.py` | `ConfigSource` 抽象 (`LocalConfigSource` / `GCSConfigSource`) と factory。`PROMPTS_URI` で切替 |
| `config.py` | YAML loading, path constants, TTL キャッシュ付き `ConfigStore` (`config_store` シングルトン)。アクセス時に TTL を確認して自動 refresh |
| `session.py` | `_Session` class and singleton — holds the current target language |
| `repo/base.py` | リポジトリ層のインタフェース。`VocabRepo` / `QuizRepo` / `TopicRepo` の Protocol と `RepoBundle` dataclass。バックエンド非依存の抽象 (Phase 1 で導入、Firestore 移行に備える) |
| `repo/sqlite_repo/` | SQLite 実装パッケージ (責務ごとに分割)。`__init__.py` が全名前を re-export し `build_sqlite_repo()` で `RepoBundle` を構築。`connection.py` (`DB_PATH` / `_connect_db`)、`schema.py` (テーブル定義・マイグレーション `_MIGRATIONS` / `init_db`)、`vocab.py` (単語・復習プール・ステータス遷移 `_save_word` / `_process_answer` + `SqliteVocabRepo`)、`quiz.py` (MC + free クイズ + `SqliteQuizRepo`)、`topic.py` (話題 + `SqliteTopicRepo`)。各サブモジュールの module 関数が SQL の唯一の出所で、`Sqlite*Repo` はその薄い OO ラッパー。`DB_PATH` は `connection.py` が出所で環境変数で上書き可能 |
| `repo/__init__.py` | `init_repo(backend)` でバックエンド初期化、`get_repo()` でシングルトン `RepoBundle` 取得。`DATA_BACKEND` 環境変数 (既定 `sqlite`) でバックエンド選択 |
| `database.py` | 後方互換用の薄い shim。`repo/sqlite_repo.py` の旧 API 名を re-export するだけ (既存テスト等の旧 import を維持)。Phase 2-5 で削除予定。新規コードは `get_repo()` を使うこと |
| `tools.py` | Variable resolvers, template rendering, vocab/quiz/story tools, and 13 `@mcp.tool` functions。DB アクセスは `get_repo()` 経由 |
| `main.py` | `mcp` FastMCP instance and entry point (`main()`), トランスポート切り替え (`TRANSPORT` 環境変数)、ヘルスチェック (`/health`)、HTTP モード時の OAuth 認証 (`GoogleProvider`)、stdio 時のみ quiz server startup |
| `quiz_server.py` | Starlette + uvicorn Webサーバー (SSE, REST API, 単語保存API)。デーモンスレッドで起動。ポートプール・グレースフルシャットダウン・古いプロセス自動停止に対応 |
| `static/quiz.html` | クイズ UI の HTML 構造 |
| `static/quiz.css` | クイズ UI のスタイル (CSS 変数によるライト/ダークテーマ対応) |
| `static/quiz.js` | クイズ UI のロジック (SSE 接続・回答送信・単語保存) |
| `validate.py` | YAML configuration consistency checker |
| `tests/test_mcp_client.py` | MCPクライアントによるサーバー動作確認（インプロセス接続でツール・リソース・プロンプト一覧を出力） |
| `tests/conftest.py` | pytest 共通設定。DB パスを一時ファイルに差し替え、quiz_server の副作用を無効化 |
| `tests/test_database.py` | DB 操作の単体テスト（スキーマ作成、クイズ CRUD、pending/results 取得、`save_words_db`） |
| `tests/test_status_transitions.py` | 単語ステータス遷移の単体テスト（`_save_word` / `_process_answer` 全6パターン） |
| `tests/test_template.py` | テンプレート解決の単体テスト（変数解決、レンダリング、エラーケース） |
| `tests/test_config.py` | ConfigStore の単体テスト（reload、update、format_language_codes） |
| `tests/test_migration.py` | マイグレーションシステムの単体テスト（バージョン管理、冪等性、migration_001） |
| `tests/test_free_quiz.py` | 自由回答クイズの単体テスト（DB保存・提出・採点・結果取得・混在クイズ） |
| `tests/test_story_topics.py` | 話題管理の単体テスト（保存・取得・言語フィルタ・件数制限） |

`main.py` creates the `mcp` instance, then `tools.py` imports it via side-effect import to register tool functions. `init_db()` はモジュールレベルで呼ばれるため、どの起動経路でも確実にDB初期化される。`main()` 内で `TRANSPORT` 環境変数を参照し、`http` なら統合 ASGI アプリで起動、未設定または `stdio` なら従来どおり stdio + デーモンスレッドのクイズWebサーバーで起動する。ヘルスチェック (`GET /health`) はモジュールレベルの `@mcp.custom_route` で登録されるため両モードで利用可能。

**HTTP モード (`TRANSPORT=http`)**: `mcp.http_app(path="/mcp")` で MCP の Starlette アプリを取得し、クイズ UI ルート（`quiz_server.py` のハンドラ）と組み合わせた統合 Starlette アプリを uvicorn で直接起動する。`combined_lifespan` で MCP セッションマネージャーの初期化とクイズキュー (`asyncio.Queue`) の初期化を統合する。単一ポートで `/` (クイズ UI), `/mcp` (MCP 接続), `/health` (ヘルスチェック), `/events` (SSE), `/api/*` (クイズ API), `/static/` (静的ファイル) を提供する。`tools.py` では HTTP モード時に `get_active_port()` の代わりに `TRANSPORT` 環境変数で分岐し、URL 表示を切り替える。

**OAuth 認証 (HTTP モード)**: 環境変数 `GOOGLE_CLIENT_ID` と `GOOGLE_CLIENT_SECRET` が設定されている場合、FastMCP の `GoogleProvider` で `/mcp` エンドポイントを OAuth 2.1 で保護する。`/health` やクイズ UI は認証不要。環境変数 `SERVICE_URL` で OAuth の `base_url` を指定する（デフォルト: `http://localhost:8080`）。環境変数が未設定の場合は認証なしで動作する（ローカル開発時）。

**メールアドレス allowlist**: 環境変数 `ALLOWED_EMAILS` にカンマ区切りで Google アカウントのメールアドレスを指定すると、`EmailAllowlistGoogleTokenVerifier` (`main.py`) が `GoogleProvider` の token verifier を差し替え、許可リストに含まれないアカウントの認証を拒否する。`required_scopes` に `userinfo.email` を加えて email を必ず取得する。`ALLOWED_EMAILS` が未設定の場合は警告ログを出して全 Google アカウントを許可する（後方互換）。

**クイズサーバーのポート管理**: `start_quiz_server()` はポートプール (デフォルト: 8765–8767) から利用可能なポートを順に試行する。ポートが占有されている場合は古いプロセスを `netstat`+`taskkill` (Windows) / `lsof`+`kill` (Unix) で自動停止してリトライする。プロセス終了時は `atexit` + `uvicorn.Server.should_exit` でグレースフルシャットダウンする。実際に使用されたポートは `get_active_port()` で取得できる。

**注意**: `fastmcp run` にファイルパスを渡すと `mcp` インスタンスが二重生成されツールが0になる。Claude Desktop では `uv run dynamic_prompt`（エントリーポイント直接呼び出し）を使うこと。詳細は `CLAUDE_DESKTOPでの使い方.md` を参照。

### Quiz Web UI architecture

**選択式クイズ (MC):**
```
Claude (AI) がクイズを生成
  → MCP tool `send_quiz` を呼び出し
  → DB保存 + SSE でブラウザにプッシュ
  → ブラウザ (localhost:8765) でクイズ表示（ラジオボタン）
  → ユーザーが回答・送信
  → Web server が即時採点して結果を DB に保存
  → MCP tool `get_quiz_results` で結果取得
```

**自由回答クイズ (Free-answer):**
```
Claude (AI) がクイズを生成
  → MCP tool `send_free_quiz` を呼び出し
  → DB保存 + SSE でブラウザにプッシュ
  → ブラウザでクイズ表示（テキストエリア入力）
  → ユーザーがテキストで回答・送信
  → Web server がテキスト回答を DB に保存（未採点）
  → MCP tool `get_unscored_quizzes` で未採点回答を取得
  → AI がユーザーの回答を model_answer と比較して採点
  → MCP tool `score_free_answers` で採点結果を DB に保存
```

- **Web server**: Starlette + uvicorn。デーモンスレッドで MCP サーバーと同時起動
- **リアルタイム通知**: SSE (Server-Sent Events) でクイズデータをブラウザにプッシュ
- **フォールバック**: ページ読み込み時に `/api/pending` で未回答クイズを取得
- **スレッド間通信**: `asyncio.Queue` + `asyncio.run_coroutine_threadsafe()` で MCP ツール(同期) → SSE(非同期) にデータを安全にプッシュ
- **単語入力**: ブラウザの入力フォームから `/api/save_words` へ POST → DB に直接保存。クイズ受信時に言語コードが自動入力される。保存された単語は次回の `get_words` MCP ツール呼び出し時に AI が取得する（非同期連携）

**Web server endpoints:**

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | quiz.html 配信 |
| GET | `/events` | SSE (クイズデータプッシュ) |
| GET | `/api/pending` | 未回答クイズ取得 |
| POST | `/api/submit` | 回答送信・採点 |
| POST | `/api/save_words` | UI からの単語保存 (lang, words, context) |

### Configuration-driven design

Behavior is driven by YAML files (置き場所はローカル `src/dynamic_prompt/prompts/` または GCS バケット — 後述):

- `user_config.yaml` — ユーザー設定 (`native_language`, `memory_test_period_hours`)
- `app_config.yaml` — アプリ設定 (`vocab_get_limit`, `quiz_server_port`, `quiz_server_port_pool_size`)
- `instructions.yaml` — instruction templates with declared variable scopes
- `languages/*.yaml` — per-language profiles (label, aliases, user_level, teaching_guide)
- `languages/_default.yaml` — fallback for unrecognized languages

**外部ストレージ対応 (`PROMPTS_URI`)**: `config_source.py` の `ConfigSource` 抽象でローカルファイルシステムと GCS バケットの両方に対応する。

| `PROMPTS_URI` | 動作 |
|---------------|------|
| 未設定（既定） | `src/dynamic_prompt/prompts/` を `LocalConfigSource` で読み込む（後方互換） |
| `/abs/path` | 指定パスを `LocalConfigSource` で読み込む |
| `gs://bucket/prefix` | GCS バケットの prefix 配下を `GCSConfigSource` (google-cloud-storage SDK) で読み込む |

Cloud Run では `PROMPTS_URI=gs://${project_id}-dp-data/prompts` を設定し、YAML 群を GCS に置く。アップロードは `just upload-prompts` (`gsutil rsync`) で行う。`validate.py` はローカル YAML 専用で、GCS にアップロードする前のチェックに使う。

**TTL キャッシュ**: `ConfigStore` はアクセスごとに TTL を確認し、期限切れなら裏で再読み込みする。`CONFIG_TTL_SECONDS` 環境変数で制御（既定 60 秒、0 以下で自動 refresh 無効）。再読み込みが例外で失敗した場合は古いキャッシュを返し、サーバを停止させない。GCS 経由でも毎リクエストでネットワークを叩かない設計。

**ConfigStore (mutable wrapper + TTL cache)**: `config.py` の `ConfigStore` クラスが frozen dataclass インスタンスへの mutable wrapper として機能する。dataclass 自体は `frozen=True` のまま（値オブジェクトの安全性を維持）、`ConfigStore` の属性 (`user_config`, `app_config`, `languages`, `instructions`) は `@property` で公開され、アクセス時に TTL を確認する。

- `config_store.reload()` — TTL を無視して即時再読み込み
- `config_store.update_user_config(**kwargs)` — 指定フィールドだけ変更した新しい UserConfig に差し替え。次の自動 refresh または `reload()` で破棄される一時的な上書き
- `config_store.update_app_config(**kwargs)` — 同上 (AppConfig)
- `config_store.format_language_codes()` — 登録言語コードのカンマ区切り文字列

MCP ツール `reload_config` (`tools.py`) を呼ぶと、Claude 側から `reload()` を発火できる（外部 YAML を編集 → 即時反映の用途）。

すべてのモジュール (`tools.py`, `main.py`) は `config_store` シングルトン経由で設定にアクセスする。旧モジュールレベル定数 (`USER_CONFIG`, `APP_CONFIG`, `LANGUAGES`, `INSTRUCTIONS`) は廃止済み。

### Template rendering

Instructions use Python `str.format_map()` with `{variable}` placeholders. Each instruction declares which variable groups it needs (`user_config`, `language`). Resolvers in `_VAR_RESOLVERS` (`tools.py`) map group names to functions that pull values from `config_store.user_config` or `session.lang` (Language dataclass).

### Session state

`_Session` (`session.py`) holds the current target language. Tools like `get_instruction` require a language to be set first via `determine_language`.

### Repository layer & Database

データアクセスは `repo/` のリポジトリ層で抽象化されている (Phase 1 で導入)。呼び出し側 (`tools.py`, `quiz_server.py`, `main.py`) は `get_repo()` でシングルトン `RepoBundle` (`vocab` / `quiz` / `topic`) を取得し、具体的なバックエンドには依存しない。`main.py` がモジュールレベルで `init_repo(DATA_BACKEND)` を呼び、起動時に初期化する。現状の実装は SQLite のみ (`repo/sqlite_repo.py`)。`database.py` は旧 API を re-export する薄い shim として残っている (Phase 2-5 で削除予定)。

SQLite with WAL journaling (`vocab.db`). `DB_PATH` は環境変数 `DB_PATH` で上書き可能（デフォルトは `src/dynamic_prompt/vocab.db`）。`init_db()` (= `vocab.init()`) がサーバー起動時にスキーマ作成・マイグレーションを1回だけ実行する。ツール呼び出しごとにスレッド安全のため新しい接続を返す (`_connect_db`)。

**マイグレーションシステム**: `schema_version` テーブルでバージョンを管理する。`_MIGRATIONS` リストに `(version, description, func)` タプルを追加するだけで新しいマイグレーションを定義できる。`_migrate()` は未適用のバージョンのみ順番に実行し、冪等性を保証する。新しいマイグレーション追加手順:
1. `_migration_NNN(db)` 関数を定義
2. `_MIGRATIONS` リストの末尾に追加（バージョン番号は連番）

**`unknown_words` table:**

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER PK | Auto-increment |
| `lang` | TEXT NOT NULL | Language code |
| `word` | TEXT NOT NULL | Word (lowercase), UNIQUE with lang |
| `context` | TEXT | Sentence where it appeared |
| `status` | TEXT NOT NULL DEFAULT 'unlearned' | `unlearned`, `wrong`, `memory_test` |
| `reviewed_at` | TEXT | Timestamp when moved to `memory_test` |
| `created_at` | TEXT NOT NULL | Creation timestamp |

**`quiz_sessions` table:**

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER PK | Auto-increment |
| `lang` | TEXT NOT NULL | Language code |
| `title` | TEXT NOT NULL | Quiz title |
| `created_at` | TEXT NOT NULL | Creation timestamp |
| `submitted_at` | TEXT | Submission timestamp (NULL = pending) |
| `scored_at` | TEXT | AI が自由回答を採点した日時 (NULL = 未採点 or MC のみ) |

**`quiz_questions` table:**

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER PK | Auto-increment |
| `session_id` | INTEGER FK | References quiz_sessions(id) |
| `question_index` | INTEGER NOT NULL | 0-based question order, UNIQUE with session_id |
| `question_text` | TEXT NOT NULL | Question text |
| `choices` | TEXT NOT NULL DEFAULT '[]' | JSON array of choice strings (MC 用。free では `'[]'`) |
| `correct_index` | INTEGER NOT NULL DEFAULT 0 | 0-based index of correct choice (MC 用。free では 0) |
| `user_answer` | INTEGER | User's selected index for MC (NULL = unanswered) |
| `is_correct` | INTEGER | 1/0/NULL (MC は即時採点、free は AI 採点後に設定) |
| `question_type` | TEXT NOT NULL DEFAULT 'mc' | `'mc'` (選択式) or `'free'` (自由回答) |
| `model_answer` | TEXT | 自由回答の模範解答 (MC では NULL) |
| `user_answer_text` | TEXT | 自由回答のユーザー回答テキスト (MC では NULL) |

**`story_topics` table:**

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER PK | Auto-increment |
| `lang` | TEXT NOT NULL | Language code |
| `topic` | TEXT NOT NULL | 話題の短いラベル (例: "weekend picnic") |
| `summary` | TEXT NOT NULL DEFAULT '' | 物語のあらすじ (1文) |
| `created_at` | TEXT NOT NULL | Creation timestamp |

**`schema_version` table:**

| Column | Type | Description |
|--------|------|-------------|
| `version` | INTEGER PK | マイグレーションバージョン番号 |
| `description` | TEXT NOT NULL | マイグレーションの説明 |
| `applied_at` | TEXT NOT NULL | 適用日時 |

### Word status levels

Words progress through three statuses:

```
save → [unlearned]
         ├─ correct → DELETE
         └─ wrong   → [wrong]
                       ├─ correct → [memory_test] (hidden for configured period)
                       └─ wrong   → stays [wrong]
                                     ├─ correct (after period) → DELETE
                                     └─ wrong (after period)   → [wrong]
```

- `memory_test_period_hours` in `user_config.yaml` controls how long words stay hidden (default: 24h)

### Vocabulary tools

| Tool | Parameters | Description |
|------|-----------|-------------|
| `get_words` | — | Retrieve random words available for review. Count configured by `vocab_get_limit` in `app_config.yaml`. |
| `save_words` | `words`, `context` | Save multiple words (comma-separated). Optional shared context. |
| `answer_words` | `correct`, `incorrect` | Record quiz results. Two comma-separated lists for correct/incorrect words. |

### Quiz tools

| Tool | Parameters | Description |
|------|-----------|-------------|
| `send_quiz` | `title`, `questions` | Send a multiple-choice quiz (JSON) to the web UI. Opens at `http://127.0.0.1:{port}`. |
| `send_free_quiz` | `title`, `questions` | Send a free-answer quiz (JSON) to the web UI. Questions require `question` and `model_answer`. |
| `get_quiz_results` | `limit` | Retrieve recent completed quiz scores and per-question details (MC + free). |
| `get_unscored_quizzes` | `limit` | Retrieve submitted but unscored free-answer quizzes for AI grading. |
| `score_free_answers` | `session_id`, `scores` | Record AI grading for free-answer quiz responses (JSON array of `question_index` + `is_correct`). |

### Story topic tools

話題の多様性を確保するために、物語の話題を DB に記録・参照する。AI が story instruction に従って自動的に使用する。

| Tool | Parameters | Description |
|------|-----------|-------------|
| `get_past_topics` | `limit` | 過去の話題を新しい順に取得。物語生成前に呼んで話題の重複を避ける。 |
| `save_story_topic` | `topic`, `summary` | 物語生成後に話題を保存。`topic` は短いラベル、`summary` は任意のあらすじ。 |

## Adding a new language

1. Create `src/dynamic_prompt/prompts/languages/<code>.yaml` following the structure of `en.yaml`/`fr.yaml`
2. Run the validator to confirm fields match expectations

## Adding a new instruction

1. Add entry to `instructions.yaml` with `requires_language`, `variables` (dict of group names → field lists), and `template`
2. Ensure all `{placeholders}` in the template correspond to fields in the relevant dataclasses
3. **Do not use literal `{` or `}` in templates** — `str.format_map()` will interpret them as placeholders. Use `{{` and `}}` to escape if needed
4. Run the validator

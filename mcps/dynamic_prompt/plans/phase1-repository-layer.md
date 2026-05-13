# Phase 1: リポジトリ層の導入

## 目的

データアクセスをインタフェースで抽象化し、後続のFirestore移行リスクを下げる。**既存挙動は一切変えない**。SQLite実装のままで、呼び出し側がリポジトリインタフェース経由になるだけ。

## 完了基準

- 既存のpytest全テストがそのままパス
- `tools.py` / `quiz_server.py` / `main.py` から `database.xxx()` の直接呼び出しが消える
- `database.py` は薄いshim or 廃止
- アプリ全体（stdio/HTTPモード両方）が起動し、MCPツール `get_words`, `save_words`, `send_quiz` 等が今までどおり動く

## ステップ

### 1.1 リポジトリインタフェース定義

新規ファイル: `src/dynamic_prompt/repo/__init__.py`, `src/dynamic_prompt/repo/base.py`

`base.py` に Protocol で以下を定義:

```python
class VocabRepo(Protocol):
    def init(self) -> None: ...
    def save_words(self, lang: str, words: list[str], context: str) -> int: ...
    def get_review_pool(self, lang: str, limit: int, memory_test_cutoff: str) -> list[dict]: ...
    def update_status(self, lang: str, word: str, new_status: str, reviewed_at: str | None) -> None: ...
    def delete_word(self, lang: str, word: str) -> None: ...

class QuizRepo(Protocol):
    def create_mc_session(self, lang: str, title: str, questions: list[dict]) -> int: ...
    def create_free_session(self, lang: str, title: str, questions: list[dict]) -> int: ...
    def get_pending(self) -> list[dict]: ...
    def submit_mc_answers(self, session_id: int, answers: dict[int, int]) -> None: ...
    def submit_free_answers(self, session_id: int, answers: dict[int, str]) -> None: ...
    def score_free_answers(self, session_id: int, scores: list[dict]) -> None: ...
    def get_recent_results(self, limit: int) -> list[dict]: ...
    def get_unscored(self, limit: int) -> list[dict]: ...

class TopicRepo(Protocol):
    def save_topic(self, lang: str, topic: str, summary: str) -> int: ...
    def list_recent(self, lang: str, limit: int) -> list[dict]: ...

class RepoBundle:
    vocab: VocabRepo
    quiz: QuizRepo
    topic: TopicRepo
```

正確なシグネチャは既存 `database.py` の関数を参照して合わせる（戻り値形式を変えない）。

### 1.2 SQLite実装の移植

新規ファイル: `src/dynamic_prompt/repo/sqlite_repo.py`

既存 `database.py` の以下を移植:
- `_connect_db`, `_migrate`, `_MIGRATIONS`, `init_db`
- `save_words_db`, `get_words_db`, `update_word_status`, `delete_word`
- `create_quiz_session`, `add_quiz_questions`, `get_pending_quizzes`, `submit_quiz_answers`, `get_quiz_results`, `get_unscored_free_quizzes`, `score_free_answers_db`
- `save_story_topic_db`, `get_past_topics_db`

クラス `SqliteVocabRepo`, `SqliteQuizRepo`, `SqliteTopicRepo` にまとめ、 `RepoBundle` 形式で公開:

```python
def build_sqlite_repo(db_path: Path | None = None) -> RepoBundle:
    ...
```

### 1.3 シングルトン初期化

`src/dynamic_prompt/repo/__init__.py`:

```python
_repo: RepoBundle | None = None

def init_repo(backend: str = "sqlite") -> RepoBundle:
    global _repo
    if backend == "sqlite":
        _repo = build_sqlite_repo()
    else:
        raise ValueError(f"unknown backend: {backend}")
    _repo.vocab.init()  # マイグレーション等
    return _repo

def get_repo() -> RepoBundle:
    if _repo is None:
        raise RuntimeError("repo not initialized; call init_repo() first")
    return _repo
```

### 1.4 呼び出し側の修正

- `database.py`: 中身を空にして、後方互換用に旧API名を `get_repo().vocab.xxx(...)` 等にforwardする薄いshimだけ残す（移行期間用）。最終的にPhase 2-5で削除予定。
- `tools.py`: `from dynamic_prompt.repo import get_repo` を追加し、`database.save_words_db(...)` → `get_repo().vocab.save_words(...)` のように置換。
- `quiz_server.py`: 同様に置換。
- `main.py`: モジュールトップの `init_db()` 呼び出しを `init_repo(os.environ.get("DATA_BACKEND", "sqlite"))` に変更。

### 1.5 テストの調整

- `tests/conftest.py`: 既存の `DB_PATH` を一時ファイルにする仕掛けはそのままでOK。ただし `init_repo("sqlite")` を呼ぶように修正。
- `tests/test_database.py`: ファイル名は維持しつつ、内部は `get_repo().vocab.xxx` を呼ぶように書き換え。または `test_sqlite_repo.py` にリネーム。
- 既存の他テスト（`test_status_transitions.py`, `test_free_quiz.py`, `test_story_topics.py`, `test_migration.py` 等）は呼び出し経路を更新するだけで通るはず。

### 1.6 動作確認

```powershell
cd c:\CodeRoot\my_ai_tools\mcps\dynamic_prompt
uv run --project . pytest src/dynamic_prompt/tests/ -v
```

`pytest -v` 全緑を確認してから次フェーズへ。

stdioモード（`uv run dynamic_prompt`）とHTTPモード（`TRANSPORT=http uv run dynamic_prompt`）の両方で起動エラーが出ないことも確認。

## ロールバック

このフェーズはコミット単位で逆戻り可能。本番への影響なし。

"""SQLite 実装のリポジトリ層。

責務ごとにサブモジュールへ分割している:

- ``connection`` — ``DB_PATH`` と接続ファクトリ ``_connect_db``
- ``schema``     — テーブル定義・マイグレーション・``init_db``
- ``vocab``      — 単語/復習プール/ステータス遷移と ``SqliteVocabRepo``
- ``quiz``       — クイズ (MC + free) と ``SqliteQuizRepo``
- ``topic``      — 物語の話題と ``SqliteTopicRepo``

各サブモジュールのモジュールレベル関数が SQL の唯一の出所で、``Sqlite*Repo`` クラスは
その薄い OO ラッパー。後方互換のため ``dynamic_prompt.database`` がここの名前を
re-export する。
"""

from pathlib import Path

from dynamic_prompt.repo.base import RepoBundle
from dynamic_prompt.repo.sqlite_repo import connection
from dynamic_prompt.repo.sqlite_repo.connection import DB_PATH, _connect_db
from dynamic_prompt.repo.sqlite_repo.quiz import (
    SqliteQuizRepo,
    get_pending_quiz,
    get_quiz_results_db,
    get_unscored_sessions_db,
    save_quiz_session,
    score_free_answers_db,
    submit_quiz_answers,
)
from dynamic_prompt.repo.sqlite_repo.schema import (
    _MIGRATIONS,
    _column_exists,
    _get_current_version,
    _migrate,
    _table_exists,
    init_db,
)
from dynamic_prompt.repo.sqlite_repo.topic import (
    SqliteTopicRepo,
    get_past_topics_db,
    save_story_topic_db,
)
from dynamic_prompt.repo.sqlite_repo.vocab import (
    STATUS_MEMORY_TEST,
    STATUS_UNLEARNED,
    STATUS_WRONG,
    SqliteVocabRepo,
    _process_answer,
    _save_word,
    get_review_pool_db,
    process_answers_db,
    save_words_db,
)

__all__ = [
    "DB_PATH",
    "STATUS_MEMORY_TEST",
    "STATUS_UNLEARNED",
    "STATUS_WRONG",
    "_MIGRATIONS",
    "_column_exists",
    "_connect_db",
    "_get_current_version",
    "_migrate",
    "_process_answer",
    "_save_word",
    "_table_exists",
    "build_sqlite_repo",
    "get_past_topics_db",
    "get_pending_quiz",
    "get_quiz_results_db",
    "get_review_pool_db",
    "get_unscored_sessions_db",
    "init_db",
    "process_answers_db",
    "save_quiz_session",
    "save_story_topic_db",
    "save_words_db",
    "score_free_answers_db",
    "submit_quiz_answers",
]


def build_sqlite_repo(db_path: Path | None = None) -> RepoBundle:
    """SQLite バックエンドの ``RepoBundle`` を構築する。

    ``db_path`` を渡すと ``connection.DB_PATH`` を上書きする (全モジュール関数が
    同じ DB を参照するため)。``None`` の場合は現在の ``DB_PATH``
    (環境変数 / テストパッチ由来) をそのまま使う。
    """
    if db_path is not None:
        connection.DB_PATH = db_path
    return RepoBundle(
        vocab=SqliteVocabRepo(),
        quiz=SqliteQuizRepo(),
        topic=SqliteTopicRepo(),
    )

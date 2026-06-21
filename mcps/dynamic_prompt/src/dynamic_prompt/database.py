"""後方互換用の薄い shim。

実装は ``dynamic_prompt.repo.sqlite_repo`` に移動した。新規コードは
``dynamic_prompt.repo.get_repo()`` 経由でリポジトリにアクセスすること。このモジュールは
既存テスト等の旧 import を壊さないために旧 API 名を re-export しているだけで、
Phase 2-5 で削除予定。
"""

from dynamic_prompt.repo.sqlite_repo import (  # noqa: F401
    DB_PATH,
    STATUS_MEMORY_TEST,
    STATUS_UNLEARNED,
    STATUS_WRONG,
    _MIGRATIONS,
    _column_exists,
    _connect_db,
    _get_current_version,
    _migrate,
    _process_answer,
    _save_word,
    _table_exists,
    get_past_topics_db,
    get_pending_quiz,
    get_quiz_results_db,
    get_review_pool_db,
    get_unscored_sessions_db,
    init_db,
    process_answers_db,
    save_quiz_session,
    save_story_topic_db,
    save_words_db,
    score_free_answers_db,
    submit_quiz_answers,
)

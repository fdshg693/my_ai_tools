"""単語・復習プールの SQLite アクセスとステータス遷移。"""

import sqlite3

from dynamic_prompt.repo.sqlite_repo.connection import _connect_db
from dynamic_prompt.repo.sqlite_repo.schema import init_db

STATUS_UNLEARNED = "unlearned"
STATUS_WRONG = "wrong"
STATUS_MEMORY_TEST = "memory_test"


def _save_word(db: sqlite3.Connection, lang: str, word: str, context: str) -> str:
    """単語を保存する。既存ステータスは保持する。"""
    w = word.strip().lower()
    if not w:
        return ""
    ctx = context.strip() or None
    db.execute(
        """INSERT INTO unknown_words (lang, word, context, status)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(lang, word) DO UPDATE SET context = COALESCE(excluded.context, context)""",
        (lang, w, ctx, STATUS_UNLEARNED),
    )
    return w


def _process_answer(db: sqlite3.Connection, lang: str, word: str, is_correct: bool) -> str:
    """ステータス遷移を適用し、結果メッセージを返す。"""
    w = word.strip().lower()
    row = db.execute(
        "SELECT status FROM unknown_words WHERE lang = ? AND word = ?",
        (lang, w),
    ).fetchone()
    if row is None:
        return f"'{word.strip()}': not found"

    status = row["status"]

    if is_correct:
        if status == STATUS_UNLEARNED:
            db.execute(
                "DELETE FROM unknown_words WHERE lang = ? AND word = ?", (lang, w)
            )
            return f"'{word.strip()}': correct, removed"
        if status == STATUS_WRONG:
            db.execute(
                "UPDATE unknown_words SET status = ?, reviewed_at = datetime('now') WHERE lang = ? AND word = ?",
                (STATUS_MEMORY_TEST, lang, w),
            )
            return f"'{word.strip()}': correct, moved to review"
        # memory_test
        db.execute("DELETE FROM unknown_words WHERE lang = ? AND word = ?", (lang, w))
        return f"'{word.strip()}': correct, fully learned"

    # incorrect
    if status == STATUS_UNLEARNED:
        db.execute(
            "UPDATE unknown_words SET status = ? WHERE lang = ? AND word = ?",
            (STATUS_WRONG, lang, w),
        )
        return f"'{word.strip()}': incorrect, marked difficult"
    if status == STATUS_WRONG:
        return f"'{word.strip()}': incorrect, stays difficult"
    # memory_test
    db.execute(
        "UPDATE unknown_words SET status = ?, reviewed_at = NULL WHERE lang = ? AND word = ?",
        (STATUS_WRONG, lang, w),
    )
    return f"'{word.strip()}': incorrect, back to difficult"


def save_words_db(lang: str, words: list[str], context: str = "") -> list[str]:
    """単語をDBに保存し、保存された単語のリストを返す。

    既存の単語はコンテキストのみ更新し、ステータスは保持する。
    """
    saved: list[str] = []
    with _connect_db() as db:
        for word in words:
            w = _save_word(db, lang, word, context)
            if w:
                saved.append(w)
    return saved


def get_review_pool_db(lang: str, limit: int, memory_test_period_hours: int) -> list[dict]:
    """復習対象の単語をランダムに返す。

    ``memory_test`` のうち、``reviewed_at`` から ``memory_test_period_hours`` 時間
    経過したものだけを含める。各要素は ``word`` / ``context`` / ``status`` を持つ。
    """
    with _connect_db() as db:
        rows = db.execute(
            """SELECT word, context, status FROM unknown_words
               WHERE lang = ?
                 AND (
                   status IN (?, ?)
                   OR (status = ?
                       AND datetime(reviewed_at, '+' || ? || ' hours') <= datetime('now'))
                 )
               ORDER BY RANDOM()
               LIMIT ?""",
            (
                lang,
                STATUS_UNLEARNED,
                STATUS_WRONG,
                STATUS_MEMORY_TEST,
                str(memory_test_period_hours),
                limit,
            ),
        ).fetchall()
    return [
        {"word": r["word"], "context": r["context"], "status": r["status"]}
        for r in rows
    ]


def process_answers_db(lang: str, correct: list[str], incorrect: list[str]) -> list[str]:
    """正答・誤答の単語にステータス遷移を適用し、結果メッセージのリストを返す。"""
    results: list[str] = []
    with _connect_db() as db:
        for w in correct:
            results.append(_process_answer(db, lang, w, True))
        for w in incorrect:
            results.append(_process_answer(db, lang, w, False))
    return results


class SqliteVocabRepo:
    """単語・復習プールの SQLite リポジトリ。"""

    def init(self) -> None:
        init_db()

    def save_words(self, lang: str, words: list[str], context: str = "") -> list[str]:
        return save_words_db(lang, words, context)

    def get_review_pool(
        self, lang: str, limit: int, memory_test_period_hours: int
    ) -> list[dict]:
        return get_review_pool_db(lang, limit, memory_test_period_hours)

    def process_answers(
        self, lang: str, correct: list[str], incorrect: list[str]
    ) -> list[str]:
        return process_answers_db(lang, correct, incorrect)

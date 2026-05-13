"""単語ステータス遷移の単体テスト — _save_word / _process_answer 全パターン。"""

from dynamic_prompt.database import (
    STATUS_MEMORY_TEST,
    STATUS_UNLEARNED,
    STATUS_WRONG,
    _connect_db,
)
from dynamic_prompt.tools import _process_answer, _save_word


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_status(db, lang: str, word: str) -> str | None:
    row = db.execute(
        "SELECT status FROM unknown_words WHERE lang = ? AND word = ?",
        (lang, word),
    ).fetchone()
    return row[0] if row else None


def _word_exists(db, lang: str, word: str) -> bool:
    return db.execute(
        "SELECT 1 FROM unknown_words WHERE lang = ? AND word = ?",
        (lang, word),
    ).fetchone() is not None


def _insert_word(db, lang: str, word: str, status: str):
    db.execute(
        "INSERT INTO unknown_words (lang, word, status) VALUES (?, ?, ?)",
        (lang, word, status),
    )
    db.commit()


# ---------------------------------------------------------------------------
# _save_word
# ---------------------------------------------------------------------------


class TestSaveWord:
    def test_new_word_saved_as_unlearned(self):
        with _connect_db() as db:
            _save_word(db, "en", "apple", "I ate an apple")
            assert _get_status(db, "en", "apple") == STATUS_UNLEARNED

    def test_saves_context(self):
        with _connect_db() as db:
            _save_word(db, "en", "banana", "A yellow banana")
            row = db.execute(
                "SELECT context FROM unknown_words WHERE lang = ? AND word = ?",
                ("en", "banana"),
            ).fetchone()
            assert row[0] == "A yellow banana"

    def test_word_is_lowercased(self):
        with _connect_db() as db:
            _save_word(db, "en", "Apple", "")
            assert _word_exists(db, "en", "apple")
            assert not _word_exists(db, "en", "Apple")

    def test_word_is_stripped(self):
        with _connect_db() as db:
            result = _save_word(db, "en", "  banana  ", "")
            assert result == "banana"
            assert _word_exists(db, "en", "banana")

    def test_empty_word_returns_empty(self):
        with _connect_db() as db:
            result = _save_word(db, "en", "  ", "")
            assert result == ""

    def test_existing_word_updates_context(self):
        with _connect_db() as db:
            _save_word(db, "en", "cat", "The cat sat")
            _save_word(db, "en", "cat", "A black cat")
            row = db.execute(
                "SELECT context FROM unknown_words WHERE lang = ? AND word = ?",
                ("en", "cat"),
            ).fetchone()
            assert row[0] == "A black cat"

    def test_existing_word_preserves_status(self):
        with _connect_db() as db:
            _save_word(db, "en", "dog", "")
            db.execute(
                "UPDATE unknown_words SET status = ? WHERE lang = ? AND word = ?",
                (STATUS_WRONG, "en", "dog"),
            )
            db.commit()
            _save_word(db, "en", "dog", "New context")
            assert _get_status(db, "en", "dog") == STATUS_WRONG

    def test_empty_context_preserves_existing(self):
        """空コンテキストで再保存すると既存コンテキストが保持される。"""
        with _connect_db() as db:
            _save_word(db, "en", "fish", "In the sea")
            _save_word(db, "en", "fish", "")
            row = db.execute(
                "SELECT context FROM unknown_words WHERE lang = ? AND word = ?",
                ("en", "fish"),
            ).fetchone()
            assert row[0] == "In the sea"


# ---------------------------------------------------------------------------
# _process_answer — ステータス遷移マトリックス
# ---------------------------------------------------------------------------


class TestProcessAnswer:
    """
    遷移図:
      unlearned + correct → DELETE
      unlearned + wrong   → wrong
      wrong     + correct → memory_test
      wrong     + wrong   → stays wrong
      memory_test + correct → DELETE
      memory_test + wrong   → wrong
    """

    # --- unlearned ---

    def test_unlearned_correct_deletes(self):
        with _connect_db() as db:
            _insert_word(db, "en", "easy", STATUS_UNLEARNED)
            result = _process_answer(db, "en", "easy", True)
            assert "removed" in result
            assert not _word_exists(db, "en", "easy")

    def test_unlearned_wrong_to_wrong(self):
        with _connect_db() as db:
            _insert_word(db, "en", "hard", STATUS_UNLEARNED)
            result = _process_answer(db, "en", "hard", False)
            assert "difficult" in result
            assert _get_status(db, "en", "hard") == STATUS_WRONG

    # --- wrong ---

    def test_wrong_correct_to_memory_test(self):
        with _connect_db() as db:
            _insert_word(db, "en", "medium", STATUS_WRONG)
            result = _process_answer(db, "en", "medium", True)
            assert "review" in result
            assert _get_status(db, "en", "medium") == STATUS_MEMORY_TEST

    def test_wrong_correct_sets_reviewed_at(self):
        with _connect_db() as db:
            _insert_word(db, "en", "timed", STATUS_WRONG)
            _process_answer(db, "en", "timed", True)
            row = db.execute(
                "SELECT reviewed_at FROM unknown_words WHERE lang = ? AND word = ?",
                ("en", "timed"),
            ).fetchone()
            assert row[0] is not None

    def test_wrong_wrong_stays_wrong(self):
        with _connect_db() as db:
            _insert_word(db, "en", "tough", STATUS_WRONG)
            result = _process_answer(db, "en", "tough", False)
            assert "stays difficult" in result
            assert _get_status(db, "en", "tough") == STATUS_WRONG

    # --- memory_test ---

    def test_memory_test_correct_deletes(self):
        with _connect_db() as db:
            _insert_word(db, "en", "learned", STATUS_MEMORY_TEST)
            result = _process_answer(db, "en", "learned", True)
            assert "fully learned" in result
            assert not _word_exists(db, "en", "learned")

    def test_memory_test_wrong_to_wrong(self):
        with _connect_db() as db:
            _insert_word(db, "en", "forgot", STATUS_MEMORY_TEST)
            result = _process_answer(db, "en", "forgot", False)
            assert "back to difficult" in result
            assert _get_status(db, "en", "forgot") == STATUS_WRONG

    def test_memory_test_wrong_clears_reviewed_at(self):
        with _connect_db() as db:
            _insert_word(db, "en", "reset", STATUS_MEMORY_TEST)
            db.execute(
                "UPDATE unknown_words SET reviewed_at = datetime('now') WHERE word = 'reset'"
            )
            db.commit()
            _process_answer(db, "en", "reset", False)
            row = db.execute(
                "SELECT reviewed_at FROM unknown_words WHERE lang = ? AND word = ?",
                ("en", "reset"),
            ).fetchone()
            assert row[0] is None

    # --- edge case ---

    def test_not_found_word(self):
        with _connect_db() as db:
            result = _process_answer(db, "en", "nonexistent", True)
            assert "not found" in result

    def test_handles_leading_trailing_spaces(self):
        with _connect_db() as db:
            _insert_word(db, "en", "spaced", STATUS_UNLEARNED)
            result = _process_answer(db, "en", "  spaced  ", True)
            assert "removed" in result

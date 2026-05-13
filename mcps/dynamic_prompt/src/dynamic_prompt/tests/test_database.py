"""database.py の単体テスト — スキーマ作成・クイズ CRUD。"""

import json

from dynamic_prompt.database import (
    _connect_db,
    get_pending_quiz,
    get_quiz_results_db,
    save_quiz_session,
    save_words_db,
    submit_quiz_answers,
)


# ---------------------------------------------------------------------------
# スキーマ作成
# ---------------------------------------------------------------------------


class TestInitDb:
    def test_creates_unknown_words_table(self):
        with _connect_db() as db:
            cols = db.execute("PRAGMA table_info(unknown_words)").fetchall()
            col_names = [c[1] for c in cols]
            for expected in ("id", "lang", "word", "context", "status", "reviewed_at", "created_at"):
                assert expected in col_names

    def test_creates_quiz_sessions_table(self):
        with _connect_db() as db:
            cols = db.execute("PRAGMA table_info(quiz_sessions)").fetchall()
            col_names = [c[1] for c in cols]
            for expected in ("id", "lang", "title", "created_at", "submitted_at"):
                assert expected in col_names

    def test_creates_quiz_questions_table(self):
        with _connect_db() as db:
            cols = db.execute("PRAGMA table_info(quiz_questions)").fetchall()
            col_names = [c[1] for c in cols]
            for expected in (
                "id", "session_id", "question_index", "question_text",
                "choices", "correct_index", "user_answer", "is_correct",
            ):
                assert expected in col_names

    def test_unknown_words_unique_constraint(self):
        """同じ (lang, word) の重複挿入が制約違反になること。"""
        import sqlite3

        with _connect_db() as db:
            db.execute(
                "INSERT INTO unknown_words (lang, word, status) VALUES ('en', 'dup', 'unlearned')"
            )
            try:
                db.execute(
                    "INSERT INTO unknown_words (lang, word, status) VALUES ('en', 'dup', 'unlearned')"
                )
                db.commit()
                assert False, "Should have raised IntegrityError"
            except sqlite3.IntegrityError:
                pass


# ---------------------------------------------------------------------------
# save_quiz_session
# ---------------------------------------------------------------------------


class TestSaveQuizSession:
    def test_saves_session_and_questions(self):
        questions = [
            {"question": "Q1", "choices": ["A", "B", "C"], "correct_index": 0},
            {"question": "Q2", "choices": ["X", "Y"], "correct_index": 1},
        ]
        session_id = save_quiz_session("en", "Test Quiz", questions)
        assert session_id is not None

        with _connect_db() as db:
            row = db.execute(
                "SELECT lang, title FROM quiz_sessions WHERE id = ?",
                (session_id,),
            ).fetchone()
            assert row == ("en", "Test Quiz")

            qs = db.execute(
                "SELECT question_text, choices, correct_index "
                "FROM quiz_questions WHERE session_id = ? ORDER BY question_index",
                (session_id,),
            ).fetchall()
            assert len(qs) == 2
            assert qs[0][0] == "Q1"
            assert json.loads(qs[0][1]) == ["A", "B", "C"]
            assert qs[0][2] == 0
            assert qs[1][0] == "Q2"
            assert qs[1][2] == 1

    def test_session_starts_as_pending(self):
        sid = save_quiz_session("en", "Pending", [
            {"question": "Q", "choices": ["A", "B"], "correct_index": 0},
        ])
        with _connect_db() as db:
            row = db.execute(
                "SELECT submitted_at FROM quiz_sessions WHERE id = ?", (sid,),
            ).fetchone()
            assert row[0] is None


# ---------------------------------------------------------------------------
# submit_quiz_answers
# ---------------------------------------------------------------------------


class TestSubmitQuizAnswers:
    def _make_session(self, questions=None):
        if questions is None:
            questions = [
                {"question": "Q1", "choices": ["A", "B"], "correct_index": 0},
                {"question": "Q2", "choices": ["X", "Y"], "correct_index": 1},
            ]
        return save_quiz_session("en", "Quiz", questions)

    def test_all_correct(self):
        sid = self._make_session()
        result = submit_quiz_answers(sid, [0, 1])
        assert result["session_id"] == sid
        assert result["correct_count"] == 2
        assert result["total_count"] == 2
        assert all(d["is_correct"] for d in result["details"])

    def test_all_incorrect(self):
        sid = self._make_session()
        result = submit_quiz_answers(sid, [1, 0])
        assert result["correct_count"] == 0
        assert not any(d["is_correct"] for d in result["details"])

    def test_mixed_answers(self):
        sid = self._make_session()
        result = submit_quiz_answers(sid, [0, 0])  # Q1 correct, Q2 wrong
        assert result["correct_count"] == 1

    def test_marks_session_as_submitted(self):
        sid = self._make_session()
        submit_quiz_answers(sid, [0, 1])
        with _connect_db() as db:
            row = db.execute(
                "SELECT submitted_at FROM quiz_sessions WHERE id = ?", (sid,),
            ).fetchone()
            assert row[0] is not None

    def test_result_details_structure(self):
        sid = self._make_session([
            {"question": "What?", "choices": ["Yes", "No"], "correct_index": 0},
        ])
        result = submit_quiz_answers(sid, [1])
        detail = result["details"][0]
        assert detail["question_index"] == 0
        assert detail["question_text"] == "What?"
        assert detail["choices"] == ["Yes", "No"]
        assert detail["correct_index"] == 0
        assert detail["user_answer"] == 1
        assert detail["is_correct"] is False


# ---------------------------------------------------------------------------
# get_pending_quiz
# ---------------------------------------------------------------------------


class TestGetPendingQuiz:
    def test_returns_pending_quiz(self):
        questions = [
            {"question": "Q1", "choices": ["A", "B"], "correct_index": 0},
        ]
        sid = save_quiz_session("en", "Pending Quiz", questions)
        pending = get_pending_quiz()

        assert pending is not None
        assert pending["session_id"] == sid
        assert pending["title"] == "Pending Quiz"
        assert pending["lang"] == "en"
        assert len(pending["questions"]) == 1
        assert pending["questions"][0]["question"] == "Q1"

    def test_returns_none_after_submit(self):
        questions = [
            {"question": "Q1", "choices": ["A", "B"], "correct_index": 0},
        ]
        sid = save_quiz_session("en", "Quiz", questions)
        submit_quiz_answers(sid, [0])

        assert get_pending_quiz() is None

    def test_returns_none_when_no_sessions(self):
        assert get_pending_quiz() is None

    def test_returns_pending_even_with_submitted(self):
        """提出済みと未回答が混在する場合、未回答のものを返す。"""
        sid_old = save_quiz_session("en", "Old", [
            {"question": "Q", "choices": ["A", "B"], "correct_index": 0},
        ])
        submit_quiz_answers(sid_old, [0])
        save_quiz_session("en", "New", [
            {"question": "Q", "choices": ["X", "Y"], "correct_index": 1},
        ])
        pending = get_pending_quiz()
        assert pending is not None
        assert pending["title"] == "New"


# ---------------------------------------------------------------------------
# get_quiz_results_db
# ---------------------------------------------------------------------------


class TestGetQuizResultsDb:
    def _submit_quiz(self, lang: str, title: str, answers: list[int]):
        questions = [
            {"question": f"Q{i}", "choices": ["A", "B"], "correct_index": 0}
            for i in range(len(answers))
        ]
        sid = save_quiz_session(lang, title, questions)
        submit_quiz_answers(sid, answers)
        return sid

    def test_returns_completed_results(self):
        self._submit_quiz("en", "Results Quiz", [0])
        results = get_quiz_results_db("en")

        assert len(results) == 1
        assert results[0]["title"] == "Results Quiz"
        assert results[0]["correct_count"] == 1
        assert results[0]["total_count"] == 1

    def test_excludes_pending_quizzes(self):
        save_quiz_session("en", "Pending", [
            {"question": "Q", "choices": ["A", "B"], "correct_index": 0},
        ])
        results = get_quiz_results_db("en")
        assert len(results) == 0

    def test_filters_by_language(self):
        self._submit_quiz("fr", "French Quiz", [0])
        assert len(get_quiz_results_db("en")) == 0
        assert len(get_quiz_results_db("fr")) == 1

    def test_respects_limit(self):
        for i in range(5):
            self._submit_quiz("en", f"Quiz {i}", [0])
        results = get_quiz_results_db("en", limit=3)
        assert len(results) == 3

    def test_result_questions_detail(self):
        self._submit_quiz("en", "Detail Quiz", [0, 1])
        results = get_quiz_results_db("en")
        qs = results[0]["questions"]
        assert len(qs) == 2
        assert qs[0]["is_correct"] is True
        assert qs[1]["is_correct"] is False


# ---------------------------------------------------------------------------
# save_words_db
# ---------------------------------------------------------------------------


class TestSaveWordsDb:
    def test_saves_words(self):
        saved = save_words_db("en", ["apple", "banana"])
        assert saved == ["apple", "banana"]
        with _connect_db() as db:
            rows = db.execute(
                "SELECT word FROM unknown_words WHERE lang = ? ORDER BY word",
                ("en",),
            ).fetchall()
            assert [r[0] for r in rows] == ["apple", "banana"]

    def test_saves_with_context(self):
        save_words_db("en", ["cherry"], context="I ate a cherry.")
        with _connect_db() as db:
            row = db.execute(
                "SELECT context FROM unknown_words WHERE lang = ? AND word = ?",
                ("en", "cherry"),
            ).fetchone()
            assert row[0] == "I ate a cherry."

    def test_lowercases_and_strips(self):
        saved = save_words_db("en", ["  Hello ", " WORLD"])
        assert saved == ["hello", "world"]

    def test_skips_empty_words(self):
        saved = save_words_db("en", ["", "  ", "valid"])
        assert saved == ["valid"]

    def test_preserves_existing_status(self):
        save_words_db("en", ["grape"])
        with _connect_db() as db:
            db.execute(
                "UPDATE unknown_words SET status = 'wrong' WHERE word = 'grape'"
            )
        save_words_db("en", ["grape"], context="new context")
        with _connect_db() as db:
            row = db.execute(
                "SELECT status, context FROM unknown_words WHERE word = 'grape'"
            ).fetchone()
            assert row[0] == "wrong"
            assert row[1] == "new context"

    def test_empty_list_returns_empty(self):
        saved = save_words_db("en", [])
        assert saved == []

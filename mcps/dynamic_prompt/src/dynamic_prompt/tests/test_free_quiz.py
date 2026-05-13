"""自由回答クイズの単体テスト — DB保存・提出・採点。"""

from dynamic_prompt.database import (
    _connect_db,
    get_pending_quiz,
    get_quiz_results_db,
    get_unscored_sessions_db,
    save_quiz_session,
    score_free_answers_db,
    submit_quiz_answers,
)


# ---------------------------------------------------------------------------
# save_quiz_session (free questions)
# ---------------------------------------------------------------------------


class TestSaveFreeQuizSession:
    def test_saves_free_questions(self):
        questions = [
            {"question": "Translate: hello", "model_answer": "bonjour", "question_type": "free"},
            {"question": "Translate: goodbye", "model_answer": "au revoir", "question_type": "free"},
        ]
        sid = save_quiz_session("fr", "Free Quiz", questions)
        assert sid is not None

        with _connect_db() as db:
            rows = db.execute(
                "SELECT question_text, question_type, model_answer, choices, correct_index "
                "FROM quiz_questions WHERE session_id = ? ORDER BY question_index",
                (sid,),
            ).fetchall()
            assert len(rows) == 2
            assert rows[0][0] == "Translate: hello"
            assert rows[0][1] == "free"
            assert rows[0][2] == "bonjour"
            assert rows[0][3] == "[]"
            assert rows[0][4] == 0

    def test_saves_mixed_questions(self):
        """MC と free が混在するクイズを保存できる。"""
        questions = [
            {"question": "MC Q1", "choices": ["A", "B"], "correct_index": 0},
            {"question": "Free Q1", "model_answer": "answer1", "question_type": "free"},
        ]
        sid = save_quiz_session("en", "Mixed Quiz", questions)

        with _connect_db() as db:
            rows = db.execute(
                "SELECT question_type, model_answer "
                "FROM quiz_questions WHERE session_id = ? ORDER BY question_index",
                (sid,),
            ).fetchall()
            assert rows[0] == ("mc", None)
            assert rows[1] == ("free", "answer1")

    def test_free_session_starts_as_pending(self):
        sid = save_quiz_session("en", "Free", [
            {"question": "Q", "model_answer": "A", "question_type": "free"},
        ])
        with _connect_db() as db:
            row = db.execute(
                "SELECT submitted_at, scored_at FROM quiz_sessions WHERE id = ?", (sid,),
            ).fetchone()
            assert row[0] is None
            assert row[1] is None


# ---------------------------------------------------------------------------
# submit_quiz_answers (free questions)
# ---------------------------------------------------------------------------


class TestSubmitFreeQuizAnswers:
    def test_submit_free_answers(self):
        sid = save_quiz_session("fr", "Free Quiz", [
            {"question": "Translate: cat", "model_answer": "chat", "question_type": "free"},
            {"question": "Translate: dog", "model_answer": "chien", "question_type": "free"},
        ])
        result = submit_quiz_answers(sid, ["chat", "le chien"])

        assert result["session_id"] == sid
        assert result["has_free"] is True
        assert result["mc_total"] == 0
        assert result["correct_count"] == 0  # free questions are not scored yet
        assert len(result["details"]) == 2
        assert result["details"][0]["question_type"] == "free"
        assert result["details"][0]["user_answer_text"] == "chat"
        assert result["details"][0]["is_correct"] is None
        assert result["details"][1]["user_answer_text"] == "le chien"

    def test_submit_mixed_answers(self):
        """MC + free 混在クイズの回答提出。"""
        sid = save_quiz_session("en", "Mixed", [
            {"question": "MC Q", "choices": ["A", "B"], "correct_index": 0},
            {"question": "Free Q", "model_answer": "answer", "question_type": "free"},
        ])
        result = submit_quiz_answers(sid, [0, "my answer"])

        assert result["mc_total"] == 1
        assert result["has_free"] is True
        assert result["correct_count"] == 1  # MC correct
        assert result["details"][0]["question_type"] == "mc"
        assert result["details"][0]["is_correct"] is True
        assert result["details"][1]["question_type"] == "free"
        assert result["details"][1]["user_answer_text"] == "my answer"
        assert result["details"][1]["is_correct"] is None

    def test_submit_marks_submitted_at(self):
        sid = save_quiz_session("en", "Free", [
            {"question": "Q", "model_answer": "A", "question_type": "free"},
        ])
        submit_quiz_answers(sid, ["answer"])
        with _connect_db() as db:
            row = db.execute(
                "SELECT submitted_at FROM quiz_sessions WHERE id = ?", (sid,),
            ).fetchone()
            assert row[0] is not None

    def test_user_answer_text_saved_in_db(self):
        sid = save_quiz_session("en", "Free", [
            {"question": "Q", "model_answer": "A", "question_type": "free"},
        ])
        submit_quiz_answers(sid, ["my text answer"])
        with _connect_db() as db:
            row = db.execute(
                "SELECT user_answer_text FROM quiz_questions WHERE session_id = ?",
                (sid,),
            ).fetchone()
            assert row[0] == "my text answer"


# ---------------------------------------------------------------------------
# get_pending_quiz (free questions)
# ---------------------------------------------------------------------------


class TestGetPendingFreeQuiz:
    def test_returns_free_quiz_with_type(self):
        sid = save_quiz_session("en", "Pending Free", [
            {"question": "Free Q1", "model_answer": "A1", "question_type": "free"},
        ])
        pending = get_pending_quiz()
        assert pending is not None
        assert pending["session_id"] == sid
        assert pending["questions"][0]["question_type"] == "free"
        assert "choices" not in pending["questions"][0]

    def test_returns_mixed_quiz_with_types(self):
        save_quiz_session("en", "Mixed", [
            {"question": "MC Q", "choices": ["A", "B"], "correct_index": 0},
            {"question": "Free Q", "model_answer": "ans", "question_type": "free"},
        ])
        pending = get_pending_quiz()
        assert pending["questions"][0]["question_type"] == "mc"
        assert "choices" in pending["questions"][0]
        assert pending["questions"][1]["question_type"] == "free"
        assert "choices" not in pending["questions"][1]


# ---------------------------------------------------------------------------
# get_unscored_sessions_db
# ---------------------------------------------------------------------------


class TestGetUnscoredSessions:
    def test_returns_submitted_unscored(self):
        sid = save_quiz_session("en", "Free Quiz", [
            {"question": "Q1", "model_answer": "A1", "question_type": "free"},
        ])
        submit_quiz_answers(sid, ["my answer"])

        sessions = get_unscored_sessions_db("en")
        assert len(sessions) == 1
        assert sessions[0]["session_id"] == sid
        assert len(sessions[0]["questions"]) == 1
        assert sessions[0]["questions"][0]["user_answer_text"] == "my answer"

    def test_excludes_scored_sessions(self):
        sid = save_quiz_session("en", "Free", [
            {"question": "Q", "model_answer": "A", "question_type": "free"},
        ])
        submit_quiz_answers(sid, ["ans"])
        score_free_answers_db(sid, [{"question_index": 0, "is_correct": True}])

        sessions = get_unscored_sessions_db("en")
        assert len(sessions) == 0

    def test_excludes_mc_only_sessions(self):
        sid = save_quiz_session("en", "MC Quiz", [
            {"question": "Q", "choices": ["A", "B"], "correct_index": 0},
        ])
        submit_quiz_answers(sid, [0])

        sessions = get_unscored_sessions_db("en")
        assert len(sessions) == 0

    def test_excludes_unsubmitted(self):
        save_quiz_session("en", "Not submitted", [
            {"question": "Q", "model_answer": "A", "question_type": "free"},
        ])
        sessions = get_unscored_sessions_db("en")
        assert len(sessions) == 0

    def test_filters_by_language(self):
        sid = save_quiz_session("fr", "French", [
            {"question": "Q", "model_answer": "A", "question_type": "free"},
        ])
        submit_quiz_answers(sid, ["ans"])

        assert len(get_unscored_sessions_db("fr")) == 1
        assert len(get_unscored_sessions_db("en")) == 0

    def test_respects_limit(self):
        for i in range(5):
            sid = save_quiz_session("en", f"Quiz {i}", [
                {"question": "Q", "model_answer": "A", "question_type": "free"},
            ])
            submit_quiz_answers(sid, ["ans"])

        sessions = get_unscored_sessions_db("en", limit=3)
        assert len(sessions) == 3


# ---------------------------------------------------------------------------
# score_free_answers_db
# ---------------------------------------------------------------------------


class TestScoreFreeAnswers:
    def test_scores_correct_and_incorrect(self):
        sid = save_quiz_session("en", "Free Quiz", [
            {"question": "Q1", "model_answer": "A1", "question_type": "free"},
            {"question": "Q2", "model_answer": "A2", "question_type": "free"},
        ])
        submit_quiz_answers(sid, ["A1", "wrong"])

        result = score_free_answers_db(sid, [
            {"question_index": 0, "is_correct": True},
            {"question_index": 1, "is_correct": False},
        ])
        assert result["scored_count"] == 2
        assert result["correct_count"] == 1

        with _connect_db() as db:
            rows = db.execute(
                "SELECT question_index, is_correct "
                "FROM quiz_questions WHERE session_id = ? AND question_type = 'free' "
                "ORDER BY question_index",
                (sid,),
            ).fetchall()
            assert rows[0][1] == 1  # correct
            assert rows[1][1] == 0  # incorrect

    def test_sets_scored_at(self):
        sid = save_quiz_session("en", "Free", [
            {"question": "Q", "model_answer": "A", "question_type": "free"},
        ])
        submit_quiz_answers(sid, ["ans"])
        score_free_answers_db(sid, [{"question_index": 0, "is_correct": True}])

        with _connect_db() as db:
            row = db.execute(
                "SELECT scored_at FROM quiz_sessions WHERE id = ?", (sid,),
            ).fetchone()
            assert row[0] is not None

    def test_does_not_affect_mc_questions(self):
        """MC 問題は score_free_answers_db で変更されない。"""
        sid = save_quiz_session("en", "Mixed", [
            {"question": "MC Q", "choices": ["A", "B"], "correct_index": 0},
            {"question": "Free Q", "model_answer": "ans", "question_type": "free"},
        ])
        submit_quiz_answers(sid, [1, "my answer"])  # MC wrong, free answer

        score_free_answers_db(sid, [{"question_index": 1, "is_correct": True}])

        with _connect_db() as db:
            mc_row = db.execute(
                "SELECT is_correct FROM quiz_questions "
                "WHERE session_id = ? AND question_index = 0",
                (sid,),
            ).fetchone()
            assert mc_row[0] == 0  # MC still wrong (not affected)


# ---------------------------------------------------------------------------
# get_quiz_results_db (free questions)
# ---------------------------------------------------------------------------


class TestGetQuizResultsFree:
    def test_results_include_free_question_details(self):
        sid = save_quiz_session("en", "Free Results", [
            {"question": "Q1", "model_answer": "A1", "question_type": "free"},
        ])
        submit_quiz_answers(sid, ["my answer"])

        results = get_quiz_results_db("en")
        assert len(results) == 1
        q = results[0]["questions"][0]
        assert q["question_type"] == "free"
        assert q["model_answer"] == "A1"
        assert q["user_answer_text"] == "my answer"
        assert q["is_correct"] is None  # not scored yet

    def test_results_include_scored_at(self):
        sid = save_quiz_session("en", "Scored", [
            {"question": "Q", "model_answer": "A", "question_type": "free"},
        ])
        submit_quiz_answers(sid, ["A"])
        score_free_answers_db(sid, [{"question_index": 0, "is_correct": True}])

        results = get_quiz_results_db("en")
        assert results[0]["scored_at"] is not None
        assert results[0]["questions"][0]["is_correct"] is True

    def test_results_mixed_quiz(self):
        sid = save_quiz_session("en", "Mixed", [
            {"question": "MC Q", "choices": ["A", "B"], "correct_index": 0},
            {"question": "Free Q", "model_answer": "ans", "question_type": "free"},
        ])
        submit_quiz_answers(sid, [0, "my answer"])

        results = get_quiz_results_db("en")
        qs = results[0]["questions"]
        assert qs[0]["question_type"] == "mc"
        assert qs[0]["is_correct"] is True
        assert qs[1]["question_type"] == "free"
        assert qs[1]["user_answer_text"] == "my answer"

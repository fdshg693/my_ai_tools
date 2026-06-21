"""クイズセッション・問題・採点の SQLite アクセス (MC + 自由回答)。"""

import json

from dynamic_prompt.repo.sqlite_repo.connection import _connect_db


def save_quiz_session(lang: str, title: str, questions: list[dict]) -> int:
    """クイズセッションと問題をDBに保存し、セッションIDを返す。

    各問題の ``question_type`` が ``'free'`` の場合は自由回答として保存する。
    省略時は ``'mc'`` (選択式)。
    """
    with _connect_db() as db:
        cursor = db.execute(
            "INSERT INTO quiz_sessions (lang, title) VALUES (?, ?)",
            (lang, title),
        )
        session_id = cursor.lastrowid
        for i, q in enumerate(questions):
            qtype = q.get("question_type", "mc")
            if qtype == "free":
                db.execute(
                    """INSERT INTO quiz_questions
                       (session_id, question_index, question_text, question_type,
                        model_answer, choices, correct_index)
                       VALUES (?, ?, ?, 'free', ?, '[]', 0)""",
                    (session_id, i, q["question"], q.get("model_answer", "")),
                )
            else:
                db.execute(
                    """INSERT INTO quiz_questions
                       (session_id, question_index, question_text, choices, correct_index,
                        question_type)
                       VALUES (?, ?, ?, ?, ?, 'mc')""",
                    (
                        session_id,
                        i,
                        q["question"],
                        json.dumps(q["choices"], ensure_ascii=False),
                        q["correct_index"],
                    ),
                )
    return session_id


def submit_quiz_answers(session_id: int, answers: list) -> dict:
    """ユーザーの回答を保存・採点し、結果を返す。

    MC 問題は即時採点、free 問題はテキストを保存して未採点のまま残す。
    ``answers`` の各要素は MC なら int (選択肢インデックス)、free なら str (テキスト)。
    """
    with _connect_db() as db:
        rows = db.execute(
            "SELECT id, question_index, question_text, choices, correct_index, "
            "question_type, model_answer "
            "FROM quiz_questions WHERE session_id = ? ORDER BY question_index",
            (session_id,),
        ).fetchall()

        correct_count = 0
        mc_total = 0
        has_free = False
        details = []
        for row, user_ans in zip(rows, answers):
            if row["question_type"] == "free":
                has_free = True
                db.execute(
                    "UPDATE quiz_questions SET user_answer_text = ? WHERE id = ?",
                    (str(user_ans), row["id"]),
                )
                details.append(
                    {
                        "question_index": row["question_index"],
                        "question_text": row["question_text"],
                        "question_type": "free",
                        "user_answer_text": str(user_ans),
                        "model_answer": row["model_answer"] or "",
                        "is_correct": None,
                    }
                )
            else:
                mc_total += 1
                user_ans_int = int(user_ans)
                is_correct = 1 if user_ans_int == row["correct_index"] else 0
                correct_count += is_correct
                db.execute(
                    "UPDATE quiz_questions SET user_answer = ?, is_correct = ? WHERE id = ?",
                    (user_ans_int, is_correct, row["id"]),
                )
                details.append(
                    {
                        "question_index": row["question_index"],
                        "question_text": row["question_text"],
                        "question_type": "mc",
                        "choices": json.loads(row["choices"]),
                        "correct_index": row["correct_index"],
                        "user_answer": user_ans_int,
                        "is_correct": bool(is_correct),
                    }
                )

        db.execute(
            "UPDATE quiz_sessions SET submitted_at = datetime('now') WHERE id = ?",
            (session_id,),
        )

    return {
        "session_id": session_id,
        "correct_count": correct_count,
        "total_count": len(rows),
        "mc_total": mc_total,
        "has_free": has_free,
        "details": details,
    }


def get_pending_quiz() -> dict | None:
    """未回答の最新クイズセッションを返す。なければNone。"""
    with _connect_db() as db:
        row = db.execute(
            "SELECT id, lang, title FROM quiz_sessions "
            "WHERE submitted_at IS NULL ORDER BY created_at DESC LIMIT 1",
        ).fetchone()
        if not row:
            return None
        sid = row["id"]
        questions = db.execute(
            "SELECT question_index, question_text, choices, correct_index, "
            "question_type, model_answer "
            "FROM quiz_questions WHERE session_id = ? ORDER BY question_index",
            (sid,),
        ).fetchall()
    result_questions = []
    for q in questions:
        qtype = q["question_type"] or "mc"
        if qtype == "free":
            result_questions.append(
                {
                    "question": q["question_text"],
                    "question_type": "free",
                }
            )
        else:
            result_questions.append(
                {
                    "question": q["question_text"],
                    "question_type": "mc",
                    "choices": json.loads(q["choices"]),
                    "correct_index": q["correct_index"],
                }
            )
    return {
        "session_id": sid,
        "lang": row["lang"],
        "title": row["title"],
        "questions": result_questions,
    }


def get_quiz_results_db(lang: str, limit: int = 5) -> list[dict]:
    """直近の完了済みクイズ結果を返す。"""
    with _connect_db() as db:
        sessions = db.execute(
            "SELECT id, title, submitted_at, scored_at FROM quiz_sessions "
            "WHERE lang = ? AND submitted_at IS NOT NULL "
            "ORDER BY submitted_at DESC LIMIT ?",
            (lang, limit),
        ).fetchall()
        results = []
        for s in sessions:
            questions = db.execute(
                "SELECT question_index, question_text, choices, correct_index, "
                "user_answer, is_correct, question_type, model_answer, user_answer_text "
                "FROM quiz_questions WHERE session_id = ? ORDER BY question_index",
                (s["id"],),
            ).fetchall()
            correct_count = sum(1 for q in questions if q["is_correct"])
            q_details = []
            for q in questions:
                qtype = q["question_type"] or "mc"
                is_correct = q["is_correct"]
                if qtype == "free":
                    q_details.append(
                        {
                            "index": q["question_index"],
                            "question_text": q["question_text"],
                            "question_type": "free",
                            "model_answer": q["model_answer"] or "",
                            "user_answer_text": q["user_answer_text"] or "",
                            "is_correct": bool(is_correct) if is_correct is not None else None,
                        }
                    )
                else:
                    choices = json.loads(q["choices"])
                    user_answer = q["user_answer"]
                    q_details.append(
                        {
                            "index": q["question_index"],
                            "question_text": q["question_text"],
                            "question_type": "mc",
                            "correct_choice": choices[q["correct_index"]],
                            "user_choice": (
                                choices[user_answer] if user_answer is not None else "(未回答)"
                            ),
                            "is_correct": bool(is_correct),
                        }
                    )
            results.append(
                {
                    "session_id": s["id"],
                    "title": s["title"],
                    "submitted_at": s["submitted_at"],
                    "scored_at": s["scored_at"],
                    "correct_count": correct_count,
                    "total_count": len(questions),
                    "questions": q_details,
                }
            )
    return results


def get_unscored_sessions_db(lang: str, limit: int = 5) -> list[dict]:
    """提出済みだが未採点の自由回答を含むクイズセッションを返す。"""
    with _connect_db() as db:
        sessions = db.execute(
            "SELECT DISTINCT s.id, s.title, s.submitted_at "
            "FROM quiz_sessions s "
            "JOIN quiz_questions q ON q.session_id = s.id "
            "WHERE s.lang = ? AND s.submitted_at IS NOT NULL "
            "  AND s.scored_at IS NULL "
            "  AND q.question_type = 'free' "
            "  AND q.user_answer_text IS NOT NULL "
            "ORDER BY s.submitted_at DESC LIMIT ?",
            (lang, limit),
        ).fetchall()
        results = []
        for s in sessions:
            questions = db.execute(
                "SELECT question_index, question_text, model_answer, "
                "user_answer_text, is_correct "
                "FROM quiz_questions "
                "WHERE session_id = ? AND question_type = 'free' "
                "ORDER BY question_index",
                (s["id"],),
            ).fetchall()
            results.append(
                {
                    "session_id": s["id"],
                    "title": s["title"],
                    "submitted_at": s["submitted_at"],
                    "questions": [
                        {
                            "question_index": q["question_index"],
                            "question_text": q["question_text"],
                            "model_answer": q["model_answer"] or "",
                            "user_answer_text": q["user_answer_text"] or "",
                            "is_correct": (
                                bool(q["is_correct"])
                                if q["is_correct"] is not None
                                else None
                            ),
                        }
                        for q in questions
                    ],
                }
            )
    return results


def score_free_answers_db(session_id: int, scores: list[dict]) -> dict:
    """AI が自由回答を採点した結果を保存する。

    ``scores`` は ``[{"question_index": 0, "is_correct": True}, ...]`` の形式。
    """
    with _connect_db() as db:
        correct_count = 0
        for s in scores:
            is_correct = 1 if s["is_correct"] else 0
            correct_count += is_correct
            db.execute(
                "UPDATE quiz_questions SET is_correct = ? "
                "WHERE session_id = ? AND question_index = ? AND question_type = 'free'",
                (is_correct, session_id, s["question_index"]),
            )
        db.execute(
            "UPDATE quiz_sessions SET scored_at = datetime('now') WHERE id = ?",
            (session_id,),
        )
    return {"session_id": session_id, "scored_count": len(scores), "correct_count": correct_count}


class SqliteQuizRepo:
    """クイズの SQLite リポジトリ。"""

    def create_session(self, lang: str, title: str, questions: list[dict]) -> int:
        return save_quiz_session(lang, title, questions)

    def submit_answers(self, session_id: int, answers: list) -> dict:
        return submit_quiz_answers(session_id, answers)

    def get_pending(self) -> dict | None:
        return get_pending_quiz()

    def get_recent_results(self, lang: str, limit: int = 5) -> list[dict]:
        return get_quiz_results_db(lang, limit)

    def get_unscored(self, lang: str, limit: int = 5) -> list[dict]:
        return get_unscored_sessions_db(lang, limit)

    def score_free_answers(self, session_id: int, scores: list[dict]) -> dict:
        return score_free_answers_db(session_id, scores)

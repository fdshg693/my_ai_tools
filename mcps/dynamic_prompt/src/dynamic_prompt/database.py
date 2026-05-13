"""DB 接続とスキーマ管理。"""

import json
import os
import sqlite3
from collections.abc import Callable
from pathlib import Path

DB_PATH = Path(os.environ.get("DB_PATH", str(Path(__file__).parent / "vocab.db")))

STATUS_UNLEARNED = "unlearned"
STATUS_WRONG = "wrong"
STATUS_MEMORY_TEST = "memory_test"


def _column_exists(db: sqlite3.Connection, table: str, column: str) -> bool:
    cols = db.execute(f"PRAGMA table_info({table})").fetchall()
    return any(c[1] == column for c in cols)


def _table_exists(db: sqlite3.Connection, table: str) -> bool:
    row = db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    return row is not None


# ---------------------------------------------------------------------------
# マイグレーション定義
# ---------------------------------------------------------------------------
# 新しいマイグレーションを追加するには:
#   1. _migration_NNN 関数を定義する
#   2. _MIGRATIONS リストの末尾に (バージョン番号, 説明, 関数) を追加する
# バージョン番号は連番にすること。


def _migration_001(db: sqlite3.Connection) -> None:
    """既存 DB に status / reviewed_at カラムがなければ追加する。"""
    if not _column_exists(db, "unknown_words", "status"):
        db.execute(
            "ALTER TABLE unknown_words ADD COLUMN status TEXT NOT NULL DEFAULT 'unlearned'"
        )
    if not _column_exists(db, "unknown_words", "reviewed_at"):
        db.execute(
            "ALTER TABLE unknown_words ADD COLUMN reviewed_at TEXT DEFAULT NULL"
        )


def _migration_002(db: sqlite3.Connection) -> None:
    """story_topics テーブルを追加する。"""
    if not _table_exists(db, "story_topics"):
        db.execute("""
            CREATE TABLE story_topics (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                lang       TEXT NOT NULL,
                topic      TEXT NOT NULL,
                summary    TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)


def _migration_003(db: sqlite3.Connection) -> None:
    """自由回答クイズ対応: quiz_questions に question_type / model_answer / user_answer_text、
    quiz_sessions に scored_at を追加する。"""
    if _table_exists(db, "quiz_questions"):
        if not _column_exists(db, "quiz_questions", "question_type"):
            db.execute(
                "ALTER TABLE quiz_questions ADD COLUMN question_type TEXT NOT NULL DEFAULT 'mc'"
            )
        if not _column_exists(db, "quiz_questions", "model_answer"):
            db.execute(
                "ALTER TABLE quiz_questions ADD COLUMN model_answer TEXT DEFAULT NULL"
            )
        if not _column_exists(db, "quiz_questions", "user_answer_text"):
            db.execute(
                "ALTER TABLE quiz_questions ADD COLUMN user_answer_text TEXT DEFAULT NULL"
            )
    if _table_exists(db, "quiz_sessions"):
        if not _column_exists(db, "quiz_sessions", "scored_at"):
            db.execute(
                "ALTER TABLE quiz_sessions ADD COLUMN scored_at TEXT DEFAULT NULL"
            )


_MIGRATIONS: list[tuple[int, str, Callable[[sqlite3.Connection], None]]] = [
    (1, "Add status and reviewed_at to unknown_words", _migration_001),
    (2, "Add story_topics table", _migration_002),
    (3, "Add free-answer quiz support", _migration_003),
]


def _get_current_version(db: sqlite3.Connection) -> int:
    """現在のスキーマバージョンを返す。テーブルがなければ 0。"""
    if not _table_exists(db, "schema_version"):
        return 0
    row = db.execute("SELECT MAX(version) FROM schema_version").fetchone()
    return row[0] or 0


def _migrate(db: sqlite3.Connection) -> None:
    """未適用のマイグレーションを順番に実行する。"""
    db.execute("""
        CREATE TABLE IF NOT EXISTS schema_version (
            version     INTEGER PRIMARY KEY,
            description TEXT NOT NULL,
            applied_at  TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    current = _get_current_version(db)
    for version, description, func in _MIGRATIONS:
        if version > current:
            func(db)
            db.execute(
                "INSERT INTO schema_version (version, description) VALUES (?, ?)",
                (version, description),
            )
    db.commit()


def init_db() -> None:
    """スキーマ作成とマイグレーションを実行する。サーバー起動時に1回だけ呼ぶ。"""
    db = sqlite3.connect(DB_PATH)
    try:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("""
            CREATE TABLE IF NOT EXISTS unknown_words (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                lang        TEXT NOT NULL,
                word        TEXT NOT NULL,
                context     TEXT,
                status      TEXT NOT NULL DEFAULT 'unlearned',
                reviewed_at TEXT DEFAULT NULL,
                created_at  TEXT NOT NULL DEFAULT (datetime('now')),
                UNIQUE(lang, word)
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS quiz_sessions (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                lang         TEXT NOT NULL,
                title        TEXT NOT NULL DEFAULT '',
                created_at   TEXT NOT NULL DEFAULT (datetime('now')),
                submitted_at TEXT DEFAULT NULL,
                scored_at    TEXT DEFAULT NULL
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS quiz_questions (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id       INTEGER NOT NULL REFERENCES quiz_sessions(id),
                question_index   INTEGER NOT NULL,
                question_text    TEXT NOT NULL,
                choices          TEXT NOT NULL DEFAULT '[]',
                correct_index    INTEGER NOT NULL DEFAULT 0,
                user_answer      INTEGER DEFAULT NULL,
                is_correct       INTEGER DEFAULT NULL,
                question_type    TEXT NOT NULL DEFAULT 'mc',
                model_answer     TEXT DEFAULT NULL,
                user_answer_text TEXT DEFAULT NULL,
                UNIQUE(session_id, question_index)
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS story_topics (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                lang       TEXT NOT NULL,
                topic      TEXT NOT NULL,
                summary    TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        _migrate(db)
    finally:
        db.close()


def _connect_db() -> sqlite3.Connection:
    """毎回新しい接続を返す。FastMCP (HTTP) は複数スレッドでツールを呼ぶため、
    接続をグローバルに使い回すと 'SQLite objects created in a thread can only
    be used in that same thread' エラーになる。呼び出し側は `with _connect_db() as db:`
    で使うこと。"""
    return sqlite3.connect(DB_PATH)


# ---------------------------------------------------------------------------
# Quiz helpers
# ---------------------------------------------------------------------------


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
            qid, idx, text, choices_json, correct_idx, qtype, model_ans = row

            if qtype == "free":
                has_free = True
                db.execute(
                    "UPDATE quiz_questions SET user_answer_text = ? WHERE id = ?",
                    (str(user_ans), qid),
                )
                details.append(
                    {
                        "question_index": idx,
                        "question_text": text,
                        "question_type": "free",
                        "user_answer_text": str(user_ans),
                        "model_answer": model_ans or "",
                        "is_correct": None,
                    }
                )
            else:
                mc_total += 1
                user_ans_int = int(user_ans)
                is_correct = 1 if user_ans_int == correct_idx else 0
                correct_count += is_correct
                db.execute(
                    "UPDATE quiz_questions SET user_answer = ?, is_correct = ? WHERE id = ?",
                    (user_ans_int, is_correct, qid),
                )
                choices = json.loads(choices_json)
                details.append(
                    {
                        "question_index": idx,
                        "question_text": text,
                        "question_type": "mc",
                        "choices": choices,
                        "correct_index": correct_idx,
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
        sid, lang_code, title = row
        questions = db.execute(
            "SELECT question_index, question_text, choices, correct_index, "
            "question_type, model_answer "
            "FROM quiz_questions WHERE session_id = ? ORDER BY question_index",
            (sid,),
        ).fetchall()
    result_questions = []
    for q in questions:
        qtype = q[4] if q[4] else "mc"
        if qtype == "free":
            result_questions.append(
                {
                    "question": q[1],
                    "question_type": "free",
                }
            )
        else:
            result_questions.append(
                {
                    "question": q[1],
                    "question_type": "mc",
                    "choices": json.loads(q[2]),
                    "correct_index": q[3],
                }
            )
    return {
        "session_id": sid,
        "lang": lang_code,
        "title": title,
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
        for sid, title, submitted_at, scored_at in sessions:
            questions = db.execute(
                "SELECT question_index, question_text, choices, correct_index, "
                "user_answer, is_correct, question_type, model_answer, user_answer_text "
                "FROM quiz_questions WHERE session_id = ? ORDER BY question_index",
                (sid,),
            ).fetchall()
            correct_count = sum(1 for q in questions if q[5])
            q_details = []
            for q in questions:
                qtype = q[6] if q[6] else "mc"
                if qtype == "free":
                    q_details.append(
                        {
                            "index": q[0],
                            "question_text": q[1],
                            "question_type": "free",
                            "model_answer": q[7] or "",
                            "user_answer_text": q[8] or "",
                            "is_correct": bool(q[5]) if q[5] is not None else None,
                        }
                    )
                else:
                    choices = json.loads(q[2])
                    q_details.append(
                        {
                            "index": q[0],
                            "question_text": q[1],
                            "question_type": "mc",
                            "correct_choice": choices[q[3]],
                            "user_choice": (
                                choices[q[4]] if q[4] is not None else "(未回答)"
                            ),
                            "is_correct": bool(q[5]),
                        }
                    )
            results.append(
                {
                    "session_id": sid,
                    "title": title,
                    "submitted_at": submitted_at,
                    "scored_at": scored_at,
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
        for sid, title, submitted_at in sessions:
            questions = db.execute(
                "SELECT question_index, question_text, model_answer, "
                "user_answer_text, is_correct "
                "FROM quiz_questions "
                "WHERE session_id = ? AND question_type = 'free' "
                "ORDER BY question_index",
                (sid,),
            ).fetchall()
            results.append(
                {
                    "session_id": sid,
                    "title": title,
                    "submitted_at": submitted_at,
                    "questions": [
                        {
                            "question_index": q[0],
                            "question_text": q[1],
                            "model_answer": q[2] or "",
                            "user_answer_text": q[3] or "",
                            "is_correct": bool(q[4]) if q[4] is not None else None,
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


# ---------------------------------------------------------------------------
# Word helpers
# ---------------------------------------------------------------------------


def save_words_db(lang: str, words: list[str], context: str = "") -> list[str]:
    """単語をDBに保存し、保存された単語のリストを返す。

    既存の単語はコンテキストのみ更新し、ステータスは保持する。
    """
    ctx = context.strip() or None
    saved: list[str] = []
    with _connect_db() as db:
        for word in words:
            w = word.strip().lower()
            if not w:
                continue
            db.execute(
                """INSERT INTO unknown_words (lang, word, context, status)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(lang, word) DO UPDATE
                       SET context = COALESCE(excluded.context, context)""",
                (lang, w, ctx, STATUS_UNLEARNED),
            )
            saved.append(w)
    return saved


# ---------------------------------------------------------------------------
# Story topic helpers
# ---------------------------------------------------------------------------


def save_story_topic_db(lang: str, topic: str, summary: str = "") -> int:
    """話題を保存し、IDを返す。"""
    with _connect_db() as db:
        cursor = db.execute(
            "INSERT INTO story_topics (lang, topic, summary) VALUES (?, ?, ?)",
            (lang, topic, summary),
        )
        return cursor.lastrowid


def get_past_topics_db(lang: str, limit: int = 20) -> list[dict]:
    """直近の話題を新しい順に返す。"""
    with _connect_db() as db:
        rows = db.execute(
            "SELECT id, topic, summary, created_at FROM story_topics "
            "WHERE lang = ? ORDER BY id DESC LIMIT ?",
            (lang, limit),
        ).fetchall()
    return [
        {"id": r[0], "topic": r[1], "summary": r[2], "created_at": r[3]}
        for r in rows
    ]

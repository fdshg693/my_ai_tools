"""MCP ツール定義とテンプレートレンダリング。"""

import json
import os
import random
from dataclasses import asdict

from dynamic_prompt.config import config_store
from dynamic_prompt.database import (
    STATUS_MEMORY_TEST,
    STATUS_UNLEARNED,
    STATUS_WRONG,
    _connect_db,
    get_past_topics_db,
    get_quiz_results_db,
    get_unscored_sessions_db,
    save_quiz_session,
    save_story_topic_db,
    score_free_answers_db,
)
from dynamic_prompt.main import mcp
from dynamic_prompt.models import Language
from dynamic_prompt.quiz_server import get_active_port, push_quiz
from dynamic_prompt.session import session


# ---------------------------------------------------------------------------
# Instruction rendering
# ---------------------------------------------------------------------------


def _resolve_user_config_vars() -> dict[str, str]:
    return {
        **asdict(config_store.user_config),
        "available_learning_languages": config_store.format_language_codes(),
    }


def _resolve_language_vars() -> dict[str, str]:
    lang = session.lang
    return {
        "label": lang.label,
        "user_level": lang.user_level,
        "teaching_guide": lang.teaching_guide,
    }


_VAR_RESOLVERS: dict[str, callable] = {
    "user_config": _resolve_user_config_vars,
    "language": _resolve_language_vars,
}


def _render_instruction(name: str) -> str:
    instr = config_store.instructions[name]
    if instr.requires_language and not session.lang_is_set:
        raise ValueError(
            f"Instruction '{name}' requires a language to be set. "
            "Call 'determine_language' tool first."
        )
    ctx: dict[str, str] = {}
    for group in instr.variables:
        ctx.update(_VAR_RESOLVERS[group]())
    return instr.template.format_map(ctx)


# ---------------------------------------------------------------------------
# Vocab helpers
# ---------------------------------------------------------------------------

_STATUS_LABEL = {
    STATUS_UNLEARNED: "new",
    STATUS_WRONG: "needs practice",
    STATUS_MEMORY_TEST: "review",
}


def _save_word(db, lang: str, word: str, context: str) -> str:
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


def _process_answer(db, lang: str, word: str, is_correct: bool) -> str:
    """ステータス遷移を適用し、結果メッセージを返す。"""
    w = word.strip().lower()
    row = db.execute(
        "SELECT status FROM unknown_words WHERE lang = ? AND word = ?",
        (lang, w),
    ).fetchone()
    if row is None:
        return f"'{word.strip()}': not found"

    status = row[0]

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


# ---------------------------------------------------------------------------
# MCP Tools
# ---------------------------------------------------------------------------


@mcp.tool
def determine_language(language: str) -> str:
    """
    Set the target language for the current learning session.
    Must be called after get_instruction("init") and before get_instruction("general"), vocabulary tools, or any language-dependent instruction.
    Accepts a language code (e.g. "en", "fr"), full name (e.g. "English", "French"), or native name (e.g. "英語"). Case-insensitive.
    """
    v = language.strip().lower()
    for lang in config_store.languages.values():
        candidates = [lang.code, lang.label] + lang.aliases
        if v in [c.lower() for c in candidates]:
            session.lang = lang
            return f"Target language set to {lang.label}."
    name = language.strip()
    session.lang = Language(
        code=name,
        label=name,
        user_level=config_store.languages["_default"].user_level,
        teaching_guide=config_store.languages["_default"].teaching_guide,
    )
    return f"Target language set to {name}. (No detailed support available; using general instructions.)"



def _get_instruction_description() -> str:
    lines = [
        "Retrieve a specific instruction by name and return its full content as a system prompt.",
        "The returned text contains detailed directives for how to assist the user.",
        "",
        "Available instructions:",
    ]
    for name, instr in config_store.instructions.items():
        lines.append(f"  - {name}: {instr.description}")
    return "\n".join(lines)


@mcp.tool(description=_get_instruction_description())
def get_instruction(name: str) -> str:
    if name not in config_store.instructions:
        available = ", ".join(config_store.instructions.keys())
        return f"Unknown instruction: '{name}'. Available: {available}"
    try:
        return _render_instruction(name)
    except ValueError as e:
        return str(e)


@mcp.tool
def get_words() -> str:
    """
    Retrieve random words available for review or quiz use.
    Requires determine_language to be called first.
    Returns word, status, and context for each word.
    The number of words returned is configured in app_config.yaml.
    """
    lang = session.lang.code
    period = config_store.user_config.memory_test_period_hours
    limit = config_store.app_config.vocab_get_limit

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
                str(period),
                limit,
            ),
        ).fetchall()

    if not rows:
        return "No words available for review."
    lines = []
    for w, ctx, status in rows:
        label = _STATUS_LABEL.get(status, status)
        line = f"- {w} [{label}]"
        if ctx:
            line += f" (context: {ctx})"
        lines.append(line)
    return "\n".join(lines)


@mcp.tool
def save_words(words: str, context: str = "") -> str:
    """
    Save multiple words to the vocabulary list at once.
    Requires determine_language to be called first.
    If a word already exists, only the context is updated (status is preserved).

    words   : Comma-separated list of words (e.g. "apple, banana, cherry").
    context : Optional shared context for all words (e.g. the sentence they appeared in).
    """
    lang = session.lang.code
    items = [w.strip() for w in words.split(",") if w.strip()]
    if not items:
        return "No words provided."

    saved = []
    with _connect_db() as db:
        for item in items:
            w = _save_word(db, lang, item, context)
            if w:
                saved.append(w)

    if not saved:
        return "No valid words to save."
    return f"Saved {len(saved)} word(s): {', '.join(saved)}"


@mcp.tool
def answer_words(correct: str = "", incorrect: str = "") -> str:
    """
    Record quiz results for multiple words at once.
    Requires determine_language to be called first.
    Status transitions are applied automatically per word.

    Words have three status levels:
    - "new": Correct → removed. Wrong → "needs practice".
    - "needs practice": Correct → "review". Wrong → stays.
    - "review": Correct → fully learned (removed). Wrong → back to "needs practice".

    correct   : Comma-separated list of words the user answered correctly (e.g. "apple, banana").
    incorrect : Comma-separated list of words the user answered incorrectly (e.g. "cherry, durian").
    """
    lang = session.lang.code
    correct_words = [w.strip() for w in correct.split(",") if w.strip()]
    incorrect_words = [w.strip() for w in incorrect.split(",") if w.strip()]

    if not correct_words and not incorrect_words:
        return "No words provided."

    results = []
    with _connect_db() as db:
        for w in correct_words:
            results.append(_process_answer(db, lang, w, True))
        for w in incorrect_words:
            results.append(_process_answer(db, lang, w, False))

    return "\n".join(results)


# ---------------------------------------------------------------------------
# Quiz Tools
# ---------------------------------------------------------------------------


def _shuffle_choices(questions: list[dict]) -> list[dict]:
    """選択肢の順序をランダム化し、correct_indexを更新する。"""
    shuffled = []
    for q in questions:
        choices = list(q["choices"])
        correct_answer = choices[q["correct_index"]]
        random.shuffle(choices)
        shuffled.append(
            {
                **q,
                "choices": choices,
                "correct_index": choices.index(correct_answer),
            }
        )
    return shuffled


@mcp.tool
def send_quiz(title: str, questions: str) -> str:
    """
    Send a multiple-choice quiz to the web UI for the user to answer.
    Requires determine_language to be called first.
    After calling this tool, tell the user to open the quiz URL in their browser.
    Choice order is automatically randomized by this tool — always set correct_index to 0 (put the correct answer first).

    title     : Quiz title (e.g. "Vocabulary Quiz - French").
    questions : JSON array of question objects. Each object must have:
                - "question": the question text
                - "choices": array of choice strings (2-6 choices). Put the correct answer FIRST.
                - "correct_index": always 0 (correct answer is the first choice; this tool shuffles automatically)
                Example: [{"question": "What does 'pomme' mean?",
                           "choices": ["Apple", "Orange", "Banana", "Grape"],
                           "correct_index": 0}]
    """
    lang = session.lang.code
    try:
        items = json.loads(questions)
    except json.JSONDecodeError as e:
        return f"Invalid JSON: {e}"

    if not isinstance(items, list) or not items:
        return "questions must be a non-empty JSON array."

    for i, q in enumerate(items):
        if not isinstance(q, dict):
            return f"Question {i} must be an object."
        for key in ("question", "choices", "correct_index"):
            if key not in q:
                return f"Question {i} missing required field: '{key}'."
        if not isinstance(q["choices"], list) or len(q["choices"]) < 2:
            return f"Question {i} must have at least 2 choices."
        if not (0 <= q["correct_index"] < len(q["choices"])):
            return f"Question {i} correct_index out of range."

    items = _shuffle_choices(items)

    session_id = save_quiz_session(lang, title, items)

    quiz_data = {
        "session_id": session_id,
        "title": title,
        "lang": lang,
        "questions": items,
    }
    push_quiz(quiz_data)

    if os.environ.get("TRANSPORT") == "http":
        url_info = "Quiz UI is available at the service root URL."
    else:
        port = get_active_port() or config_store.app_config.quiz_server_port
        url_info = f"URL: http://127.0.0.1:{port}"
    return (
        f"Quiz '{title}' with {len(items)} question(s) sent to web UI.\n"
        f"Session ID: {session_id}\n"
        f"{url_info}"
    )


@mcp.tool
def get_quiz_results(limit: int = 5) -> str:
    """
    Retrieve recent quiz results from the database.
    Requires determine_language to be called first.
    Returns quiz scores and per-question details for the most recent completed quizzes.
    Includes both multiple-choice and free-answer quizzes.

    limit : Maximum number of quiz sessions to return (default 5).
    """
    lang = session.lang.code
    results = get_quiz_results_db(lang, limit)

    if not results:
        return "No completed quizzes found."

    lines = []
    for r in results:
        score = r["correct_count"]
        total = r["total_count"]
        pct = (score / total * 100) if total > 0 else 0
        lines.append(f"## {r['title']} ({r['submitted_at']})")
        lines.append(f"Score: {score}/{total} ({pct:.0f}%)")
        if r.get("scored_at"):
            lines.append(f"Free answers scored at: {r['scored_at']}")
        for q in r["questions"]:
            if q.get("question_type") == "free":
                status = (
                    "correct" if q["is_correct"] is True
                    else "wrong" if q["is_correct"] is False
                    else "unscored"
                )
                lines.append(
                    f"  - Q{q['index'] + 1} [free]: {q['question_text']} "
                    f"[{status}] (user: {q['user_answer_text']}, expected: {q['model_answer']})"
                )
            else:
                mark = "correct" if q["is_correct"] else "wrong"
                lines.append(
                    f"  - Q{q['index'] + 1}: {q['question_text']} "
                    f"[{mark}] (answered: {q['user_choice']}, correct: {q['correct_choice']})"
                )
        lines.append("")
    return "\n".join(lines)


@mcp.tool
def send_free_quiz(title: str, questions: str) -> str:
    """
    Send a free-answer quiz to the web UI for the user to answer in writing.
    Requires determine_language to be called first.
    Free-answer quizzes are NOT scored immediately — the user's text answers are saved,
    and you must call get_unscored_quizzes + score_free_answers later to grade them.

    title     : Quiz title (e.g. "Free Answer Quiz - French").
    questions : JSON array of question objects. Each object must have:
                - "question": the question text
                - "model_answer": the expected/ideal answer (used when you score later)
                Example: [{{"question": "Translate 'I love reading' into French.",
                           "model_answer": "J'aime lire"}}]
    """
    lang = session.lang.code
    try:
        items = json.loads(questions)
    except json.JSONDecodeError as e:
        return f"Invalid JSON: {e}"

    if not isinstance(items, list) or not items:
        return "questions must be a non-empty JSON array."

    for i, q in enumerate(items):
        if not isinstance(q, dict):
            return f"Question {i} must be an object."
        if "question" not in q:
            return f"Question {i} missing required field: 'question'."
        if "model_answer" not in q:
            return f"Question {i} missing required field: 'model_answer'."

    # question_type を追加して DB 保存
    db_items = [
        {
            "question": q["question"],
            "model_answer": q["model_answer"],
            "question_type": "free",
        }
        for q in items
    ]
    session_id = save_quiz_session(lang, title, db_items)

    quiz_data = {
        "session_id": session_id,
        "title": title,
        "lang": lang,
        "questions": [
            {"question": q["question"], "question_type": "free"}
            for q in items
        ],
    }
    push_quiz(quiz_data)

    if os.environ.get("TRANSPORT") == "http":
        url_info = "Quiz UI is available at the service root URL."
    else:
        port = get_active_port() or config_store.app_config.quiz_server_port
        url_info = f"URL: http://127.0.0.1:{port}"
    return (
        f"Free-answer quiz '{title}' with {len(items)} question(s) sent to web UI.\n"
        f"Session ID: {session_id}\n"
        f"{url_info}\n"
        f"After the user submits, call get_unscored_quizzes() to retrieve the answers, "
        f"then score_free_answers() to record your grading."
    )


@mcp.tool
def get_unscored_quizzes(limit: int = 5) -> str:
    """
    Retrieve free-answer quizzes that the user has submitted but have not been scored yet.
    Requires determine_language to be called first.
    Use this to find quizzes that need your grading, then call score_free_answers to record scores.

    limit : Maximum number of sessions to return (default 5).
    """
    lang = session.lang.code
    sessions = get_unscored_sessions_db(lang, limit)

    if not sessions:
        return "No unscored free-answer quizzes found."

    lines = []
    for s in sessions:
        lines.append(f"## Session {s['session_id']}: {s['title']} (submitted: {s['submitted_at']})")
        for q in s["questions"]:
            lines.append(
                f"  - Q{q['question_index'] + 1}: {q['question_text']}\n"
                f"    Expected: {q['model_answer']}\n"
                f"    User answered: {q['user_answer_text']}"
            )
        lines.append("")
    return "\n".join(lines)


@mcp.tool
def score_free_answers(session_id: int, scores: str) -> str:
    """
    Score the user's free-answer quiz responses. Call this after reviewing the user's answers
    from get_unscored_quizzes.
    Requires determine_language to be called first.

    session_id : The quiz session ID to score.
    scores     : JSON array of score objects. Each object must have:
                 - "question_index": 0-based index of the question
                 - "is_correct": true or false
                 Example: [{{"question_index": 0, "is_correct": true}},
                           {{"question_index": 1, "is_correct": false}}]
    """
    try:
        items = json.loads(scores)
    except json.JSONDecodeError as e:
        return f"Invalid JSON: {e}"

    if not isinstance(items, list) or not items:
        return "scores must be a non-empty JSON array."

    for i, s in enumerate(items):
        if not isinstance(s, dict):
            return f"Score {i} must be an object."
        if "question_index" not in s:
            return f"Score {i} missing required field: 'question_index'."
        if "is_correct" not in s:
            return f"Score {i} missing required field: 'is_correct'."

    result = score_free_answers_db(session_id, items)
    return (
        f"Scored {result['scored_count']} free-answer question(s) for session {session_id}.\n"
        f"Correct: {result['correct_count']}/{result['scored_count']}"
    )


# ---------------------------------------------------------------------------
# Story Topic Tools
# ---------------------------------------------------------------------------


@mcp.tool
def get_past_topics(limit: int = 20) -> str:
    """
    Retrieve past story topics to avoid repetition when creating a new story.
    Requires determine_language to be called first.
    Call this BEFORE writing a new story so you can choose a fresh topic.

    limit : Maximum number of past topics to return (default 20, most recent first).
    """
    lang = session.lang.code
    topics = get_past_topics_db(lang, limit)

    if not topics:
        return "No past topics recorded yet. You are free to choose any topic."

    lines = ["Past story topics (most recent first):"]
    for t in topics:
        line = f"- {t['topic']}"
        if t["summary"]:
            line += f": {t['summary']}"
        lines.append(line)
    return "\n".join(lines)


@mcp.tool
def save_story_topic(topic: str, summary: str = "") -> str:
    """
    Save the topic of a story you just created, so future stories can avoid repeating the same topic.
    Requires determine_language to be called first.
    Call this AFTER creating a story.

    topic   : A short label for the story's topic (e.g. "weekend picnic", "space exploration").
    summary : Optional one-sentence summary of the story's plot.
    """
    lang = session.lang.code
    topic_text = topic.strip()
    if not topic_text:
        return "No topic provided."
    topic_id = save_story_topic_db(lang, topic_text, summary.strip())
    return f"Topic saved (id={topic_id}): {topic_text}"

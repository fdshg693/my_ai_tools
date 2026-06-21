"""物語の話題の SQLite アクセス。"""

from dynamic_prompt.repo.sqlite_repo.connection import _connect_db


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
        {
            "id": r["id"],
            "topic": r["topic"],
            "summary": r["summary"],
            "created_at": r["created_at"],
        }
        for r in rows
    ]


class SqliteTopicRepo:
    """話題の SQLite リポジトリ。"""

    def save_topic(self, lang: str, topic: str, summary: str = "") -> int:
        return save_story_topic_db(lang, topic, summary)

    def list_recent(self, lang: str, limit: int = 20) -> list[dict]:
        return get_past_topics_db(lang, limit)

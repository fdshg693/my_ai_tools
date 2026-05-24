"""story_topics の単体テスト — 保存・取得・言語フィルタ・件数制限。"""

from dynamic_prompt.database import (
    _connect_db,
    get_past_topics_db,
    save_story_topic_db,
)


class TestSaveStoryTopic:
    def test_saves_and_returns_id(self):
        topic_id = save_story_topic_db("en", "weekend picnic", "A family goes on a picnic.")
        assert topic_id is not None
        assert isinstance(topic_id, int)

    def test_saved_data_in_db(self):
        save_story_topic_db("en", "space exploration", "An astronaut visits Mars.")
        with _connect_db() as db:
            row = db.execute(
                "SELECT lang, topic, summary FROM story_topics WHERE topic = ?",
                ("space exploration",),
            ).fetchone()
        assert (row["lang"], row["topic"], row["summary"]) == (
            "en",
            "space exploration",
            "An astronaut visits Mars.",
        )

    def test_allows_duplicate_topics(self):
        """同じ話題を複数回保存できること（別の物語で同じ話題を使う可能性）。"""
        id1 = save_story_topic_db("en", "cooking", "")
        id2 = save_story_topic_db("en", "cooking", "")
        assert id1 != id2

    def test_empty_summary_defaults(self):
        save_story_topic_db("fr", "travel", "")
        with _connect_db() as db:
            row = db.execute(
                "SELECT summary FROM story_topics WHERE topic = 'travel'",
            ).fetchone()
        assert row[0] == ""


class TestGetPastTopics:
    def test_returns_empty_when_no_topics(self):
        assert get_past_topics_db("en") == []

    def test_returns_saved_topics(self):
        save_story_topic_db("en", "cooking", "Chef makes pasta.")
        save_story_topic_db("en", "adventure", "A hike in the mountains.")
        topics = get_past_topics_db("en")
        assert len(topics) == 2
        topic_names = [t["topic"] for t in topics]
        assert "cooking" in topic_names
        assert "adventure" in topic_names

    def test_most_recent_first(self):
        save_story_topic_db("en", "first", "")
        save_story_topic_db("en", "second", "")
        topics = get_past_topics_db("en")
        assert topics[0]["topic"] == "second"
        assert topics[1]["topic"] == "first"

    def test_filters_by_language(self):
        save_story_topic_db("en", "english topic", "")
        save_story_topic_db("fr", "french topic", "")
        en_topics = get_past_topics_db("en")
        fr_topics = get_past_topics_db("fr")
        assert len(en_topics) == 1
        assert en_topics[0]["topic"] == "english topic"
        assert len(fr_topics) == 1
        assert fr_topics[0]["topic"] == "french topic"

    def test_respects_limit(self):
        for i in range(10):
            save_story_topic_db("en", f"topic {i}", "")
        topics = get_past_topics_db("en", limit=3)
        assert len(topics) == 3

    def test_result_structure(self):
        save_story_topic_db("en", "mystery", "A detective solves a case.")
        topics = get_past_topics_db("en")
        t = topics[0]
        assert "id" in t
        assert t["topic"] == "mystery"
        assert t["summary"] == "A detective solves a case."
        assert "created_at" in t

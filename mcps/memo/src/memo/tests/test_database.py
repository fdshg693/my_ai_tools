"""DB 操作の単体テスト (CRUD + タイトル部分一致検索)。"""

from memo.database import (
    create_memo_db,
    delete_memo_db,
    get_memo_db,
    list_memos_db,
    search_memos_db,
    update_memo_db,
)


def test_create_and_get():
    memo = create_memo_db("買い物リスト", "牛乳と卵を買う")
    assert memo["id"] > 0
    assert memo["title"] == "買い物リスト"
    assert memo["summary"] == "牛乳と卵を買う"
    assert memo["created_at"]
    assert memo["updated_at"]

    fetched = get_memo_db(memo["id"])
    assert fetched == memo


def test_get_missing_returns_none():
    assert get_memo_db(9999) is None


def test_create_with_default_summary():
    memo = create_memo_db("タイトルのみ")
    assert memo["summary"] == ""


def test_list_orders_newest_first():
    a = create_memo_db("A")
    b = create_memo_db("B")
    c = create_memo_db("C")
    memos = list_memos_db()
    ids = [m["id"] for m in memos]
    # updated_at が同値の場合は id 降順で新しい順になる
    assert ids == [c["id"], b["id"], a["id"]]


def test_list_limit():
    for i in range(5):
        create_memo_db(f"memo-{i}")
    assert len(list_memos_db(limit=3)) == 3


def test_search_partial_title_match():
    create_memo_db("会議メモ 2026", "四半期レビュー")
    create_memo_db("買い物メモ", "週末の買い物")
    create_memo_db("旅行計画", "京都へ")

    results = search_memos_db("メモ")
    titles = {m["title"] for m in results}
    assert titles == {"会議メモ 2026", "買い物メモ"}


def test_search_is_case_insensitive():
    create_memo_db("Meeting Notes", "")
    results = search_memos_db("meeting")
    assert len(results) == 1
    assert results[0]["title"] == "Meeting Notes"


def test_search_does_not_match_summary():
    create_memo_db("タイトル", "本文に検索語ピザを含む")
    assert search_memos_db("ピザ") == []


def test_search_escapes_like_wildcards():
    create_memo_db("100%達成", "")
    create_memo_db("達成度", "")
    # '%' はリテラル扱いされ、全件マッチにならない
    results = search_memos_db("100%")
    assert len(results) == 1
    assert results[0]["title"] == "100%達成"


def test_search_no_match():
    create_memo_db("foo", "")
    assert search_memos_db("zzz") == []


def test_update_changes_fields():
    memo = create_memo_db("旧タイトル", "旧概要")
    updated = update_memo_db(memo["id"], title="新タイトル", summary="新概要")
    assert updated["title"] == "新タイトル"
    assert updated["summary"] == "新概要"
    assert updated["created_at"] == memo["created_at"]


def test_update_partial_only_title():
    memo = create_memo_db("旧タイトル", "概要そのまま")
    updated = update_memo_db(memo["id"], title="新タイトル")
    assert updated["title"] == "新タイトル"
    assert updated["summary"] == "概要そのまま"


def test_update_missing_returns_none():
    assert update_memo_db(9999, title="x") is None


def test_delete():
    memo = create_memo_db("消す", "")
    assert delete_memo_db(memo["id"]) is True
    assert get_memo_db(memo["id"]) is None


def test_delete_missing_returns_false():
    assert delete_memo_db(9999) is False

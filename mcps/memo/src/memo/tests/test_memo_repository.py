"""repository.memo の単体テスト (CRUD + タイトル部分一致検索 + ユーザー分離 + admin 特権)。"""

from memo.infra.database import ADMIN_USER, OTHERS_CATEGORY
from memo.repository.memo import (
    count_memos_db,
    create_memo_db,
    delete_memo_db,
    get_memo_db,
    list_categories_db,
    list_memos_db,
    normalize_category,
    search_memos_db,
    update_memo_db,
)

ALICE = "alice"
BOB = "bob"


def test_create_and_get():
    memo = create_memo_db(ALICE, "買い物リスト", "牛乳と卵を買う")
    assert memo["id"] > 0
    assert memo["user"] == ALICE
    assert memo["title"] == "買い物リスト"
    assert memo["summary"] == "牛乳と卵を買う"
    assert memo["created_at"]
    assert memo["updated_at"]

    fetched = get_memo_db(ALICE, memo["id"])
    assert fetched == memo


def test_get_missing_returns_none():
    assert get_memo_db(ALICE, 9999) is None


def test_create_with_default_summary():
    memo = create_memo_db(ALICE, "タイトルのみ")
    assert memo["summary"] == ""


def test_list_orders_newest_first():
    a = create_memo_db(ALICE, "A")
    b = create_memo_db(ALICE, "B")
    c = create_memo_db(ALICE, "C")
    memos = list_memos_db(ALICE)
    ids = [m["id"] for m in memos]
    # updated_at が同値の場合は id 降順で新しい順になる
    assert ids == [c["id"], b["id"], a["id"]]


def test_list_limit():
    for i in range(5):
        create_memo_db(ALICE, f"memo-{i}")
    assert len(list_memos_db(ALICE, limit=3)) == 3


def test_list_offset_paginates():
    created = [create_memo_db(ALICE, f"memo-{i}") for i in range(5)]
    # 新しい順 (id 降順) なので末尾が先頭
    newest_first = [m["id"] for m in reversed(created)]
    page1 = [m["id"] for m in list_memos_db(ALICE, limit=2, offset=0)]
    page2 = [m["id"] for m in list_memos_db(ALICE, limit=2, offset=2)]
    page3 = [m["id"] for m in list_memos_db(ALICE, limit=2, offset=4)]
    assert page1 == newest_first[0:2]
    assert page2 == newest_first[2:4]
    assert page3 == newest_first[4:5]  # 最終ページは1件


def test_count_only_own_memos():
    create_memo_db(ALICE, "alice-1")
    create_memo_db(ALICE, "alice-2")
    create_memo_db(BOB, "bob-1")
    assert count_memos_db(ALICE) == 2
    assert count_memos_db(BOB) == 1


def test_count_admin_counts_all():
    create_memo_db(ALICE, "alice-1")
    create_memo_db(BOB, "bob-1")
    create_memo_db("", "orphan-1")
    assert count_memos_db(ADMIN_USER, is_admin=True) == 3


def test_search_partial_title_match():
    create_memo_db(ALICE, "会議メモ 2026", "四半期レビュー")
    create_memo_db(ALICE, "買い物メモ", "週末の買い物")
    create_memo_db(ALICE, "旅行計画", "京都へ")

    results = search_memos_db(ALICE, ["メモ"])
    titles = {m["title"] for m in results}
    assert titles == {"会議メモ 2026", "買い物メモ"}


def test_search_annotates_matched_keyword():
    create_memo_db(ALICE, "会議メモ", "")
    results = search_memos_db(ALICE, ["メモ"])
    assert results[0]["matched_keywords"] == ["メモ"]


def test_search_multiple_keywords_or():
    create_memo_db(ALICE, "会議メモ", "")
    create_memo_db(ALICE, "買い物リスト", "")
    create_memo_db(ALICE, "旅行計画", "")

    results = search_memos_db(ALICE, ["メモ", "リスト"])
    titles = {m["title"] for m in results}
    assert titles == {"会議メモ", "買い物リスト"}


def test_search_matched_keywords_per_memo():
    create_memo_db(ALICE, "会議メモのリスト", "")  # 両方に一致
    create_memo_db(ALICE, "買い物メモ", "")  # メモ のみ
    create_memo_db(ALICE, "やることリスト", "")  # リスト のみ

    by_title = {
        m["title"]: m["matched_keywords"] for m in search_memos_db(ALICE, ["メモ", "リスト"])
    }
    assert by_title["会議メモのリスト"] == ["メモ", "リスト"]
    assert by_title["買い物メモ"] == ["メモ"]
    assert by_title["やることリスト"] == ["リスト"]


def test_search_is_case_insensitive():
    create_memo_db(ALICE, "Meeting Notes", "")
    results = search_memos_db(ALICE, ["meeting"])
    assert len(results) == 1
    assert results[0]["title"] == "Meeting Notes"


def test_search_does_not_match_summary():
    create_memo_db(ALICE, "タイトル", "本文に検索語ピザを含む")
    assert search_memos_db(ALICE, ["ピザ"]) == []


def test_search_escapes_like_wildcards():
    create_memo_db(ALICE, "100%達成", "")
    create_memo_db(ALICE, "達成度", "")
    # '%' はリテラル扱いされ、全件マッチにならない
    results = search_memos_db(ALICE, ["100%"])
    assert len(results) == 1
    assert results[0]["title"] == "100%達成"


def test_search_no_match():
    create_memo_db(ALICE, "foo", "")
    assert search_memos_db(ALICE, ["zzz"]) == []


def test_search_empty_keywords():
    create_memo_db(ALICE, "foo", "")
    assert search_memos_db(ALICE, []) == []


def test_update_changes_fields():
    memo = create_memo_db(ALICE, "旧タイトル", "旧概要")
    updated = update_memo_db(ALICE, memo["id"], title="新タイトル", summary="新概要")
    assert updated["title"] == "新タイトル"
    assert updated["summary"] == "新概要"
    assert updated["created_at"] == memo["created_at"]


def test_update_partial_only_title():
    memo = create_memo_db(ALICE, "旧タイトル", "概要そのまま")
    updated = update_memo_db(ALICE, memo["id"], title="新タイトル")
    assert updated["title"] == "新タイトル"
    assert updated["summary"] == "概要そのまま"


def test_update_missing_returns_none():
    assert update_memo_db(ALICE, 9999, title="x") is None


def test_delete():
    memo = create_memo_db(ALICE, "消す", "")
    assert delete_memo_db(ALICE, memo["id"]) is True
    assert get_memo_db(ALICE, memo["id"]) is None


def test_delete_missing_returns_false():
    assert delete_memo_db(ALICE, 9999) is False


# ---------------------------------------------------------------------------
# ユーザー分離: 他ユーザーのメモは読み取りも含めて一切操作できない
# ---------------------------------------------------------------------------


def test_get_other_users_memo_returns_none():
    memo = create_memo_db(ALICE, "alice の秘密", "")
    # bob からは存在しないものとして扱われる
    assert get_memo_db(BOB, memo["id"]) is None


def test_list_only_own_memos():
    create_memo_db(ALICE, "alice-1")
    create_memo_db(ALICE, "alice-2")
    create_memo_db(BOB, "bob-1")

    alice_titles = {m["title"] for m in list_memos_db(ALICE)}
    bob_titles = {m["title"] for m in list_memos_db(BOB)}
    assert alice_titles == {"alice-1", "alice-2"}
    assert bob_titles == {"bob-1"}


def test_search_only_own_memos():
    create_memo_db(ALICE, "共有メモ", "")
    create_memo_db(BOB, "共有メモ", "")

    results = search_memos_db(BOB, ["共有"])
    assert len(results) == 1
    assert results[0]["user"] == BOB


def test_update_other_users_memo_returns_none():
    memo = create_memo_db(ALICE, "alice のメモ", "元の概要")
    # bob による更新は拒否される
    assert update_memo_db(BOB, memo["id"], title="改ざん") is None
    # alice 側は変更されていない
    assert get_memo_db(ALICE, memo["id"])["title"] == "alice のメモ"


def test_delete_other_users_memo_returns_false():
    memo = create_memo_db(ALICE, "alice のメモ", "")
    # bob による削除は拒否される
    assert delete_memo_db(BOB, memo["id"]) is False
    # alice 側には残っている
    assert get_memo_db(ALICE, memo["id"]) is not None


# ---------------------------------------------------------------------------
# admin 特権: is_admin=True で全ユーザー (user='' の孤立メモ含む) を操作できる
# ---------------------------------------------------------------------------


def test_admin_get_any_users_memo():
    memo = create_memo_db(ALICE, "alice の秘密", "")
    # admin は所有者を問わず取得できる
    fetched = get_memo_db(ADMIN_USER, memo["id"], is_admin=True)
    assert fetched is not None
    assert fetched["user"] == ALICE


def test_admin_get_orphan_memo():
    # user='' の孤立メモ (旧 DB からの移行など) も admin は取得できる
    orphan = create_memo_db("", "孤立メモ", "")
    assert get_memo_db(ADMIN_USER, orphan["id"], is_admin=True) is not None
    # 通常ユーザーからは見えない
    assert get_memo_db(ALICE, orphan["id"]) is None


def test_admin_list_all_users_memos():
    create_memo_db(ALICE, "alice-1")
    create_memo_db(BOB, "bob-1")
    create_memo_db("", "orphan-1")
    titles = {m["title"] for m in list_memos_db(ADMIN_USER, is_admin=True)}
    assert titles == {"alice-1", "bob-1", "orphan-1"}


def test_admin_search_all_users_memos():
    create_memo_db(ALICE, "共有メモ", "")
    create_memo_db(BOB, "共有メモ", "")
    results = search_memos_db(ADMIN_USER, ["共有"], is_admin=True)
    assert {m["user"] for m in results} == {ALICE, BOB}


def test_admin_update_any_users_memo():
    memo = create_memo_db(ALICE, "alice のメモ", "元")
    updated = update_memo_db(ADMIN_USER, memo["id"], title="admin が更新", is_admin=True)
    assert updated["title"] == "admin が更新"
    # 所有者は変わらない
    assert updated["user"] == ALICE


def test_admin_delete_any_users_memo():
    memo = create_memo_db(ALICE, "alice のメモ", "")
    assert delete_memo_db(ADMIN_USER, memo["id"], is_admin=True) is True
    assert get_memo_db(ALICE, memo["id"]) is None


# ---------------------------------------------------------------------------
# カテゴリ: 未指定は OTHERS・大文字正規化・同一カテゴリでの絞り込み
# ---------------------------------------------------------------------------


def test_normalize_category_rules():
    assert normalize_category(None) == OTHERS_CATEGORY
    assert normalize_category("") == OTHERS_CATEGORY
    assert normalize_category("   ") == OTHERS_CATEGORY
    assert normalize_category("  work ") == "WORK"
    assert normalize_category("Work") == "WORK"


def test_create_defaults_to_others():
    memo = create_memo_db(ALICE, "カテゴリなし")
    assert memo["category"] == OTHERS_CATEGORY


def test_create_normalizes_category():
    memo = create_memo_db(ALICE, "仕事メモ", "", category="work")
    assert memo["category"] == "WORK"
    # 保存後も get で同じ値が読める
    assert get_memo_db(ALICE, memo["id"])["category"] == "WORK"


def test_list_filters_by_category():
    create_memo_db(ALICE, "w1", "", category="work")
    create_memo_db(ALICE, "w2", "", category="WORK")
    create_memo_db(ALICE, "p1", "", category="private")
    create_memo_db(ALICE, "o1")  # OTHERS

    work = {m["title"] for m in list_memos_db(ALICE, category="work")}
    assert work == {"w1", "w2"}
    others = {m["title"] for m in list_memos_db(ALICE, category=None)}
    assert others == {"w1", "w2", "p1", "o1"}  # None は全カテゴリ
    just_others = {m["title"] for m in list_memos_db(ALICE, category="OTHERS")}
    assert just_others == {"o1"}


def test_count_filters_by_category():
    create_memo_db(ALICE, "w1", "", category="work")
    create_memo_db(ALICE, "w2", "", category="work")
    create_memo_db(ALICE, "o1")
    assert count_memos_db(ALICE, category="WORK") == 2
    assert count_memos_db(ALICE) == 3


def test_search_filters_by_category():
    create_memo_db(ALICE, "会議メモ", "", category="work")
    create_memo_db(ALICE, "買い物メモ", "", category="private")

    results = search_memos_db(ALICE, ["メモ"], category="work")
    assert {m["title"] for m in results} == {"会議メモ"}
    # カテゴリ未指定なら両方
    assert len(search_memos_db(ALICE, ["メモ"])) == 2


def test_update_changes_category():
    memo = create_memo_db(ALICE, "メモ", "", category="work")
    updated = update_memo_db(ALICE, memo["id"], category="private")
    assert updated["category"] == "PRIVATE"
    # title/summary は据え置き
    assert updated["title"] == "メモ"


def test_update_without_category_keeps_existing():
    memo = create_memo_db(ALICE, "メモ", "概要", category="work")
    updated = update_memo_db(ALICE, memo["id"], summary="概要を更新")
    assert updated["category"] == "WORK"  # category 省略 → 変更しない


def test_update_empty_category_resets_to_others():
    memo = create_memo_db(ALICE, "メモ", "", category="work")
    updated = update_memo_db(ALICE, memo["id"], category="")
    assert updated["category"] == OTHERS_CATEGORY


def test_admin_search_filters_by_category():
    create_memo_db(ALICE, "共有メモ", "", category="work")
    create_memo_db(BOB, "共有メモ", "", category="private")
    results = search_memos_db(ADMIN_USER, ["共有"], is_admin=True, category="work")
    assert {m["user"] for m in results} == {ALICE}


def test_list_categories_distinct_sorted_per_user():
    create_memo_db(ALICE, "a1", "", category="work")
    create_memo_db(ALICE, "a2", "", category="WORK")  # 重複は1つに
    create_memo_db(ALICE, "a3", "", category="private")
    create_memo_db(ALICE, "a4")  # OTHERS
    create_memo_db(BOB, "b1", "", category="finance")  # 他人のは出ない

    assert list_categories_db(ALICE) == ["OTHERS", "PRIVATE", "WORK"]  # 名前順
    assert list_categories_db(BOB) == ["FINANCE"]


def test_list_categories_empty_when_no_memos():
    assert list_categories_db(ALICE) == []


def test_list_categories_admin_spans_all_users():
    create_memo_db(ALICE, "a1", "", category="work")
    create_memo_db(BOB, "b1", "", category="finance")
    assert list_categories_db(ADMIN_USER, is_admin=True) == ["FINANCE", "WORK"]

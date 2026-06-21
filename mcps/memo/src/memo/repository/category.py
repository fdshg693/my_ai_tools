"""カテゴリのデータアクセス (正規化ルール + メモが持つカテゴリ一覧)。

カテゴリは現状 ``memos.category`` 列に格納される「メモの属性」だが、正規化ルール
(canonical 形式の定義) と「存在するカテゴリの列挙」はメモ行そのものの CRUD とは
関心が別なので、将来のカテゴリ機能 (専用テーブル・リネーム/マージ等) の土台として
このファイルに切り出す。

``repository.memo`` がここの ``normalize_category`` を取り込む (memo → category の
一方向依存)。循環参照を避けるため、ここでは ``repository.memo`` を一切 import せず、
``list_categories_db`` の user 絞り込みは ``infra`` だけに依存して自前で組み立てる。
ここでは「誰が admin か」は判定しない (呼び出し元が解決した ``is_admin`` を受け取る)。
"""

from memo.infra.database import OTHERS_CATEGORY, _connect_db


def normalize_category(category: str | None) -> str:
    """カテゴリ名を正規化する: 前後の空白を除去し大文字化する。

    ``None`` や空文字 (空白のみ含む) は既定カテゴリ ``OTHERS`` に寄せる。
    大文字化することで ``work`` / ``Work`` / ``WORK`` を同一カテゴリとして
    保存・照合できる。書き込み (create/update) と検索フィルタの両方がこの
    ヘルパーを通すので、保存値と絞り込み条件が必ず一致する。
    """
    if category is None:
        return OTHERS_CATEGORY
    normalized = category.strip().upper()
    return normalized or OTHERS_CATEGORY


def list_categories_db(user: str, is_admin: bool = False) -> list[str]:
    """ユーザーのメモが持つカテゴリ一覧を重複なく名前順に返す。

    通常は ``user`` のメモが属するカテゴリだけ。``is_admin=True`` なら全ユーザー
    (``user=''`` の孤立メモ含む) のカテゴリ。メモが1件も無ければ空リスト。
    カテゴリは保存時に正規化済み (大文字) なので、ここでの再正規化は不要。
    """
    if is_admin:
        where, params = "", []
    else:
        where, params = "WHERE user = ?", [user]
    with _connect_db() as db:
        rows = db.execute(
            f"SELECT DISTINCT category FROM memos {where} ORDER BY category",
            params,
        ).fetchall()
    return [r["category"] for r in rows]

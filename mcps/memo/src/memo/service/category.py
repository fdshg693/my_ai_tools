"""カテゴリのドメイン操作 (現状はメモが持つカテゴリ一覧の取得のみ)。

``repository.category`` を包む薄い層。トランスポート端 (MCP の ``switch_user`` など)
は repository を直接呼ばず、この service 経由でカテゴリを取得する
(エッジ → service → repository の一方向を保つ)。将来カテゴリ自体のドメイン
ルール (リネーム/マージ等) が増えたら、その置き場所はここになる。

認可 (admin 判定) はここに入れない (呼び出し元が解決した ``is_admin`` を渡す)。
"""

from memo.repository.category import list_categories_db


def list_categories(user: str, is_admin: bool = False) -> list[str]:
    """ユーザーのメモが持つカテゴリ一覧を重複なく名前順に返す。

    通常は ``user`` のメモのカテゴリだけ。``is_admin=True`` なら全ユーザー分。
    """
    return list_categories_db(user, is_admin=is_admin)

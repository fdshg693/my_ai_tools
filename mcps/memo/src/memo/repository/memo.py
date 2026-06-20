"""メモ (``memos`` テーブル) のデータアクセス。

すべてのメモは作成したユーザー名 (``user``) を持ち、CRUD・検索は原則
``user`` で絞り込む。これにより、あるユーザーのメモは他ユーザーからは
読み取りも含めて一切アクセスできない (完全分離)。ただし ``is_admin=True``
を渡すと user 絞り込みを外し、全ユーザー (``user=''`` の孤立メモ含む) の
メモを操作対象にする (admin 特権)。

ここでは「誰が admin か」は判定しない。呼び出し元 (tools / authz) が解決した
``is_admin`` を受け取るだけの純粋なデータアクセス層。
"""

import sqlite3

from memo.infra.database import OTHERS_CATEGORY, _connect_db


def _row_to_dict(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "user": row["user"],
        "title": row["title"],
        "summary": row["summary"],
        "category": row["category"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


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


def _scope(memo_id: int, user: str, is_admin: bool) -> tuple[str, list]:
    """ID で1件のメモを指す WHERE 句片とパラメータを返す。

    通常は所有者 (``user``) でも絞り、他人のメモは対象外になる。
    ``is_admin=True`` は所有者を問わず ID だけで対象を指す (admin 特権)。
    get/update/delete はこのヘルパーで `is_admin` 分岐を1か所に集約する。
    """
    if is_admin:
        return "id = ?", [memo_id]
    return "id = ? AND user = ?", [memo_id, user]


def create_memo_db(
    user: str, title: str, summary: str = "", category: str | None = None
) -> dict:
    """メモを新規作成し、作成したレコードを返す。所有者は ``user``。

    ``category`` は ``normalize_category`` で正規化する (未指定は ``OTHERS``)。
    """
    with _connect_db() as db:
        cursor = db.execute(
            "INSERT INTO memos (user, title, summary, category) VALUES (?, ?, ?, ?)",
            (user, title, summary, normalize_category(category)),
        )
        memo_id = cursor.lastrowid
        row = db.execute("SELECT * FROM memos WHERE id = ?", (memo_id,)).fetchone()
    return _row_to_dict(row)


def get_memo_db(user: str, memo_id: int, is_admin: bool = False) -> dict | None:
    """ID でメモを1件取得する。

    通常は ``user`` が所有しない/存在しなければ None。``is_admin=True`` なら
    所有者を問わず ID だけで取得する。
    """
    where, params = _scope(memo_id, user, is_admin)
    with _connect_db() as db:
        row = db.execute(f"SELECT * FROM memos WHERE {where}", params).fetchone()
    return _row_to_dict(row) if row else None


def _base_filter(
    user: str, is_admin: bool, category: str | None
) -> tuple[list[str], list]:
    """user / category の絞り込み条件 (WHERE 句片の一覧とパラメータ) を組み立てる。

    通常は ``user`` で絞り、``is_admin=True`` なら所有者の絞り込みを外す。
    ``category`` を渡すとさらに正規化したカテゴリ一致で絞る (``None`` は全カテゴリ)。
    """
    clauses: list[str] = []
    params: list = []
    if not is_admin:
        clauses.append("user = ?")
        params.append(user)
    if category is not None:
        clauses.append("category = ?")
        params.append(normalize_category(category))
    return clauses, params


def list_memos_db(
    user: str,
    limit: int = 50,
    is_admin: bool = False,
    offset: int = 0,
    category: str | None = None,
) -> list[dict]:
    """メモを新しい順 (更新日時の降順) に取得する。

    通常は ``user`` のメモのみ。``is_admin=True`` なら全ユーザーのメモを返す。
    ``category`` を渡すと同一カテゴリのメモだけに絞る (``None`` は全カテゴリ)。
    ``offset`` で先頭から読み飛ばす件数を指定でき、``limit`` と組み合わせて
    ページングに使える。
    """
    clauses, params = _base_filter(user, is_admin, category)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with _connect_db() as db:
        rows = db.execute(
            f"SELECT * FROM memos {where} "
            "ORDER BY updated_at DESC, id DESC LIMIT ? OFFSET ?",
            [*params, limit, offset],
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def count_memos_db(
    user: str, is_admin: bool = False, category: str | None = None
) -> int:
    """メモの総件数を返す (ページング用)。

    通常は ``user`` のメモのみ数える。``is_admin=True`` なら全ユーザー分。
    ``category`` を渡すと同一カテゴリだけを数える (``None`` は全カテゴリ)。
    """
    clauses, params = _base_filter(user, is_admin, category)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with _connect_db() as db:
        row = db.execute(f"SELECT COUNT(*) AS n FROM memos {where}", params).fetchone()
    return row["n"]


def list_categories_db(user: str, is_admin: bool = False) -> list[str]:
    """ユーザーのメモが持つカテゴリ一覧を重複なく名前順に返す。

    通常は ``user`` のメモが属するカテゴリだけ。``is_admin=True`` なら全ユーザー
    (``user=''`` の孤立メモ含む) のカテゴリ。メモが1件も無ければ空リスト。
    カテゴリは保存時に正規化済み (大文字) なので、ここでの再正規化は不要。
    """
    clauses, params = _base_filter(user, is_admin, None)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with _connect_db() as db:
        rows = db.execute(
            f"SELECT DISTINCT category FROM memos {where} ORDER BY category",
            params,
        ).fetchall()
    return [r["category"] for r in rows]


def _escape_like(keyword: str) -> str:
    """LIKE のワイルドカード (``%`` ``_``) と ``\\`` をリテラル化する。"""
    return keyword.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def search_memos_db(
    user: str,
    keywords: list[str],
    limit: int = 50,
    is_admin: bool = False,
    category: str | None = None,
) -> list[dict]:
    """メモをタイトルの部分一致で検索する (大文字小文字を区別しない)。

    通常は ``user`` のメモのみ、``is_admin=True`` なら全ユーザーのメモが対象。
    ``category`` を渡すと同一カテゴリのメモだけに絞る (``None`` は全カテゴリ)。
    複数キーワードはいずれかに一致したメモを返す (OR 検索)。各メモには
    どのキーワードに一致したかを示す ``matched_keywords`` を付与する。

    LIKE のワイルドカード (``%`` ``_``) はリテラルとして扱うため ESCAPE でエスケープする。
    """
    if not keywords:
        return []
    title_clause = " OR ".join("title LIKE ? ESCAPE '\\'" for _ in keywords)
    clauses, params = _base_filter(user, is_admin, category)
    clauses.append(f"({title_clause})")
    where = " AND ".join(clauses)
    params.extend(f"%{_escape_like(k)}%" for k in keywords)
    params.append(limit)
    with _connect_db() as db:
        rows = db.execute(
            f"SELECT * FROM memos WHERE {where} "
            "ORDER BY updated_at DESC, id DESC LIMIT ?",
            params,
        ).fetchall()

    results = []
    for r in rows:
        memo = _row_to_dict(r)
        title_lower = memo["title"].lower()
        # SQLite の LIKE と同じく ASCII の大文字小文字を区別せずに一致判定する
        memo["matched_keywords"] = [k for k in keywords if k.lower() in title_lower]
        results.append(memo)
    return results


def update_memo_db(
    user: str,
    memo_id: int,
    title: str | None = None,
    summary: str | None = None,
    is_admin: bool = False,
    category: str | None = None,
) -> dict | None:
    """メモを更新する。指定したフィールドのみ変更し、更新後のレコードを返す。

    通常は ``user`` が所有するメモのみ更新でき、対象が存在しない/他人のものなら
    None。``is_admin=True`` なら所有者を問わず ID で更新する。
    title / summary / category がすべて None の場合は更新せず既存レコードを返す。
    ``category`` を渡すと ``normalize_category`` で正規化して設定する。
    """
    where, scope_params = _scope(memo_id, user, is_admin)
    with _connect_db() as db:
        row = db.execute(f"SELECT * FROM memos WHERE {where}", scope_params).fetchone()
        if row is None:
            return None

        fields = []
        params: list = []
        if title is not None:
            fields.append("title = ?")
            params.append(title)
        if summary is not None:
            fields.append("summary = ?")
            params.append(summary)
        if category is not None:
            fields.append("category = ?")
            params.append(normalize_category(category))

        if fields:
            fields.append("updated_at = datetime('now')")
            db.execute(
                f"UPDATE memos SET {', '.join(fields)} WHERE {where}",
                params + scope_params,
            )
            row = db.execute(
                f"SELECT * FROM memos WHERE {where}", scope_params
            ).fetchone()
    return _row_to_dict(row)


def delete_memo_db(user: str, memo_id: int, is_admin: bool = False) -> bool:
    """メモを削除する。削除できたら True、対象が無ければ False。

    通常は ``user`` が所有するメモのみ。``is_admin=True`` なら所有者を問わない。
    """
    where, params = _scope(memo_id, user, is_admin)
    with _connect_db() as db:
        cursor = db.execute(f"DELETE FROM memos WHERE {where}", params)
        deleted = cursor.rowcount > 0
    return deleted

"""メモ (``memos`` テーブル) のデータアクセス。

すべてのメモは作成したユーザー名 (``user``) を持ち、CRUD・検索は常に
``user`` で絞り込む。これにより、あるユーザーのメモは他ユーザーからは
読み取りも含めて一切アクセスできない (完全分離)。admin も例外ではなく、
他人のメモは操作できない (admin はユーザー台帳を管理できるだけの通常ユーザー)。

ここでは認可も特権判定も行わない。呼び出し元 (tools / authz) が解決した
接続ユーザー ``user`` を受け取るだけの純粋なデータアクセス層。
"""

import sqlite3

from memo.infra.database import _connect_db
from memo.repository.category import normalize_category


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


def _scope(memo_id: int, user: str) -> tuple[str, list]:
    """ID と所有者でメモ1件を指す WHERE 句片とパラメータを返す。

    常に所有者 (``user``) でも絞るので、他人のメモは対象外になる。
    get/update/delete はこのヘルパーで対象の指定を1か所に集約する。
    """
    return "id = ? AND user = ?", [memo_id, user]


def create_memo_db(
    user: str, title: str, summary: str = "", category: str | None = None
) -> dict:
    """メモを新規作成し、作成したレコードを返す。所有者は ``user``。

    ``category`` は ``normalize_category`` で正規化する (未指定は ``OTHERS``)。
    カテゴリが登録済みかの検証は service 層が行う (ここは permissive)。
    """
    with _connect_db() as db:
        cursor = db.execute(
            "INSERT INTO memos (user, title, summary, category) VALUES (?, ?, ?, ?)",
            (user, title, summary, normalize_category(category)),
        )
        memo_id = cursor.lastrowid
        row = db.execute("SELECT * FROM memos WHERE id = ?", (memo_id,)).fetchone()
    return _row_to_dict(row)


def get_memo_db(user: str, memo_id: int) -> dict | None:
    """ID でメモを1件取得する (``user`` が所有しない/存在しなければ None)。"""
    where, params = _scope(memo_id, user)
    with _connect_db() as db:
        row = db.execute(f"SELECT * FROM memos WHERE {where}", params).fetchone()
    return _row_to_dict(row) if row else None


def _base_filter(user: str, category: str | None) -> tuple[list[str], list]:
    """user / category の絞り込み条件 (WHERE 句片の一覧とパラメータ) を組み立てる。

    常に ``user`` で絞る。``category`` を渡すとさらに正規化したカテゴリ一致で
    絞る (``None`` は全カテゴリ)。
    """
    clauses: list[str] = ["user = ?"]
    params: list = [user]
    if category is not None:
        clauses.append("category = ?")
        params.append(normalize_category(category))
    return clauses, params


def list_memos_db(
    user: str,
    limit: int = 50,
    offset: int = 0,
    category: str | None = None,
) -> list[dict]:
    """メモを新しい順 (更新日時の降順) に取得する (``user`` のメモのみ)。

    ``category`` を渡すと同一カテゴリのメモだけに絞る (``None`` は全カテゴリ)。
    ``offset`` で先頭から読み飛ばす件数を指定でき、``limit`` と組み合わせて
    ページングに使える。
    """
    clauses, params = _base_filter(user, category)
    where = " AND ".join(clauses)
    with _connect_db() as db:
        rows = db.execute(
            f"SELECT * FROM memos WHERE {where} "
            "ORDER BY updated_at DESC, id DESC LIMIT ? OFFSET ?",
            [*params, limit, offset],
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def count_memos_db(user: str, category: str | None = None) -> int:
    """メモの総件数を返す (``user`` のメモのみ。ページング用)。

    ``category`` を渡すと同一カテゴリだけを数える (``None`` は全カテゴリ)。
    """
    clauses, params = _base_filter(user, category)
    where = " AND ".join(clauses)
    with _connect_db() as db:
        row = db.execute(
            f"SELECT COUNT(*) AS n FROM memos WHERE {where}", params
        ).fetchone()
    return row["n"]


def _escape_like(keyword: str) -> str:
    """LIKE のワイルドカード (``%`` ``_``) と ``\\`` をリテラル化する。"""
    return keyword.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def search_memos_db(
    user: str,
    keywords: list[str],
    limit: int = 50,
    category: str | None = None,
) -> list[dict]:
    """メモをタイトルの部分一致で検索する (大文字小文字を区別しない)。

    ``user`` のメモのみが対象。``category`` を渡すと同一カテゴリのメモだけに
    絞る (``None`` は全カテゴリ)。複数キーワードはいずれかに一致したメモを返す
    (OR 検索)。各メモには ``matched_keywords`` を付与する。

    LIKE のワイルドカード (``%`` ``_``) はリテラルとして扱うため ESCAPE でエスケープする。
    """
    if not keywords:
        return []
    title_clause = " OR ".join("title LIKE ? ESCAPE '\\'" for _ in keywords)
    clauses, params = _base_filter(user, category)
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
    category: str | None = None,
) -> dict | None:
    """メモを更新する。指定したフィールドのみ変更し、更新後のレコードを返す。

    ``user`` が所有するメモのみ更新でき、対象が存在しない/他人のものなら None。
    title / summary / category がすべて None の場合は更新せず既存レコードを返す。
    ``category`` を渡すと ``normalize_category`` で正規化して設定する
    (登録済みかの検証は service 層が行う)。
    """
    where, scope_params = _scope(memo_id, user)
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


def delete_memo_db(user: str, memo_id: int) -> bool:
    """メモを削除する。削除できたら True、対象が無ければ False。

    ``user`` が所有するメモのみ削除できる (他人のメモは対象外)。
    """
    where, params = _scope(memo_id, user)
    with _connect_db() as db:
        cursor = db.execute(f"DELETE FROM memos WHERE {where}", params)
        deleted = cursor.rowcount > 0
    return deleted

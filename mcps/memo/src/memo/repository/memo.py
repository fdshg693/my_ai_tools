"""メモ (``memos`` テーブル) のデータアクセス。

すべてのメモは作成したユーザーの不変 ID (``user_id``) を持ち、CRUD・検索は常に
``user_id`` で絞り込む。これにより、あるユーザーのメモは他ユーザーからは
読み取りも含めて一切アクセスできない (完全分離)。admin も例外ではなく、
他人のメモは操作できない (admin はユーザー台帳を管理できるだけの通常ユーザー)。
メモは ID に紐づくので、所有者のユーザー名 (name) を変更してもこの層の更新は不要。

ここでは認可も特権判定も行わない。呼び出し元 (tools / web / service) が解決した
接続ユーザーの ``user_id`` を受け取るだけの純粋なデータアクセス層。
"""

import sqlite3

from memo.infra.database import _connect_db
from memo.repository.category import normalize_category


def _row_to_dict(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "user_id": row["user_id"],
        "title": row["title"],
        "summary": row["summary"],
        "category": row["category"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _scope(memo_id: int, user_id: int) -> tuple[str, list]:
    """ID と所有者でメモ1件を指す WHERE 句片とパラメータを返す。

    常に所有者 (``user_id``) でも絞るので、他人のメモは対象外になる。
    get/update/delete はこのヘルパーで対象の指定を1か所に集約する。
    """
    return "id = ? AND user_id = ?", [memo_id, user_id]


def create_memo_db(
    user_id: int, title: str, summary: str = "", category: str | None = None
) -> dict:
    """メモを新規作成し、作成したレコードを返す。所有者は ``user_id``。

    ``category`` は ``normalize_category`` で正規化する (未指定は ``OTHERS``)。
    カテゴリが登録済みかの検証は service 層が行う (ここは permissive)。
    """
    with _connect_db() as db:
        cursor = db.execute(
            "INSERT INTO memos (user_id, title, summary, category) VALUES (?, ?, ?, ?)",
            (user_id, title, summary, normalize_category(category)),
        )
        memo_id = cursor.lastrowid
        row = db.execute("SELECT * FROM memos WHERE id = ?", (memo_id,)).fetchone()
    return _row_to_dict(row)


def get_memo_db(user_id: int, memo_id: int) -> dict | None:
    """ID でメモを1件取得する (``user_id`` が所有しない/存在しなければ None)。"""
    where, params = _scope(memo_id, user_id)
    with _connect_db() as db:
        row = db.execute(f"SELECT * FROM memos WHERE {where}", params).fetchone()
    return _row_to_dict(row) if row else None


def _base_filter(user_id: int, category: str | None) -> tuple[list[str], list]:
    """user_id / category の絞り込み条件 (WHERE 句片の一覧とパラメータ) を組み立てる。

    常に ``user_id`` で絞る。``category`` を渡すとさらに正規化したカテゴリ一致で
    絞る (``None`` は全カテゴリ)。
    """
    clauses: list[str] = ["user_id = ?"]
    params: list = [user_id]
    if category is not None:
        clauses.append("category = ?")
        params.append(normalize_category(category))
    return clauses, params


def list_memos_db(
    user_id: int,
    limit: int = 50,
    offset: int = 0,
    category: str | None = None,
) -> list[dict]:
    """メモを新しい順 (更新日時の降順) に取得する (``user_id`` のメモのみ)。

    ``category`` を渡すと同一カテゴリのメモだけに絞る (``None`` は全カテゴリ)。
    ``offset`` で先頭から読み飛ばす件数を指定でき、``limit`` と組み合わせて
    ページングに使える。
    """
    clauses, params = _base_filter(user_id, category)
    where = " AND ".join(clauses)
    with _connect_db() as db:
        rows = db.execute(
            f"SELECT * FROM memos WHERE {where} "
            "ORDER BY updated_at DESC, id DESC LIMIT ? OFFSET ?",
            [*params, limit, offset],
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def count_memos_db(user_id: int, category: str | None = None) -> int:
    """メモの総件数を返す (``user_id`` のメモのみ。ページング用)。

    ``category`` を渡すと同一カテゴリだけを数える (``None`` は全カテゴリ)。
    """
    clauses, params = _base_filter(user_id, category)
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
    user_id: int,
    keywords: list[str],
    limit: int = 50,
    category: str | None = None,
) -> list[dict]:
    """メモをタイトルの部分一致で検索する (大文字小文字を区別しない)。

    ``user_id`` のメモのみが対象。``category`` を渡すと同一カテゴリのメモだけに
    絞る (``None`` は全カテゴリ)。複数キーワードはいずれかに一致したメモを返す
    (OR 検索)。各メモには ``matched_keywords`` を付与する。

    LIKE のワイルドカード (``%`` ``_``) はリテラルとして扱うため ESCAPE でエスケープする。
    """
    if not keywords:
        return []
    title_clause = " OR ".join("title LIKE ? ESCAPE '\\'" for _ in keywords)
    clauses, params = _base_filter(user_id, category)
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
    user_id: int,
    memo_id: int,
    title: str | None = None,
    summary: str | None = None,
    category: str | None = None,
) -> dict | None:
    """メモを更新する。指定したフィールドのみ変更し、更新後のレコードを返す。

    ``user_id`` が所有するメモのみ更新でき、対象が存在しない/他人のものなら None。
    title / summary / category がすべて None の場合は更新せず既存レコードを返す。
    ``category`` を渡すと ``normalize_category`` で正規化して設定する
    (登録済みかの検証は service 層が行う)。
    """
    where, scope_params = _scope(memo_id, user_id)
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


def delete_memo_db(user_id: int, memo_id: int) -> bool:
    """メモを削除する。削除できたら True、対象が無ければ False。

    ``user_id`` が所有するメモのみ削除できる (他人のメモは対象外)。紐づく埋め込み
    キャッシュ (``memo_embeddings``) は外部キーの ON DELETE CASCADE で DB が
    自動削除する (孤立行を残さない)。
    """
    where, params = _scope(memo_id, user_id)
    with _connect_db() as db:
        cursor = db.execute(f"DELETE FROM memos WHERE {where}", params)
        deleted = cursor.rowcount > 0
    return deleted

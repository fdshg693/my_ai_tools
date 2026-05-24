"""DB 接続とスキーマ管理、メモの CRUD・検索ヘルパー。

dynamic_prompt と同様、SQLite を WAL モードで使う。ツール呼び出しごとに
新しい接続を返す (`_connect_db`) ことで、FastMCP が複数スレッドからツールを
呼んでもスレッド安全を保つ。
"""

import os
import sqlite3
from pathlib import Path

DB_PATH = Path(os.environ.get("MEMO_DB_PATH", str(Path(__file__).parent / "memo.db")))


def init_db() -> None:
    """スキーマを作成する。サーバー起動時に1回だけ呼ぶ (冪等)。"""
    db = sqlite3.connect(DB_PATH)
    try:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("""
            CREATE TABLE IF NOT EXISTS memos (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                title      TEXT NOT NULL,
                summary    TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        db.commit()
    finally:
        db.close()


def _connect_db() -> sqlite3.Connection:
    """毎回新しい接続を返す。呼び出し側は `with _connect_db() as db:` で使うこと。"""
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    return db


def _row_to_dict(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "title": row["title"],
        "summary": row["summary"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


# ---------------------------------------------------------------------------
# CRUD helpers
# ---------------------------------------------------------------------------


def create_memo_db(title: str, summary: str = "") -> dict:
    """メモを新規作成し、作成したレコードを返す。"""
    with _connect_db() as db:
        cursor = db.execute(
            "INSERT INTO memos (title, summary) VALUES (?, ?)",
            (title, summary),
        )
        memo_id = cursor.lastrowid
        row = db.execute("SELECT * FROM memos WHERE id = ?", (memo_id,)).fetchone()
    return _row_to_dict(row)


def get_memo_db(memo_id: int) -> dict | None:
    """ID でメモを1件取得する。存在しなければ None。"""
    with _connect_db() as db:
        row = db.execute("SELECT * FROM memos WHERE id = ?", (memo_id,)).fetchone()
    return _row_to_dict(row) if row else None


def list_memos_db(limit: int = 50) -> list[dict]:
    """メモを新しい順 (更新日時の降順) に取得する。"""
    with _connect_db() as db:
        rows = db.execute(
            "SELECT * FROM memos ORDER BY updated_at DESC, id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def _escape_like(keyword: str) -> str:
    """LIKE のワイルドカード (``%`` ``_``) と ``\\`` をリテラル化する。"""
    return keyword.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def search_memos_db(keywords: list[str], limit: int = 50) -> list[dict]:
    """タイトルの部分一致でメモを検索する (大文字小文字を区別しない)。

    複数キーワードはいずれかに一致したメモを返す (OR 検索)。各メモには
    どのキーワードに一致したかを示す ``matched_keywords`` を付与する。

    LIKE のワイルドカード (``%`` ``_``) はリテラルとして扱うため ESCAPE でエスケープする。
    """
    if not keywords:
        return []
    clauses = " OR ".join("title LIKE ? ESCAPE '\\'" for _ in keywords)
    params: list = [f"%{_escape_like(k)}%" for k in keywords]
    params.append(limit)
    with _connect_db() as db:
        rows = db.execute(
            f"SELECT * FROM memos WHERE {clauses} "
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
    memo_id: int, title: str | None = None, summary: str | None = None
) -> dict | None:
    """メモを更新する。指定したフィールドのみ変更し、更新後のレコードを返す。

    対象 ID が存在しなければ None を返す。title と summary が両方 None の場合も
    更新対象なしとして既存レコードをそのまま返す。
    """
    with _connect_db() as db:
        row = db.execute("SELECT * FROM memos WHERE id = ?", (memo_id,)).fetchone()
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

        if fields:
            fields.append("updated_at = datetime('now')")
            params.append(memo_id)
            db.execute(
                f"UPDATE memos SET {', '.join(fields)} WHERE id = ?",
                params,
            )
        row = db.execute("SELECT * FROM memos WHERE id = ?", (memo_id,)).fetchone()
    return _row_to_dict(row)


def delete_memo_db(memo_id: int) -> bool:
    """メモを削除する。削除できたら True、対象が無ければ False。"""
    with _connect_db() as db:
        cursor = db.execute("DELETE FROM memos WHERE id = ?", (memo_id,))
        deleted = cursor.rowcount > 0
    return deleted

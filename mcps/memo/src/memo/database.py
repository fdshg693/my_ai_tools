"""DB 接続とスキーマ管理、メモの CRUD・検索ヘルパー。

dynamic_prompt と同様、SQLite を WAL モードで使う。ツール呼び出しごとに
新しい接続を返す (`_connect_db`) ことで、FastMCP が複数スレッドからツールを
呼んでもスレッド安全を保つ。

すべてのメモは作成したユーザー名 (``user``) を持ち、CRUD・検索はすべて
``user`` で絞り込む。これにより、あるユーザーのメモは他ユーザーからは
読み取りも含めて一切アクセスできない (完全分離)。
"""

import os
import sqlite3
from pathlib import Path

DB_PATH = Path(os.environ.get("MEMO_DB_PATH", str(Path(__file__).parent / "memo.db")))


def init_db() -> None:
    """スキーマを作成する。サーバー起動時に1回だけ呼ぶ (冪等)。

    ``user`` カラムを持たない既存 DB は ``ALTER TABLE`` で移行する
    (既存メモは ``user=''`` となり、どのユーザーからもアクセスできなくなる)。
    """
    db = sqlite3.connect(DB_PATH)
    try:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("""
            CREATE TABLE IF NOT EXISTS memos (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                user       TEXT NOT NULL,
                title      TEXT NOT NULL,
                summary    TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        # 既存 DB に user カラムが無ければ追加する (軽量マイグレーション)
        columns = {row[1] for row in db.execute("PRAGMA table_info(memos)")}
        if "user" not in columns:
            db.execute("ALTER TABLE memos ADD COLUMN user TEXT NOT NULL DEFAULT ''")
        # ユーザー単位の絞り込みを高速化する
        db.execute("CREATE INDEX IF NOT EXISTS idx_memos_user ON memos(user)")
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
        "user": row["user"],
        "title": row["title"],
        "summary": row["summary"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


# ---------------------------------------------------------------------------
# CRUD helpers
#
# すべての関数は第1引数に ``user`` を取り、その user が所有するメモだけを
# 対象にする。他ユーザーのメモを指定した get/update/delete は、存在を
# 漏らさないため「対象なし」(None / False) として扱う。
# ---------------------------------------------------------------------------


def create_memo_db(user: str, title: str, summary: str = "") -> dict:
    """メモを新規作成し、作成したレコードを返す。"""
    with _connect_db() as db:
        cursor = db.execute(
            "INSERT INTO memos (user, title, summary) VALUES (?, ?, ?)",
            (user, title, summary),
        )
        memo_id = cursor.lastrowid
        row = db.execute("SELECT * FROM memos WHERE id = ?", (memo_id,)).fetchone()
    return _row_to_dict(row)


def get_memo_db(user: str, memo_id: int) -> dict | None:
    """ID でメモを1件取得する。user が所有しない/存在しなければ None。"""
    with _connect_db() as db:
        row = db.execute(
            "SELECT * FROM memos WHERE id = ? AND user = ?", (memo_id, user)
        ).fetchone()
    return _row_to_dict(row) if row else None


def list_memos_db(user: str, limit: int = 50) -> list[dict]:
    """user のメモを新しい順 (更新日時の降順) に取得する。"""
    with _connect_db() as db:
        rows = db.execute(
            "SELECT * FROM memos WHERE user = ? ORDER BY updated_at DESC, id DESC LIMIT ?",
            (user, limit),
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def _escape_like(keyword: str) -> str:
    """LIKE のワイルドカード (``%`` ``_``) と ``\\`` をリテラル化する。"""
    return keyword.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def search_memos_db(user: str, keywords: list[str], limit: int = 50) -> list[dict]:
    """user のメモをタイトルの部分一致で検索する (大文字小文字を区別しない)。

    複数キーワードはいずれかに一致したメモを返す (OR 検索)。各メモには
    どのキーワードに一致したかを示す ``matched_keywords`` を付与する。

    LIKE のワイルドカード (``%`` ``_``) はリテラルとして扱うため ESCAPE でエスケープする。
    """
    if not keywords:
        return []
    clauses = " OR ".join("title LIKE ? ESCAPE '\\'" for _ in keywords)
    params: list = [user]
    params.extend(f"%{_escape_like(k)}%" for k in keywords)
    params.append(limit)
    with _connect_db() as db:
        rows = db.execute(
            f"SELECT * FROM memos WHERE user = ? AND ({clauses}) "
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
    user: str, memo_id: int, title: str | None = None, summary: str | None = None
) -> dict | None:
    """user が所有するメモを更新する。指定したフィールドのみ変更し、更新後のレコードを返す。

    対象 ID が存在しない、または user が所有しない場合は None を返す。
    title と summary が両方 None の場合も更新対象なしとして既存レコードをそのまま返す。
    """
    with _connect_db() as db:
        row = db.execute(
            "SELECT * FROM memos WHERE id = ? AND user = ?", (memo_id, user)
        ).fetchone()
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
            params.append(user)
            db.execute(
                f"UPDATE memos SET {', '.join(fields)} WHERE id = ? AND user = ?",
                params,
            )
        row = db.execute(
            "SELECT * FROM memos WHERE id = ? AND user = ?", (memo_id, user)
        ).fetchone()
    return _row_to_dict(row)


def delete_memo_db(user: str, memo_id: int) -> bool:
    """user が所有するメモを削除する。削除できたら True、対象が無ければ False。"""
    with _connect_db() as db:
        cursor = db.execute(
            "DELETE FROM memos WHERE id = ? AND user = ?", (memo_id, user)
        )
        deleted = cursor.rowcount > 0
    return deleted

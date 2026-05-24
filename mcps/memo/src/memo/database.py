"""DB 接続とスキーマ管理、メモ・ユーザーの CRUD・検索ヘルパー。

dynamic_prompt と同様、SQLite を WAL モードで使う。ツール呼び出しごとに
新しい接続を返す (`_connect_db`) ことで、FastMCP が複数スレッドからツールを
呼んでもスレッド安全を保つ。

すべてのメモは作成したユーザー名 (``user``) を持ち、CRUD・検索は原則
``user`` で絞り込む。これにより、あるユーザーのメモは他ユーザーからは
読み取りも含めて一切アクセスできない (完全分離)。ただし ``admin``
ユーザー (``ADMIN_USER``) だけは ``is_admin=True`` を渡すことで、全ユーザー
(``user=''`` の孤立メモ含む) のメモを操作できる。

接続ユーザーは ``users`` テーブルに登録されていなければならない。登録判定は
``is_registered_user()`` で行い、未登録ユーザーはツール側で拒否される。
``admin`` は ``init_db()`` で必ずシードされる固定ユーザー。
"""

import os
import sqlite3
from pathlib import Path

DB_PATH = Path(os.environ.get("MEMO_DB_PATH", str(Path(__file__).parent / "memo.db")))

#: 全ユーザーのメモを操作できる特権ユーザー名。init_db() で必ずシードされる。
ADMIN_USER = "admin"


def init_db() -> None:
    """スキーマを作成する。サーバー起動時に1回だけ呼ぶ (冪等)。

    ``user`` カラムを持たない既存 DB は ``ALTER TABLE`` で移行する
    (既存メモは ``user=''`` となり、admin 以外からはアクセスできなくなる)。
    ``users`` テーブルを作成し、特権ユーザー ``admin`` をシードする。
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

        # 接続を許可するユーザーの台帳。name が不変の識別子、display_name と
        # note は admin が編集できる属性。
        db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                name         TEXT PRIMARY KEY,
                display_name TEXT NOT NULL DEFAULT '',
                note         TEXT NOT NULL DEFAULT '',
                created_at   TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at   TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        # 特権ユーザー admin を必ず用意する (ブートストラップ)
        db.execute(
            "INSERT OR IGNORE INTO users (name, display_name) VALUES (?, ?)",
            (ADMIN_USER, "Administrator"),
        )
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
# Memo CRUD helpers
#
# get/list/search/update/delete は第1引数に ``user``、末尾に ``is_admin`` を取る。
# ``is_admin=False`` (通常) では ``WHERE user = ?`` で絞り込み、他ユーザーのメモは
# 一覧・検索に出ず、ID 指定の get/update/delete も「対象なし」(None / False) として
# 扱い、存在を漏らさない。``is_admin=True`` では user 絞り込みを外し、全ユーザー
# (``user=''`` の孤立メモ含む) を操作対象にする。
#
# create は admin でも owner=接続ユーザー (admin 自身) として作成する。
# ---------------------------------------------------------------------------


def create_memo_db(user: str, title: str, summary: str = "") -> dict:
    """メモを新規作成し、作成したレコードを返す。所有者は ``user``。"""
    with _connect_db() as db:
        cursor = db.execute(
            "INSERT INTO memos (user, title, summary) VALUES (?, ?, ?)",
            (user, title, summary),
        )
        memo_id = cursor.lastrowid
        row = db.execute("SELECT * FROM memos WHERE id = ?", (memo_id,)).fetchone()
    return _row_to_dict(row)


def get_memo_db(user: str, memo_id: int, is_admin: bool = False) -> dict | None:
    """ID でメモを1件取得する。

    通常は ``user`` が所有しない/存在しなければ None。``is_admin=True`` なら
    所有者を問わず ID だけで取得する。
    """
    with _connect_db() as db:
        if is_admin:
            row = db.execute(
                "SELECT * FROM memos WHERE id = ?", (memo_id,)
            ).fetchone()
        else:
            row = db.execute(
                "SELECT * FROM memos WHERE id = ? AND user = ?", (memo_id, user)
            ).fetchone()
    return _row_to_dict(row) if row else None


def list_memos_db(user: str, limit: int = 50, is_admin: bool = False) -> list[dict]:
    """メモを新しい順 (更新日時の降順) に取得する。

    通常は ``user`` のメモのみ。``is_admin=True`` なら全ユーザーのメモを返す。
    """
    with _connect_db() as db:
        if is_admin:
            rows = db.execute(
                "SELECT * FROM memos ORDER BY updated_at DESC, id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        else:
            rows = db.execute(
                "SELECT * FROM memos WHERE user = ? ORDER BY updated_at DESC, id DESC LIMIT ?",
                (user, limit),
            ).fetchall()
    return [_row_to_dict(r) for r in rows]


def _escape_like(keyword: str) -> str:
    """LIKE のワイルドカード (``%`` ``_``) と ``\\`` をリテラル化する。"""
    return keyword.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def search_memos_db(
    user: str, keywords: list[str], limit: int = 50, is_admin: bool = False
) -> list[dict]:
    """メモをタイトルの部分一致で検索する (大文字小文字を区別しない)。

    通常は ``user`` のメモのみ、``is_admin=True`` なら全ユーザーのメモが対象。
    複数キーワードはいずれかに一致したメモを返す (OR 検索)。各メモには
    どのキーワードに一致したかを示す ``matched_keywords`` を付与する。

    LIKE のワイルドカード (``%`` ``_``) はリテラルとして扱うため ESCAPE でエスケープする。
    """
    if not keywords:
        return []
    clauses = " OR ".join("title LIKE ? ESCAPE '\\'" for _ in keywords)
    params: list = []
    if is_admin:
        where = f"({clauses})"
    else:
        where = f"user = ? AND ({clauses})"
        params.append(user)
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
) -> dict | None:
    """メモを更新する。指定したフィールドのみ変更し、更新後のレコードを返す。

    通常は ``user`` が所有するメモのみ更新でき、対象が存在しない/他人のものなら
    None。``is_admin=True`` なら所有者を問わず ID で更新する。
    title と summary が両方 None の場合は更新せず既存レコードを返す。
    """
    with _connect_db() as db:
        if is_admin:
            row = db.execute(
                "SELECT * FROM memos WHERE id = ?", (memo_id,)
            ).fetchone()
        else:
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
            if is_admin:
                params.append(memo_id)
                db.execute(
                    f"UPDATE memos SET {', '.join(fields)} WHERE id = ?", params
                )
            else:
                params.append(memo_id)
                params.append(user)
                db.execute(
                    f"UPDATE memos SET {', '.join(fields)} WHERE id = ? AND user = ?",
                    params,
                )

        if is_admin:
            row = db.execute(
                "SELECT * FROM memos WHERE id = ?", (memo_id,)
            ).fetchone()
        else:
            row = db.execute(
                "SELECT * FROM memos WHERE id = ? AND user = ?", (memo_id, user)
            ).fetchone()
    return _row_to_dict(row)


def delete_memo_db(user: str, memo_id: int, is_admin: bool = False) -> bool:
    """メモを削除する。削除できたら True、対象が無ければ False。

    通常は ``user`` が所有するメモのみ。``is_admin=True`` なら所有者を問わない。
    """
    with _connect_db() as db:
        if is_admin:
            cursor = db.execute("DELETE FROM memos WHERE id = ?", (memo_id,))
        else:
            cursor = db.execute(
                "DELETE FROM memos WHERE id = ? AND user = ?", (memo_id, user)
            )
        deleted = cursor.rowcount > 0
    return deleted


# ---------------------------------------------------------------------------
# User CRUD helpers (admin が ``users`` 台帳を管理するためのヘルパー)
#
# name は不変の識別子 (PK)。display_name / note は編集可能な属性。
# ユーザーを削除してもそのユーザーのメモ (memos) は残す。未登録になった
# ユーザーは接続を拒否されるため、残ったメモは admin だけが操作できる。
# ---------------------------------------------------------------------------


def _user_row_to_dict(row: sqlite3.Row) -> dict:
    return {
        "name": row["name"],
        "display_name": row["display_name"],
        "note": row["note"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def is_registered_user(name: str) -> bool:
    """``name`` が ``users`` 台帳に登録されていれば True。"""
    with _connect_db() as db:
        row = db.execute("SELECT 1 FROM users WHERE name = ?", (name,)).fetchone()
    return row is not None


def create_user_db(name: str, display_name: str = "", note: str = "") -> dict | None:
    """ユーザーを新規登録し、作成したレコードを返す。

    同名のユーザーが既に存在する場合は None を返す (重複登録を防ぐ)。
    """
    with _connect_db() as db:
        exists = db.execute("SELECT 1 FROM users WHERE name = ?", (name,)).fetchone()
        if exists:
            return None
        db.execute(
            "INSERT INTO users (name, display_name, note) VALUES (?, ?, ?)",
            (name, display_name, note),
        )
        row = db.execute("SELECT * FROM users WHERE name = ?", (name,)).fetchone()
    return _user_row_to_dict(row)


def get_user_db(name: str) -> dict | None:
    """ユーザーを1件取得する。存在しなければ None。"""
    with _connect_db() as db:
        row = db.execute("SELECT * FROM users WHERE name = ?", (name,)).fetchone()
    return _user_row_to_dict(row) if row else None


def list_users_db() -> list[dict]:
    """全ユーザーを名前順に取得する。"""
    with _connect_db() as db:
        rows = db.execute("SELECT * FROM users ORDER BY name").fetchall()
    return [_user_row_to_dict(r) for r in rows]


def update_user_db(
    name: str, display_name: str | None = None, note: str | None = None
) -> dict | None:
    """ユーザーの属性 (display_name / note) を更新する。

    name (識別子) は変更しない。対象が存在しなければ None。
    display_name と note が両方 None の場合は更新せず既存レコードを返す。
    """
    with _connect_db() as db:
        row = db.execute("SELECT * FROM users WHERE name = ?", (name,)).fetchone()
        if row is None:
            return None

        fields = []
        params: list = []
        if display_name is not None:
            fields.append("display_name = ?")
            params.append(display_name)
        if note is not None:
            fields.append("note = ?")
            params.append(note)

        if fields:
            fields.append("updated_at = datetime('now')")
            params.append(name)
            db.execute(
                f"UPDATE users SET {', '.join(fields)} WHERE name = ?", params
            )
        row = db.execute("SELECT * FROM users WHERE name = ?", (name,)).fetchone()
    return _user_row_to_dict(row)


def delete_user_db(name: str) -> bool:
    """ユーザーを台帳から削除する。削除できたら True、対象が無ければ False。

    そのユーザーのメモ (memos) は削除しない。
    """
    with _connect_db() as db:
        cursor = db.execute("DELETE FROM users WHERE name = ?", (name,))
        deleted = cursor.rowcount > 0
    return deleted

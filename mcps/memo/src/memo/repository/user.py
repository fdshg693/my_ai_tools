"""ユーザー台帳 (``users`` テーブル) のデータアクセス。

``name`` は不変の識別子 (PK)。``display_name`` / ``note`` は編集可能な属性。
接続を許可してよいかの判定 (``is_registered_user``) もここで提供する
(認可ロジック自体は ``memo.authz`` がこれを使って組み立てる)。

ユーザーを削除してもそのユーザーのメモ (``memos``) は残す。未登録になった
ユーザーは接続を拒否されるため、残ったメモは admin だけが操作できる。
"""

import sqlite3

from memo.database import _connect_db


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

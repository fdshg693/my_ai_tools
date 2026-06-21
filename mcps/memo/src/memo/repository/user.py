"""ユーザー台帳 (``users`` テーブル) のデータアクセス。

``id`` が不変の識別子 (PK)。メモ・カテゴリは ``id`` (``user_id``) に紐づくため、
``name`` を変更しても下位データの更新は不要。``name`` は一意のログインハンドル、
``display_name`` / ``note`` は編集可能な属性、``is_admin`` は名前から独立した
管理者権限フラグ (Python 側では bool)。接続を許可してよいかの判定
(``is_registered_user``) もここで提供する (認可ロジック自体は ``memo.authz`` が
これを使って組み立てる)。

ユーザーを削除すると、そのユーザーのメモ (``memos``)・カテゴリ
(``categories``)・埋め込みキャッシュ (``memo_embeddings``) も一緒に消えるが、
これは **DB の外部キー (ON DELETE CASCADE) が自動で行う** (``infra.database``
のスキーマ参照)。アプリ側で複数テーブルを手で消すことはしない
(外部キーは接続ごとに ``PRAGMA foreign_keys=ON`` で有効化済み)。
"""

import sqlite3

from memo.infra.database import _connect_db


def _user_row_to_dict(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "name": row["name"],
        "display_name": row["display_name"],
        "note": row["note"],
        "is_admin": bool(row["is_admin"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def is_registered_user(name: str) -> bool:
    """``name`` が ``users`` 台帳に登録されていれば True。"""
    with _connect_db() as db:
        row = db.execute("SELECT 1 FROM users WHERE name = ?", (name,)).fetchone()
    return row is not None


def count_admins_db() -> int:
    """``is_admin`` が立っているユーザー数を返す (最後の管理者保護に使う)。"""
    with _connect_db() as db:
        row = db.execute("SELECT COUNT(*) AS n FROM users WHERE is_admin = 1").fetchone()
    return row["n"]


def create_user_db(
    name: str, display_name: str = "", note: str = "", is_admin: bool = False
) -> dict | None:
    """ユーザーを新規登録し、作成したレコードを返す。

    同名のユーザーが既に存在する場合は None を返す (重複登録を防ぐ)。
    ``is_admin`` で管理者権限を付けて作成できる。
    """
    with _connect_db() as db:
        exists = db.execute("SELECT 1 FROM users WHERE name = ?", (name,)).fetchone()
        if exists:
            return None
        db.execute(
            "INSERT INTO users (name, display_name, note, is_admin) VALUES (?, ?, ?, ?)",
            (name, display_name, note, 1 if is_admin else 0),
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
    name: str,
    display_name: str | None = None,
    note: str | None = None,
    is_admin: bool | None = None,
) -> dict | None:
    """ユーザーの属性 (display_name / note / is_admin) を更新する。

    name (ログインハンドル) は変更しない。対象が存在しなければ None。
    すべて None の場合は更新せず既存レコードを返す。``is_admin`` は ``None`` で
    「変更しない」、bool で管理者権限を付与/剥奪する。
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
        if is_admin is not None:
            fields.append("is_admin = ?")
            params.append(1 if is_admin else 0)

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

    そのユーザーのメモ (memos)・カテゴリ (categories)・埋め込みキャッシュ
    (memo_embeddings) は、外部キーの ON DELETE CASCADE により DB が自動で
    削除する (孤立データを残さない)。ここでは users 行を1つ消すだけ。
    """
    with _connect_db() as db:
        cursor = db.execute("DELETE FROM users WHERE name = ?", (name,))
        return cursor.rowcount > 0

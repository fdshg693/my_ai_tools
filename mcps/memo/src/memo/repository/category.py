"""カテゴリのデータアクセス (正規化ルール + ユーザーごとの第一級カテゴリ台帳)。

カテゴリは ``categories`` テーブルでユーザーごとに管理される第一級の実体。
``(user, name)`` で一意で、メモは自分の登録済みカテゴリにしか紐づけられない
(その検証は service 層が ``category_exists_db`` を使って行う)。

``repository.memo`` がここの ``normalize_category`` を取り込む (memo → category の
一方向依存)。循環参照を避けるため、ここでは ``repository.memo`` を一切 import せず、
``infra`` だけに依存する。リネーム/削除はメモへ波及するため (rename はカテゴリ名の
付け替え、delete は紐づくメモを OTHERS へ戻す)、``memos`` 行への ``UPDATE`` も
ここで生 SQL で行い、カテゴリ行とメモ行を1接続のトランザクションで整合させる。

ここでは「誰が admin か」は扱わない。カテゴリは admin も含め常にユーザー単位で
スコープする (横断アクセスは持たない)。
"""

import sqlite3

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


def _row_to_dict(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "user": row["user"],
        "name": row["name"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def list_categories_db(user: str) -> list[dict]:
    """ユーザーのカテゴリ一覧を名前順に返す (``categories`` テーブル参照)。

    カテゴリはユーザー単位なので、常に ``user`` のものだけを返す。
    各要素は id / user / name / created_at / updated_at を持つ dict。
    """
    with _connect_db() as db:
        rows = db.execute(
            "SELECT * FROM categories WHERE user = ? ORDER BY name",
            (user,),
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def get_category_db(user: str, category_id: int) -> dict | None:
    """id でカテゴリを1件取得する (そのユーザーのものに限る)。無ければ None。"""
    with _connect_db() as db:
        row = db.execute(
            "SELECT * FROM categories WHERE id = ? AND user = ?",
            (category_id, user),
        ).fetchone()
    return _row_to_dict(row) if row else None


def category_exists_db(user: str, name: str) -> bool:
    """``user`` が ``name`` のカテゴリを持っていれば True (正規化して照合)。"""
    with _connect_db() as db:
        row = db.execute(
            "SELECT 1 FROM categories WHERE user = ? AND name = ?",
            (user, normalize_category(name)),
        ).fetchone()
    return row is not None


def create_category_db(user: str, name: str) -> dict | None:
    """カテゴリを新規作成し、作成レコードを返す。

    ``name`` は ``normalize_category`` で正規化する。同名 (正規化後) が既に
    存在する場合は None を返す (重複防止)。
    """
    normalized = normalize_category(name)
    with _connect_db() as db:
        exists = db.execute(
            "SELECT 1 FROM categories WHERE user = ? AND name = ?",
            (user, normalized),
        ).fetchone()
        if exists:
            return None
        cursor = db.execute(
            "INSERT INTO categories (user, name) VALUES (?, ?)",
            (user, normalized),
        )
        row = db.execute(
            "SELECT * FROM categories WHERE id = ?", (cursor.lastrowid,)
        ).fetchone()
    return _row_to_dict(row)


def ensure_default_category_db(user: str) -> None:
    """``user`` に既定カテゴリ ``OTHERS`` を保証する (冪等)。

    新規ユーザー作成時に呼び、最低でも OTHERS を1つ持たせる。
    """
    with _connect_db() as db:
        db.execute(
            "INSERT OR IGNORE INTO categories (user, name) VALUES (?, ?)",
            (user, OTHERS_CATEGORY),
        )


def rename_category_db(user: str, old_name: str, new_name: str) -> None:
    """カテゴリ名を変更し、紐づくメモのカテゴリも追従させる。

    ``categories`` 行のリネームと ``memos.category`` の付け替えを1接続の
    トランザクションでまとめて行う。呼び出し元 (service) が事前に存在/衝突を
    検証している前提だが、ここでも正規化した値で UPDATE する。
    """
    old = normalize_category(old_name)
    new = normalize_category(new_name)
    with _connect_db() as db:
        db.execute(
            "UPDATE categories SET name = ?, updated_at = datetime('now') "
            "WHERE user = ? AND name = ?",
            (new, user, old),
        )
        # 紐づくメモのカテゴリも自動更新する
        db.execute(
            "UPDATE memos SET category = ?, updated_at = datetime('now') "
            "WHERE user = ? AND category = ?",
            (new, user, old),
        )
        db.commit()


def delete_category_db(user: str, name: str) -> None:
    """カテゴリを削除し、紐づくメモを既定カテゴリ ``OTHERS`` へ付け替える。

    メモの付け替えとカテゴリ行の削除を1接続のトランザクションで行う。
    ``OTHERS`` 自体は削除不可 (呼び出し元 service が拒否する)。
    """
    target = normalize_category(name)
    with _connect_db() as db:
        # 先に紐づくメモを OTHERS へ戻してから、カテゴリ行を消す
        db.execute(
            "UPDATE memos SET category = ?, updated_at = datetime('now') "
            "WHERE user = ? AND category = ?",
            (OTHERS_CATEGORY, user, target),
        )
        db.execute(
            "DELETE FROM categories WHERE user = ? AND name = ?",
            (user, target),
        )
        db.commit()

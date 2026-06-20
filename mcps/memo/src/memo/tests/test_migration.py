"""スキーマ移行 (軽量マイグレーション) の単体テスト。

``init_db()`` が ``category`` カラムを持たない既存 DB に対し、カラムを追加して
既存メモを既定カテゴリ ``OTHERS`` へ移行することを検証する。conftest が DB パスを
一時ファイルへ差し替えているので、ここでは ``memos`` テーブルを作り直して
「カラムが無かった時代の DB」を再現する。
"""

import memo.infra.database as db_mod
from memo.infra.database import OTHERS_CATEGORY, init_db


def _rebuild_legacy_memos_table() -> int:
    """category カラムを持たない旧 memos テーブルを作り直し、1 件挿入して id を返す。"""
    with db_mod._connect_db() as db:
        db.execute("DROP TABLE IF EXISTS memos")
        db.execute(
            """
            CREATE TABLE memos (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                user       TEXT NOT NULL,
                title      TEXT NOT NULL,
                summary    TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )
        cursor = db.execute(
            "INSERT INTO memos (user, title, summary) VALUES (?, ?, ?)",
            ("alice", "旧メモ", "本文"),
        )
        return cursor.lastrowid


def test_init_db_adds_category_column_and_migrates_to_others():
    memo_id = _rebuild_legacy_memos_table()

    # 移行前: category カラムは存在しない
    with db_mod._connect_db() as db:
        columns = {row[1] for row in db.execute("PRAGMA table_info(memos)")}
    assert "category" not in columns

    init_db()  # 冪等。ここで category カラムを追加し、既存行を OTHERS にする

    with db_mod._connect_db() as db:
        columns = {row[1] for row in db.execute("PRAGMA table_info(memos)")}
        row = db.execute(
            "SELECT category FROM memos WHERE id = ?", (memo_id,)
        ).fetchone()
    assert "category" in columns
    assert row["category"] == OTHERS_CATEGORY

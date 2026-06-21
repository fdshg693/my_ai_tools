"""マイグレーションの実行エンジン (バージョン管理)。

``schema_version`` テーブルに適用済みバージョンを記録し、``_MIGRATIONS`` の
うち未適用のものだけを昇順に実行する。新しいマイグレーションを足す手順:

  1. ``mNNN_xxx.py`` を作り、``VERSION`` / ``DESCRIPTION`` / ``migrate(db)`` を定義する。
  2. このファイルの ``_MIGRATIONS`` に ``(VERSION, DESCRIPTION, migrate)`` を追加する
     (バージョン番号は連番)。

**接続はオートコミット (``isolation_level = None``) で渡すこと。** 一部の
マイグレーション (m001) はテーブル作り替えのため ``PRAGMA foreign_keys`` を
トランザクション外で切り替え、自前で ``BEGIN``/``COMMIT`` する必要がある。
"""

import sqlite3
from collections.abc import Callable

from memo.migrations import m001_foreign_keys, m002_user_id

# (version, description, migrate_func) を昇順で並べる。
_MIGRATIONS: list[tuple[int, str, Callable[[sqlite3.Connection], None]]] = [
    (
        m001_foreign_keys.VERSION,
        m001_foreign_keys.DESCRIPTION,
        m001_foreign_keys.migrate,
    ),
    (
        m002_user_id.VERSION,
        m002_user_id.DESCRIPTION,
        m002_user_id.migrate,
    ),
]


def _table_exists(db: sqlite3.Connection, name: str) -> bool:
    row = db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone()
    return row is not None


def _ensure_version_table(db: sqlite3.Connection) -> None:
    db.execute("""
        CREATE TABLE IF NOT EXISTS schema_version (
            version     INTEGER PRIMARY KEY,
            description TEXT NOT NULL,
            applied_at  TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)


def _get_current_version(db: sqlite3.Connection) -> int:
    """適用済みの最大バージョンを返す。``schema_version`` が無ければ 0。"""
    if not _table_exists(db, "schema_version"):
        return 0
    row = db.execute("SELECT MAX(version) FROM schema_version").fetchone()
    return row[0] or 0


def run_migrations(db: sqlite3.Connection) -> None:
    """未適用のマイグレーションを順番に実行し、適用済みバージョンを記録する。

    冪等: 何度呼んでも適用済みバージョンはスキップされる。``db`` は
    オートコミット (``isolation_level = None``) であること (モジュール docstring 参照)。
    """
    _ensure_version_table(db)
    current = _get_current_version(db)
    for version, description, func in _MIGRATIONS:
        if version > current:
            func(db)
            db.execute(
                "INSERT INTO schema_version (version, description) VALUES (?, ?)",
                (version, description),
            )

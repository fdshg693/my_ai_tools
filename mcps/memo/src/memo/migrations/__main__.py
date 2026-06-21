"""既存 DB を最新スキーマへ移行するスタンドアロン実行口。

使い方::

    uv run memo-migrate            # MEMO_DB_PATH (既定の memo.db) を移行
    uv run memo-migrate /path/to/memo.db
    python -m memo.migrations [DB_PATH]

``init_db()`` を呼ぶだけ (スキーマ作成 + マイグレーション + シードを冪等に行う)。
移行前後の ``schema_version`` を表示する。サーバー起動時にも同じ ``init_db()`` が
走るので、通常はこのスクリプトを明示的に実行する必要はない。既存データを
手動で移行・確認したいときの口。
"""

import sqlite3
import sys
from pathlib import Path

import memo.infra.database as database
from memo.migrations.runner import _get_current_version


def _version_of(db_path: Path) -> int:
    conn = sqlite3.connect(db_path)
    try:
        return _get_current_version(conn)
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> None:
    argv = sys.argv[1:] if argv is None else argv
    if argv:
        database.DB_PATH = Path(argv[0])

    before = _version_of(database.DB_PATH)
    database.init_db()
    after = _version_of(database.DB_PATH)

    print(f"DB: {database.DB_PATH}")
    print(f"schema_version: {before} -> {after}")


if __name__ == "__main__":
    main()

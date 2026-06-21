"""SQLite 接続ファクトリと DB パス。

``DB_PATH`` がこのバックエンドの DB ファイル位置の唯一の出所。テストや
``build_sqlite_repo(db_path=...)`` はここを書き換える。全ての接続取得は
``_connect_db()`` を経由するため、``DB_PATH`` を差し替えれば全モジュールに反映される。
"""

import os
import sqlite3
from pathlib import Path

# __file__ = repo/sqlite_repo/connection.py → parents[2] = dynamic_prompt/
DB_PATH = Path(os.environ.get("DB_PATH", str(Path(__file__).parents[2] / "vocab.db")))


def _connect_db() -> sqlite3.Connection:
    """毎回新しい接続を返す。FastMCP (HTTP) は複数スレッドでツールを呼ぶため、
    接続をグローバルに使い回すと 'SQLite objects created in a thread can only
    be used in that same thread' エラーになる。呼び出し側は `with _connect_db() as db:`
    で使うこと。

    ``row_factory = sqlite3.Row`` により、行は列名でアクセスできる
    (``row["is_correct"]``)。位置インデックス (``row[0]``) も後方互換で使えるが、
    SELECT の列順変更に強い列名アクセスを推奨する。"""
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    return db

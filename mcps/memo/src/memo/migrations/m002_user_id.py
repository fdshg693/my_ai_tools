"""Migration 002: ユーザーへ不変の ``id`` (PK) と ``is_admin`` フラグを導入する。

ねらい:

- **管理者判定を名前から切り離す。** これまでは名前 ``admin`` で管理者かどうかを
  判定していたが、``users.is_admin`` (0/1) で管理する。既存の ``admin`` 行は
  ``is_admin=1`` に設定する (既定管理者を保つ)。
- **ユーザーの安定識別子を ``id`` にする。** ``users.name`` は PK から一意属性へ
  変え、新たに ``id INTEGER PRIMARY KEY AUTOINCREMENT`` を持たせる。メモ・カテゴリ
  の所有者参照を ``user`` (名前文字列) → ``user_id`` (``users(id)`` への外部キー)
  へ移す。これによりメモは ID に紐づき、ユーザー名を変更してもメモの更新は不要。

SQLite は ``ALTER TABLE`` で PK 追加や外部キーの差し替えができないため、
``users`` / ``categories`` / ``memos`` を「新テーブル作成 → データ移送 → 旧テーブル
削除 → リネーム」で作り替える (公式手順)。カテゴリ↔メモの同期トリガーは
``user`` 参照から ``user_id`` 参照へ作り替える (旧トリガーを drop し、現行の
``infra.database._create_triggers`` で作り直す)。

新規 DB は ``init_db`` の ``_create_schema`` で既に ``id`` / ``user_id`` 付きなので、
この移行はトリガーの存在だけ保証してスキップする (冪等)。
"""

import sqlite3

from memo.infra.database import ADMIN_USER, _create_triggers

VERSION = 2
DESCRIPTION = "Add users.id PK + is_admin; retie memos/categories to user_id"


def _column_exists(db: sqlite3.Connection, table: str, column: str) -> bool:
    return any(r[1] == column for r in db.execute(f"PRAGMA table_info({table})"))


def migrate(db: sqlite3.Connection) -> None:
    """name ベースの FK スキーマを id ベースへ作り替え、``is_admin`` を導入する。

    既に id ベース (``memos.user_id`` がある) なら作り替えをスキップし、
    トリガーの存在だけ保証する。``db`` はオートコミットであること。
    """
    if _column_exists(db, "memos", "user_id"):
        # 既に id ベース (新規 DB / 適用済み)。現行 (user_id) トリガーを保証して終了。
        _create_triggers(db)
        return

    # users へ is_admin 列を足し、既定管理者 admin を管理者にする (作り替え前に実施
    # しておけば下の users 作り替えがこの列をそのまま移送できる)。
    if not _column_exists(db, "users", "is_admin"):
        db.execute("ALTER TABLE users ADD COLUMN is_admin INTEGER NOT NULL DEFAULT 0")
    db.execute("UPDATE users SET is_admin = 1 WHERE name = ?", (ADMIN_USER,))

    # テーブル作り替えは外部キー強制を OFF にし、トランザクション外で PRAGMA を
    # 切り替えてから行う (PRAGMA foreign_keys はトランザクション内では無効)。
    db.execute("PRAGMA foreign_keys=OFF")
    db.execute("BEGIN")
    try:
        _drop_orphans(db)
        _rebuild_users(db)
        _rebuild_categories(db)
        _rebuild_memos(db)
        # 旧 (user 参照) トリガーを捨て、現行の user_id 参照トリガーへ作り替える。
        db.execute("DROP TRIGGER IF EXISTS trg_categories_rename_cascade")
        db.execute("DROP TRIGGER IF EXISTS trg_categories_delete_reassign")
        _create_triggers(db)
        violations = db.execute("PRAGMA foreign_key_check").fetchall()
        if violations:
            raise sqlite3.IntegrityError(
                f"foreign_key_check failed after user_id migration: {violations}"
            )
        db.execute("COMMIT")
    except Exception:
        db.execute("ROLLBACK")
        raise
    finally:
        db.execute("PRAGMA foreign_keys=ON")


def _drop_orphans(db: sqlite3.Connection) -> None:
    """所有者が ``users`` に居ないメモ/カテゴリを削除する (移送の JOIN で落ちる行を一掃)。"""
    db.execute("DELETE FROM memos WHERE user NOT IN (SELECT name FROM users)")
    db.execute("DELETE FROM categories WHERE user NOT IN (SELECT name FROM users)")
    db.execute(
        "DELETE FROM memo_embeddings WHERE memo_id NOT IN (SELECT id FROM memos)"
    )


def _rebuild_users(db: sqlite3.Connection) -> None:
    """``users`` を name PK から id PK (+ name UNIQUE) へ作り替え、id を採番する。"""
    db.execute("""
        CREATE TABLE users_new (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            name         TEXT NOT NULL UNIQUE,
            display_name TEXT NOT NULL DEFAULT '',
            note         TEXT NOT NULL DEFAULT '',
            is_admin     INTEGER NOT NULL DEFAULT 0,
            created_at   TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at   TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    # 作成日時順に採番して id を安定させる (admin が先頭になりやすい)。
    db.execute(
        "INSERT INTO users_new "
        "(name, display_name, note, is_admin, created_at, updated_at) "
        "SELECT name, display_name, note, is_admin, created_at, updated_at "
        "FROM users ORDER BY created_at, rowid"
    )
    db.execute("DROP TABLE users")
    db.execute("ALTER TABLE users_new RENAME TO users")


def _rebuild_categories(db: sqlite3.Connection) -> None:
    """``categories`` の所有者参照を ``user`` (名前) → ``user_id`` へ移す。"""
    db.execute("""
        CREATE TABLE categories_new (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            name       TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE(user_id, name)
        )
    """)
    db.execute(
        "INSERT INTO categories_new (id, user_id, name, created_at, updated_at) "
        "SELECT c.id, u.id, c.name, c.created_at, c.updated_at "
        "FROM categories c JOIN users u ON c.user = u.name"
    )
    db.execute("DROP TABLE categories")
    db.execute("ALTER TABLE categories_new RENAME TO categories")
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_categories_user_id ON categories(user_id)"
    )


def _rebuild_memos(db: sqlite3.Connection) -> None:
    """``memos`` の所有者参照を ``user`` (名前) → ``user_id`` へ移す (id は保持)。

    ``memo_embeddings`` は ``memo_id`` を変えないので作り替え不要 (FK はそのまま有効)。
    """
    db.execute("""
        CREATE TABLE memos_new (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            title      TEXT NOT NULL,
            summary    TEXT NOT NULL DEFAULT '',
            category   TEXT NOT NULL DEFAULT 'OTHERS',
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    db.execute(
        "INSERT INTO memos_new "
        "(id, user_id, title, summary, category, created_at, updated_at) "
        "SELECT m.id, u.id, m.title, m.summary, m.category, m.created_at, m.updated_at "
        "FROM memos m JOIN users u ON m.user = u.name"
    )
    db.execute("DROP TABLE memos")
    db.execute("ALTER TABLE memos_new RENAME TO memos")
    db.execute("CREATE INDEX IF NOT EXISTS idx_memos_user_id ON memos(user_id)")

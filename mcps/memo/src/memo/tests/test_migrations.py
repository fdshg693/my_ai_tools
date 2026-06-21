"""マイグレーション (バージョン管理 + m001 外部キー移行) の単体テスト。

conftest の共有 DB ではなく、各テストで一時 DB を作って検証する
(旧スキーマ → 移行 → 外部キー/トリガーの確認)。dynamic_prompt の
test_migration.py の方針を踏襲する。
"""

import sqlite3
import tempfile
from pathlib import Path

from memo.migrations.m001_foreign_keys import _has_fk
from memo.migrations.runner import (
    _MIGRATIONS,
    _get_current_version,
    run_migrations,
)

# 旧スキーマ (外部キー無し)。移行前の既存 DB を再現する。
_LEGACY_SCHEMA = """
    CREATE TABLE users (
        name TEXT PRIMARY KEY,
        display_name TEXT NOT NULL DEFAULT '',
        note TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        updated_at TEXT NOT NULL DEFAULT (datetime('now'))
    );
    CREATE TABLE categories (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user TEXT NOT NULL,
        name TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        updated_at TEXT NOT NULL DEFAULT (datetime('now')),
        UNIQUE(user, name)
    );
    CREATE TABLE memos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user TEXT NOT NULL,
        title TEXT NOT NULL,
        summary TEXT NOT NULL DEFAULT '',
        category TEXT NOT NULL DEFAULT 'OTHERS',
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        updated_at TEXT NOT NULL DEFAULT (datetime('now'))
    );
    CREATE TABLE memo_embeddings (
        memo_id INTEGER PRIMARY KEY,
        summary_hash TEXT NOT NULL,
        model TEXT NOT NULL,
        vector TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT (datetime('now'))
    );
"""


def _legacy_db() -> sqlite3.Connection:
    """旧スキーマ (外部キー無し) の一時 DB 接続を返す (オートコミット)。"""
    path = Path(tempfile.mkdtemp()) / "legacy.db"
    db = sqlite3.connect(str(path))
    db.isolation_level = None  # run_migrations はオートコミット接続を要求する
    db.executescript(_LEGACY_SCHEMA)
    return db


def _seed_legacy(db: sqlite3.Connection) -> None:
    """alice の正常データ + 孤立データ (所有者不明メモ・実体無し埋め込み) を入れる。"""
    db.execute("INSERT INTO users (name) VALUES ('admin')")
    db.execute("INSERT INTO users (name) VALUES ('alice')")
    db.execute("INSERT INTO categories (user, name) VALUES ('alice', 'WORK')")
    db.execute("INSERT INTO memos (id, user, title, category) VALUES (1, 'alice', 'm', 'WORK')")
    # 孤立メモ: 所有者 ghost は users に居ない
    db.execute("INSERT INTO memos (id, user, title, category) VALUES (2, 'ghost', 'orphan', 'OTHERS')")
    # 孤立埋め込み: メモ 999 は存在しない
    db.execute(
        "INSERT INTO memo_embeddings (memo_id, summary_hash, model, vector) "
        "VALUES (999, 'h', 'm', '[]')"
    )


# ---------------------------------------------------------------------------
# バージョン管理
# ---------------------------------------------------------------------------


def test_initial_version_is_zero():
    db = _legacy_db()
    assert _get_current_version(db) == 0
    db.close()


def test_version_after_migrate():
    db = _legacy_db()
    _seed_legacy(db)
    run_migrations(db)
    expected = max(v for v, _, _ in _MIGRATIONS)
    assert _get_current_version(db) == expected
    db.close()


def test_migrate_twice_is_idempotent():
    db = _legacy_db()
    _seed_legacy(db)
    run_migrations(db)
    run_migrations(db)
    count = db.execute("SELECT COUNT(*) FROM schema_version").fetchone()[0]
    assert count == len(_MIGRATIONS)
    db.close()


# ---------------------------------------------------------------------------
# m001: 外部キー付与
# ---------------------------------------------------------------------------


def test_adds_foreign_keys():
    db = _legacy_db()
    _seed_legacy(db)
    assert _has_fk(db, "memos") is False  # 移行前は無い
    run_migrations(db)
    assert _has_fk(db, "memos") is True
    assert _has_fk(db, "categories") is True
    assert _has_fk(db, "memo_embeddings") is True
    db.close()


def test_drops_orphans():
    db = _legacy_db()
    _seed_legacy(db)
    run_migrations(db)
    # 孤立メモ (ghost) と孤立埋め込み (999) は消える / 正常データは残る
    ids = {r[0] for r in db.execute("SELECT id FROM memos")}
    assert ids == {1}
    emb = db.execute("SELECT COUNT(*) FROM memo_embeddings").fetchone()[0]
    assert emb == 0
    db.close()


def test_preserves_valid_data():
    db = _legacy_db()
    _seed_legacy(db)
    run_migrations(db)
    # m002 後は user_id ベース。所有者名は users との JOIN で確認する。
    row = db.execute(
        "SELECT u.name, m.title, m.category FROM memos m "
        "JOIN users u ON m.user_id = u.id WHERE m.id = 1"
    ).fetchone()
    assert row == ("alice", "m", "WORK")
    db.close()


# ---------------------------------------------------------------------------
# m002: ユーザー id 化 + is_admin
# ---------------------------------------------------------------------------


def _alice_id(db: sqlite3.Connection) -> int:
    return db.execute("SELECT id FROM users WHERE name = 'alice'").fetchone()[0]


def test_user_id_columns_after_migration():
    db = _legacy_db()
    _seed_legacy(db)
    run_migrations(db)
    user_cols = {r[1] for r in db.execute("PRAGMA table_info(users)")}
    memo_cols = {r[1] for r in db.execute("PRAGMA table_info(memos)")}
    cat_cols = {r[1] for r in db.execute("PRAGMA table_info(categories)")}
    assert "id" in user_cols and "is_admin" in user_cols
    assert "user_id" in memo_cols and "user" not in memo_cols
    assert "user_id" in cat_cols and "user" not in cat_cols
    db.close()


def test_existing_admin_is_flagged():
    db = _legacy_db()
    _seed_legacy(db)
    run_migrations(db)
    # 既存 admin 行は is_admin=1、それ以外は 0
    assert db.execute("SELECT is_admin FROM users WHERE name='admin'").fetchone()[0] == 1
    assert db.execute("SELECT is_admin FROM users WHERE name='alice'").fetchone()[0] == 0
    db.close()


def test_memos_retied_to_user_id():
    db = _legacy_db()
    _seed_legacy(db)
    run_migrations(db)
    # メモ 1 は alice の id に紐づく
    assert db.execute("SELECT user_id FROM memos WHERE id=1").fetchone()[0] == _alice_id(db)
    db.close()


def test_user_delete_cascades_after_migration():
    db = _legacy_db()
    _seed_legacy(db)
    run_migrations(db)
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("DELETE FROM users WHERE name = 'alice'")
    assert db.execute("SELECT COUNT(*) FROM memos").fetchone()[0] == 0
    # alice のカテゴリは消える (admin のカテゴリは無いので全体 0)
    assert db.execute("SELECT COUNT(*) FROM categories").fetchone()[0] == 0
    db.close()


def test_category_rename_trigger_after_migration():
    db = _legacy_db()
    _seed_legacy(db)
    run_migrations(db)
    db.execute("PRAGMA foreign_keys=ON")
    db.execute(
        "UPDATE categories SET name = 'JOB' WHERE user_id = ? AND name = 'WORK'",
        (_alice_id(db),),
    )
    cat = db.execute("SELECT category FROM memos WHERE id = 1").fetchone()[0]
    assert cat == "JOB"
    db.close()


def test_category_delete_trigger_reassigns_after_migration():
    db = _legacy_db()
    _seed_legacy(db)
    run_migrations(db)
    db.execute("PRAGMA foreign_keys=ON")
    db.execute(
        "DELETE FROM categories WHERE user_id = ? AND name = 'WORK'",
        (_alice_id(db),),
    )
    cat = db.execute("SELECT category FROM memos WHERE id = 1").fetchone()[0]
    assert cat == "OTHERS"
    db.close()

# Schema

## Database

SQLite with WAL journaling (`memo.db`). `init_db()` creates the schema and runs migrations at server startup (idempotent). Each tool call returns a fresh connection for thread safety (`_connect_db`, `row_factory = sqlite3.Row`). `DB_PATH` defaults to `parent.parent / "memo.db"` (= `src/memo/memo.db`), overridable via `MEMO_DB_PATH`.

**Foreign keys are always ON** (`PRAGMA foreign_keys=ON` in both `init_db()` and every `_connect_db()`), so the DB itself enforces referential integrity and performs cascades — the app never hand-writes cross-table cascade SQL. The relationships:

- `categories.user` / `memos.user` → `users(name)` with `ON DELETE CASCADE ON UPDATE CASCADE`: deleting a user removes that user's categories and memos (and, transitively, their embeddings).
- `memo_embeddings.memo_id` → `memos(id)` with `ON DELETE CASCADE`: deleting a memo removes its embedding cache row.
- The `memo ⇄ category` link is a denormalized **string** (`memos.category`), not an FK, because the delete behavior ("reassign to the owner's `OTHERS`") is per-row dynamic and not expressible as an FK action. Two **triggers** keep it in sync instead (`trg_categories_rename_cascade` on `AFTER UPDATE OF name` → repoint memos to the new name; `trg_categories_delete_reassign` on `BEFORE DELETE` → set memos to `OTHERS`, skipping `OTHERS` itself). Triggers run inside the triggering statement's transaction, so the cascade is atomic.

**`memos` table:**

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER PK | Auto-increment |
| `user` | TEXT NOT NULL | Owning user name. **FK → `users(name)` (`ON DELETE/UPDATE CASCADE`)**. Indexed by `idx_memos_user`. Memos are always scoped by this (no cross-user access, even for `admin`) |
| `title` | TEXT NOT NULL | Title |
| `summary` | TEXT NOT NULL DEFAULT '' | Summary |
| `category` | TEXT NOT NULL DEFAULT 'OTHERS' | Category (denormalized string, **not an FK** — kept in sync by triggers, see above). Normalized (trim + uppercase) on write by `repository.category.normalize_category`; empty/unspecified → `OTHERS` (`OTHERS_CATEGORY`). Must be one of the owner's registered `categories` (validated in `service.memo`). See [features/category.md](features/category.md) |
| `created_at` | TEXT NOT NULL | Created timestamp |
| `updated_at` | TEXT NOT NULL | Updated timestamp (set to `datetime('now')` on update) |

**`users` table:**

| Column | Type | Description |
|--------|------|-------------|
| `name` | TEXT PK | User name (immutable identifier). Used to decide whether to allow a connection |
| `display_name` | TEXT NOT NULL DEFAULT '' | Display name (editable by admin) |
| `note` | TEXT NOT NULL DEFAULT '' | Note / remarks (editable by admin) |
| `created_at` | TEXT NOT NULL | Created timestamp |
| `updated_at` | TEXT NOT NULL | Updated timestamp |

**`categories` table** (per-user first-class category ledger):

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER PK | Auto-increment |
| `user` | TEXT NOT NULL | Owning user name. **FK → `users(name)` (`ON DELETE/UPDATE CASCADE`)**. Indexed by `idx_categories_user` |
| `name` | TEXT NOT NULL | Category name (normalized: trim + uppercase). `UNIQUE(user, name)` |
| `created_at` | TEXT NOT NULL | Created timestamp |
| `updated_at` | TEXT NOT NULL | Updated timestamp |

Each user is seeded with `OTHERS` (cannot be renamed/deleted). A memo's `category` must match one of its owner's rows here (or `OTHERS`). Rename cascades to `memos.category` and delete reassigns linked memos to `OTHERS` — **both via triggers** (see Database above), not app SQL. See [features/category.md](features/category.md).

**`memo_embeddings` table** (embedding cache for semantic search):

| Column | Type | Description |
|--------|------|-------------|
| `memo_id` | INTEGER PK | Target memo id (one row per memo). **FK → `memos(id)` (`ON DELETE CASCADE`)** — deleting a memo drops its cache row |
| `summary_hash` | TEXT NOT NULL | SHA-256 of the summary at embed time. Mismatch when the summary changes → recompute |
| `model` | TEXT NOT NULL | Embedding model name. Mismatch when the model changes → recompute (also prevents dimension mismatch) |
| `vector` | TEXT NOT NULL | Embedding vector (JSON array) |
| `created_at` | TEXT NOT NULL | Computed / stored timestamp |

## Changing the schema

Schema changes are now **version-managed migrations** living in their own package, [`src/memo/migrations/`](../src/memo/migrations/) (modeled on `dynamic_prompt`'s `_MIGRATIONS`). `init_db()` runs three idempotent steps on an **autocommit** connection: `_create_schema()` (the current FK schema via `CREATE TABLE IF NOT EXISTS` — makes fresh DBs complete) → `run_migrations()` (upgrades legacy DBs) → `_seed()` (admin + per-user `OTHERS` + `(user, category)` back-fill).

Migration framework (`migrations/`):
- `runner.py` — `schema_version` table (`version` PK / `description` / `applied_at`), `_MIGRATIONS` registry of `(version, description, migrate_fn)`, and `run_migrations(db)` which applies only versions above the current max. Requires an autocommit connection.
- `mNNN_*.py` — one migration each, exposing `VERSION` / `DESCRIPTION` / `migrate(db)`.
- `__main__.py` — standalone runner (`uv run memo-migrate [DB_PATH]`, or `python -m memo.migrations`) that calls `init_db()` and prints the `schema_version` before→after. The same `init_db()` runs on every server startup, so explicit runs are only for inspecting/migrating an existing DB by hand.

To add a migration: create `mNNN_*.py` with `migrate(db)` and append it to `runner._MIGRATIONS` (sequential version number). For a simple new column, follow the `PRAGMA table_info` → `ALTER TABLE ADD COLUMN` guard pattern inside the migration. Adding/altering an **FK** requires a table rebuild (SQLite can't `ALTER` one in) — see `m001` for the canonical recipe.

**`m001_foreign_keys`** (current head, version 1): converts a legacy no-FK DB to the FK schema. Idempotent — if `memos`/`categories` already carry the FK (fresh DB from `_create_schema`, or already migrated) it only ensures the triggers exist and returns. Otherwise, with `PRAGMA foreign_keys=OFF` and inside an explicit transaction, it: defensively `ADD COLUMN`s any missing `user`/`category`; drops orphans (memos/categories whose `user` isn't in `users`, embeddings whose `memo_id` is gone — these can't survive under the new FKs, and the prior `user=''` orphans land here); rebuilds `categories` / `memos` / `memo_embeddings` with the FK constraints (create-new → copy → drop → rename, re-creating indexes); creates the two category↔memo triggers; runs `PRAGMA foreign_key_check` (raises on any remaining violation) and commits. The per-user `OTHERS` seed and `(user, category)` back-fill stay in `init_db()._seed()` (run after migrations, `INSERT OR IGNORE`).

# Schema

## Database

SQLite with WAL journaling (`memo.db`). `init_db()` creates the schema and runs migrations at server startup (idempotent). Each tool call returns a fresh connection for thread safety (`_connect_db`, `row_factory = sqlite3.Row`). `DB_PATH` defaults to `parent.parent / "memo.db"` (= `src/memo/memo.db`), overridable via `MEMO_DB_PATH`.

**Identity model.** `users.id` (INTEGER PK) is the **immutable identifier**; `users.name` is a unique but mutable login handle. Memos and categories reference the owner by `user_id` (→ `users(id)`), **not** by name — so a future user rename never has to touch memo/category rows (they are tied to the id). Admin status is the independent `users.is_admin` flag (0/1), **decided by the flag, not by the name** (`ADMIN_USER = "admin"` is only the default seeded admin's name).

**Foreign keys are always ON** (`PRAGMA foreign_keys=ON` in both `init_db()` and every `_connect_db()`), so the DB itself enforces referential integrity and performs cascades — the app never hand-writes cross-table cascade SQL. The relationships:

- `categories.user_id` / `memos.user_id` → `users(id)` with `ON DELETE CASCADE`: deleting a user removes that user's categories and memos (and, transitively, their embeddings). No `ON UPDATE CASCADE` — `id` is immutable.
- `memo_embeddings.memo_id` → `memos(id)` with `ON DELETE CASCADE`: deleting a memo removes its embedding cache row.
- The `memo ⇄ category` link is a denormalized **string** (`memos.category`), not an FK, because the delete behavior ("reassign to the owner's `OTHERS`") is per-row dynamic and not expressible as an FK action. Two **triggers** keep it in sync instead (`trg_categories_rename_cascade` on `AFTER UPDATE OF name` → repoint memos to the new name; `trg_categories_delete_reassign` on `BEFORE DELETE` → set memos to `OTHERS`, skipping `OTHERS` itself). Both scope by `user_id`. Triggers run inside the triggering statement's transaction, so the cascade is atomic.

**`memos` table:**

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER PK | Auto-increment |
| `user_id` | INTEGER NOT NULL | Owning user id. **FK → `users(id)` (`ON DELETE CASCADE`)**. Indexed by `idx_memos_user_id`. Memos are always scoped by this (no cross-user access, even for admins) |
| `title` | TEXT NOT NULL | Title |
| `summary` | TEXT NOT NULL DEFAULT '' | Summary |
| `category` | TEXT NOT NULL DEFAULT 'OTHERS' | Category (denormalized string, **not an FK** — kept in sync by triggers, see above). Normalized (trim + uppercase) on write by `repository.category.normalize_category`; empty/unspecified → `OTHERS` (`OTHERS_CATEGORY`). Must be one of the owner's registered `categories` (validated in `service.memo`). See [features/category.md](features/category.md) |
| `created_at` | TEXT NOT NULL | Created timestamp |
| `updated_at` | TEXT NOT NULL | Updated timestamp (set to `datetime('now')` on update) |

**`users` table:**

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER PK | Auto-increment. **Immutable identifier** that memos/categories reference (`user_id`) |
| `name` | TEXT NOT NULL UNIQUE | Login handle (used to identify a connection). Currently not renamed by any surface, but the schema allows it without touching memos |
| `display_name` | TEXT NOT NULL DEFAULT '' | Display name (editable by admin) |
| `note` | TEXT NOT NULL DEFAULT '' | Note / remarks (editable by admin) |
| `is_admin` | INTEGER NOT NULL DEFAULT 0 | Admin flag (1 = admin). Independent of `name`. Editable from the `memo-admin` web UI only. Exposed in Python dicts as a `bool` |
| `created_at` | TEXT NOT NULL | Created timestamp |
| `updated_at` | TEXT NOT NULL | Updated timestamp |

**`categories` table** (per-user first-class category ledger):

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER PK | Auto-increment |
| `user_id` | INTEGER NOT NULL | Owning user id. **FK → `users(id)` (`ON DELETE CASCADE`)**. Indexed by `idx_categories_user_id` |
| `name` | TEXT NOT NULL | Category name (normalized: trim + uppercase). `UNIQUE(user_id, name)` |
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

Schema changes are now **version-managed migrations** living in their own package, [`src/memo/migrations/`](../src/memo/migrations/) (modeled on `dynamic_prompt`'s `_MIGRATIONS`). `init_db()` runs four idempotent steps on an **autocommit** connection: `_create_schema()` (the current id/user_id FK schema via `CREATE TABLE IF NOT EXISTS` — makes fresh DBs complete; it only creates the category↔memo triggers when `categories.user_id` already exists so it doesn't install `user_id`-based triggers onto a not-yet-migrated legacy table) → `run_migrations()` (upgrades legacy DBs) → `_create_indexes()` (the `user_id` indexes; run **after** migrations because `user_id` only appears post-migration on legacy DBs) → `_seed()` (admin with `is_admin=1` + per-user `OTHERS` keyed by `user_id` + `(user_id, category)` back-fill).

Migration framework (`migrations/`):
- `runner.py` — `schema_version` table (`version` PK / `description` / `applied_at`), `_MIGRATIONS` registry of `(version, description, migrate_fn)`, and `run_migrations(db)` which applies only versions above the current max. Requires an autocommit connection.
- `mNNN_*.py` — one migration each, exposing `VERSION` / `DESCRIPTION` / `migrate(db)`.
- `__main__.py` — standalone runner (`uv run memo-migrate [DB_PATH]`, or `python -m memo.migrations`) that calls `init_db()` and prints the `schema_version` before→after. The same `init_db()` runs on every server startup, so explicit runs are only for inspecting/migrating an existing DB by hand.

To add a migration: create `mNNN_*.py` with `migrate(db)` and append it to `runner._MIGRATIONS` (sequential version number). For a simple new column, follow the `PRAGMA table_info` → `ALTER TABLE ADD COLUMN` guard pattern inside the migration. Adding/altering an **FK** or a **PK** requires a table rebuild (SQLite can't `ALTER` one in) — see `m001`/`m002` for the canonical recipe. **A migration must be a frozen snapshot**: it should not call helpers from `infra.database` whose definitions later change (e.g. the trigger SQL). `m001` therefore inlines its own (name-based) trigger creation (`_create_name_triggers`) instead of importing `_create_triggers`, which is now `user_id`-based.

**`m001_foreign_keys`** (version 1): converts a legacy no-FK **name-based** DB to the (then-current) name-based FK schema. Idempotent — if `memos`/`categories` already carry the FK it only ensures its (name-based) triggers exist and returns. Otherwise, with `PRAGMA foreign_keys=OFF` and inside an explicit transaction, it: defensively `ADD COLUMN`s any missing `user`/`category`; drops orphans; rebuilds `categories` / `memos` / `memo_embeddings` with `user`-name FK constraints; creates the two name-based category↔memo triggers; runs `PRAGMA foreign_key_check` and commits.

**`m002_user_id`** (current head, version 2): converts the name-based FK schema to the **id-based** one and adds `is_admin`. Idempotent — if `memos.user_id` already exists (fresh DB or already migrated) it just ensures the current (`user_id`) triggers exist and returns. Otherwise it `ADD COLUMN`s `users.is_admin` (defaulting 0) and sets `is_admin=1` for the `ADMIN_USER` row, then with `PRAGMA foreign_keys=OFF` inside a transaction: drops orphans; rebuilds `users` from a `name` PK to an `id` PK (`name` becomes UNIQUE) assigning ids; rebuilds `categories` / `memos` remapping `user` (name) → `user_id` via a `JOIN users ON … = users.name` (FK → `users(id)`, `ON DELETE CASCADE`, indexes re-created); **drops the old name-based triggers and recreates the `user_id`-based ones** (`_create_triggers` from `infra.database`); runs `PRAGMA foreign_key_check` and commits. `memo_embeddings` is left as-is (memo ids are preserved). The per-user `OTHERS` seed and `(user_id, category)` back-fill stay in `init_db()._seed()` (run after migrations, `INSERT OR IGNORE`).

# Schema

## Database

SQLite with WAL journaling (`memo.db`). `init_db()` creates the schema at server startup (idempotent). Each tool call returns a fresh connection for thread safety (`_connect_db`, `row_factory = sqlite3.Row`). `DB_PATH` defaults to `parent.parent / "memo.db"` (= `src/memo/memo.db`), overridable via `MEMO_DB_PATH`.

**`memos` table:**

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER PK | Auto-increment |
| `user` | TEXT NOT NULL | Owning user name. Indexed by `idx_memos_user` |
| `title` | TEXT NOT NULL | Title |
| `summary` | TEXT NOT NULL DEFAULT '' | Summary |
| `category` | TEXT NOT NULL DEFAULT 'OTHERS' | Category. Normalized (trim + uppercase) on write; empty/unspecified → `OTHERS` (`OTHERS_CATEGORY`). See [features/category.md](features/category.md) |
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

**`memo_embeddings` table** (embedding cache for semantic search):

| Column | Type | Description |
|--------|------|-------------|
| `memo_id` | INTEGER PK | Target memo id (one row per memo). No FK (follows the existing schema) |
| `summary_hash` | TEXT NOT NULL | SHA-256 of the summary at embed time. Mismatch when the summary changes → recompute |
| `model` | TEXT NOT NULL | Embedding model name. Mismatch when the model changes → recompute (also prevents dimension mismatch) |
| `vector` | TEXT NOT NULL | Embedding vector (JSON array) |
| `created_at` | TEXT NOT NULL | Computed / stored timestamp |

## Changing the schema

Update the `CREATE TABLE` statements in `init_db()`. To add a column to an existing DB, follow the lightweight pattern used for the `user` column (`PRAGMA table_info` to check existence → `ALTER TABLE ADD COLUMN` if absent). If a full migration spanning multiple versions becomes necessary, refer to the `_MIGRATIONS` approach in `dynamic_prompt`.

Existing lightweight migrations performed by `init_db()`:
- `user` column: `ALTER TABLE ADD COLUMN user TEXT NOT NULL DEFAULT ''` (old memos become `user=''`: inaccessible to regular users but operable by admin).
- `category` column: `ALTER TABLE memos ADD COLUMN category TEXT NOT NULL DEFAULT 'OTHERS'`, so all pre-existing memos become `OTHERS` in one step (same `PRAGMA table_info` pattern as the `user` column).

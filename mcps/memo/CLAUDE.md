# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

> **About this file**: CLAUDE.md is the AI-facing document. Keep implementation and investigation details here, written in **English**. Human-facing material (startup steps, app overview, caveats) belongs in [README.md](./README.md), written in Japanese. Preserve this split when editing either file.

## Scope

This file covers `mcps/memo/` only — a FastMCP-based MCP server for managing simple memos (title + summary). Search supports both title substring matching and semantic search over summaries (OpenAI embeddings).

## Commands

```bash
# Run the MCP server (stdio transport — Claude Desktop / VS Code connect this way)
# --user sets the owning user for this process (env var MEMO_USER also works)
uv run memo --user alice

# Run the MCP server (HTTP transport). Clients pass /mcp?user=NAME&client_id=ID
# HOST defaults to 127.0.0.1 (local-only). Set HOST=0.0.0.0 only behind auth.
TRANSPORT=http PORT=8080 uv run memo

# Emit the full session picture (Mcp-Session-Id etc.) at DEBUG level on stderr
uv run memo --user alice --debug        # or env MEMO_LOG_DEBUG=1

# Unit tests (DB CRUD / search / admin privilege / user ledger / switch / audit log)
uv run --project mcps/memo pytest mcps/memo/src/memo/tests/ -v

# Inspect the registered tools via an MCP client (in-process connection)
uv run python -m memo.tests.test_mcp_client

# To exercise semantic search against the real API you need an OpenAI key
OPENAI_API_KEY=sk-... uv run memo --user admin
```

## Architecture

The server exposes 13 MCP tools. **Memo tools (7):** `create_memo`, `get_memo`, `list_memos`, `search_memos`, `semantic_search_memos`, `update_memo`, `delete_memo`. **User management tools (5, admin-only):** `create_user`, `get_user`, `list_users`, `update_user`, `delete_user`. **Session tool (1, not admin-only):** `switch_user`.

### Tool reference

**Memo tools** — regular users operate only on their own memos; other users' memos are reported as "not found" so existence is not leaked. `admin` operates on all memos (including orphans owned by `user=''`).

| Tool | Args | Behavior |
|------|------|----------|
| `create_memo` | `title`, `summary=""` | Create a memo. `title` required. Owner is the connected user (an admin-created memo is owned by `admin`). Returns a short message with the new id. |
| `get_memo` | `memo_id` | Fetch one memo by id. Own memos only; admin sees any owner. |
| `list_memos` | `limit=50` | List memos newest-first (`updated_at` desc). Own memos only; admin sees all. |
| `search_memos` | `query`, `limit=50` | Title substring search. `query` is comma-split into OR keywords; each result carries `matched_keywords`. Own memos only; admin sees all. |
| `semantic_search_memos` | `query`, `limit=5` | Semantic search over **summaries**. Results carry `similarity` (0–1), sorted desc; empty summaries are excluded. Own memos only; admin sees all. Needs `OPENAI_API_KEY`. |
| `update_memo` | `memo_id`, `title=None`, `summary=None` | Update only the supplied fields. Own memos only; admin any owner. |
| `delete_memo` | `memo_id` | Delete a memo. Own memos only; admin any owner. |

**User management tools (admin-only)** — each returns an `admin-only` error unless the caller is `admin`.

| Tool | Args | Behavior |
|------|------|----------|
| `create_user` | `name`, `display_name=""`, `note=""` | Register a user. `name` required, unique identifier. Returns a no-op message if it already exists. |
| `get_user` | `name` | Fetch one user. |
| `list_users` | — | List registered users by name. |
| `update_user` | `name`, `display_name=None`, `note=None` | Update attributes (display name / note). `name` (identifier) is immutable. |
| `delete_user` | `name` | Remove a user from the ledger (memos kept). `admin` itself cannot be deleted. |

**Session tool (not admin-only)** — any registered caller may switch the current user.

| Tool | Args | Behavior |
|------|------|----------|
| `switch_user` | `target` | Switch the connection's current user to `target` (must be registered; `admin` allowed) without reconnecting/restarting. stdio: rewrites the process user via `set_stdio_user`. HTTP: requires `?client_id=`; updates the `client_id → user` map. Errors if `target` unregistered or (HTTP) `client_id` absent. |

### Module structure

Files are split by domain (memo / user), with layers separated into data access (`repository`), authorization (`authz`), and the MCP interface (`tools`).

| Module | Responsibility |
|--------|---------------|
| `database.py` | Shared infrastructure only. SQLite connection factory (`_connect_db`), `init_db()` (startup schema init + lightweight `user`-column migration + `users` / `memo_embeddings` table creation + `admin` seed), constant `ADMIN_USER = "admin"`. `DB_PATH` overridable via `MEMO_DB_PATH`. Holds no domain CRUD. |
| `repository/memo.py` | Pure data access for memos (`*_memo_db`). get/list/search/update/delete take a trailing `is_admin`; when True the user filter is dropped to cover all memos (including orphans). Uses only `_connect_db`; no authorization. |
| `repository/user.py` | Data access for the user ledger (`users`, `*_user_db`) plus the registration check (`is_registered_user`). `name` is the immutable identifier; `display_name`/`note` are editable. Deleting a user does not delete their memos. |
| `repository/embedding.py` | Pure data access for the embedding cache (`memo_embeddings`): `get_cached_embedding` / `upsert_embedding` (UPSERT) / `delete_embedding`. vector is a JSON array. No network, no authorization. |
| `embedding.py` | OpenAI embedding API wrapper (leaf). The only place that imports `openai` and reads `OPENAI_API_KEY`. Provides `embed_text(text)`, constant `MODEL` (overridable via `MEMO_EMBEDDING_MODEL`), and exception `EmbeddingError`. The key is fetched lazily at call time. On import it loads `mcps/memo/.env` (fixed `parents[2]/.env`) via `python-dotenv` (existing env vars take precedence; .env does not override). |
| `service.py` | Semantic-search orchestration. `semantic_search(user, query, limit, is_admin)` embeds the query → fetches candidates (`list_memos_db`) → get-or-computes each summary embedding (`_embedding_for_memo`) → ranks by cosine similarity (`_cosine`, pure Python), desc. **The only domain layer allowed to make network calls** (repositories must not). Tests monkeypatch `service.embed_text`. |
| `auth.py` | **Identification only** of the connected user. Transport (http vs stdio) is a startup-time constant: `main()` calls `set_http_transport()` once, and `transport_is_http()` reads that flag (no per-call `get_http_request()` try/except to "detect" the transport). `current_user()`: stdio → the value recorded by `set_stdio_user()`; HTTP → if `?client_id=` is present, looks up the in-memory `_http_user_by_client` map (initializing it from `?user=` via `setdefault`, so a prior `switch_user` value is preserved and middleware double-reads are idempotent), else falls back to `?user=` (backward compatible). In HTTP mode `get_http_request()` is called directly to read the request; if it ever raised outside a request context the error surfaces rather than silently degrading to stdio. Helpers: `http_client_id()`, `transport_is_http()`, `switch_http_user(client_id, target)`. The map is in-memory (reset on restart; no TTL — fine for personal/local use). |
| `authz.py` | **Authorization** (shared by both domains). `resolve_caller()` runs `current_user()` → registration check (`is_registered_user`) and returns `(user, is_admin, error)`. If `error` is set, the tool returns it and stops. Error constants (`NO_USER_ERROR` / `ADMIN_ONLY_ERROR` / `not_registered_error`) live here too. |
| `tools/__init__.py` | Side-effect import that loads the submodules (`memo`, `user`) to register the tools. |
| `tools/memo.py` | The 7 memo `@mcp.tool`s. Authorize via `resolve_caller()`, then pass `is_admin` down to `repository.memo` / `service`. Results are returned as JSON strings. `semantic_search_memos` calls `service.semantic_search` and turns `EmbeddingError` into a message. |
| `tools/user.py` | The 5 user-management `@mcp.tool`s (admin-only) plus `switch_user` (not admin-only). The 5 management tools return `ADMIN_ONLY_ERROR` unless `is_admin`; `delete_user` rejects `admin` itself. `switch_user` only requires `resolve_caller()` to succeed and `target` to be registered, then rewrites stdio user or the HTTP `client_id → user` map. |
| `logging_middleware.py` | `AuditLogMiddleware` (registered via `mcp.add_middleware`). Overrides `Middleware.on_message` — the outermost hook, so it captures every method incl. `initialize`. INFO: one line per `tools/call` (`tool/user/client_id/session`). DEBUG: full session picture for all methods (`method/request_id/client_id/raw_user/resolved_user/session`). `session` is the raw `Mcp-Session-Id` header. Resolves the user via `auth.current_user()`. |
| `main.py` | The `mcp` FastMCP instance (with `AuditLogMiddleware` added right after creation) and the entry point (`main()`). Reads `--user`/`MEMO_USER` and `--debug`/`MEMO_LOG_DEBUG` via argparse; calls `_configure_logging(debug)` (basicConfig to **stderr**; root stays INFO, only `memo.*` goes DEBUG so library noise is excluded). `TRANSPORT` switches stdio/http and is recorded once via `auth.set_http_transport()`; HTTP `HOST` defaults to `127.0.0.1` (local-only; see security note). Registers a `/health` check via `@mcp.custom_route`. |
| `tests/conftest.py` | Shared pytest setup. Redirects the DB path to a temp file, empties the tables before each test, and re-seeds `admin`. |
| `tests/test_memo_repository.py` | Unit tests for `repository.memo` (CRUD + search + user isolation + admin privilege). |
| `tests/test_user_repository.py` | Unit tests for `repository.user` (ledger CRUD + registration check). |
| `tests/test_embedding_repository.py` | Unit tests for `repository.embedding` (cache get / upsert / overwrite / delete). |
| `tests/test_semantic_search.py` | Unit tests for `service.semantic_search`. Monkeypatches `service.embed_text` to fixed vectors and verifies ranking, cache hits, recompute on summary change, user isolation, and admin cross-user (no network / API key needed). |
| `tests/test_mcp_client.py` | Integration tests through an MCP client (tool registration + authorization + admin cross-user + user management + semantic search; monkeypatches `service.embed_text`. Runs via `asyncio.run()` without depending on pytest-asyncio). Also covers `switch_user` (stdio path), the `current_user` HTTP `client_id` branches (monkeypatching `auth.get_http_request` with a dummy request), and the audit log (`caplog` for the INFO tool line and the DEBUG `initialize` line). |

`main.py` creates the `mcp` instance and adds `AuditLogMiddleware`, then imports `memo.tools` via side-effect import; `tools/__init__.py` loads the submodules (`tools.memo` / `tools.user`) to register all tools. `init_db()` is called at module level, so the DB is reliably initialized on every startup path.

### Layer dependency direction

`tools/*` → `authz` → `repository/*` → `database`, one-way. `authz` uses `auth` (identification) and `repository.user` (registration check). `database` depends on no domain layer. To add a new domain, add `repository/<domain>.py` and `tools/<domain>.py`, then add the load to `tools/__init__.py`. `logging_middleware` sits at the transport edge (it reads `auth` only) and is orthogonal to these layers.

Semantic search involves the network (OpenAI call) plus ranking, so it is not placed in the `repository` layer; a **`service` layer** is inserted: `tools/memo.py` → `service` → (`embedding`'s OpenAI call + `repository.embedding` / `repository.memo`). This keeps the invariant that `repository/*` is pure SQLite only, no network.

### Database

SQLite with WAL journaling (`memo.db`). `init_db()` creates the schema at server startup (idempotent). Each tool call returns a fresh connection for thread safety (`_connect_db`, `row_factory = sqlite3.Row`).

**`memos` table:**

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER PK | Auto-increment |
| `user` | TEXT NOT NULL | Owning user name. Indexed by `idx_memos_user` |
| `title` | TEXT NOT NULL | Title |
| `summary` | TEXT NOT NULL DEFAULT '' | Summary |
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

### User isolation / registration / admin privilege

A memo is owned by the connected user that created it. For regular callers (`is_admin=False`), every `*_memo_db` helper filters with `WHERE user = ?`, so other users' memos never appear in list/search, and supplying someone else's id to `get`/`update`/`delete` yields "no match" (None / False) — existence itself is not leaked.

Connections are allowed only for users registered in the `users` ledger. `resolve_caller()` rejects both the unidentified case (`current_user()` is None) and the unregistered case (`is_registered_user` is False). `admin` (`ADMIN_USER`) is the fixed user always seeded by `init_db()` via `INSERT OR IGNORE`, and cannot be deleted (`delete_user` guards it).

Only an `admin` connection invokes the memo tools with `is_admin=True`, dropping the user filter to operate on all users (including orphan memos with `user=''`). User-management tools (`*_user`) return an `admin-only` error unless `is_admin`. Deleting a user keeps their memos (a deleted user becomes unregistered and is refused connection, so the leftover memos are operable only by admin).

`init_db()` migrates a legacy DB lacking the `user` column via `ALTER TABLE ADD COLUMN user TEXT NOT NULL DEFAULT ''` (old memos become `user=''`: inaccessible to regular users but operable by admin).

### User switching

`switch_user(target)` changes the connection's current user without reconnecting/restarting, separating a **stable client identity** from the **mutable current user**:

- **stdio** (per-process, single user): rewrites the module-level `_stdio_user` via `set_stdio_user`. A single-assignment write is atomic under the GIL.
- **HTTP** (shared, multi-client): keyed by the self-supplied `?client_id=` query param, not by `Mcp-Session-Id`. `Mcp-Session-Id` is stable within one connection but **changes on reconnect (re-initialize)**, so it cannot persist switch state; `client_id` is stable across reconnects. `current_user()` seeds `_http_user_by_client[client_id]` from `?user=` with `setdefault` (first value wins), and `switch_user` overwrites it. HTTP without `client_id` cannot hold switch state and `switch_user` returns an error.

**Security**: switching is unauthenticated (personal/local assumption) — any caller can become any registered user incl. `admin`. This is why HTTP `HOST` defaults to `127.0.0.1`. Exposing on `0.0.0.0` requires fronting with real auth.

### Audit logging

`AuditLogMiddleware` (in `logging_middleware.py`, added via `mcp.add_middleware`) records every call from one place by overriding `Middleware.on_message` (the outermost hook in `_dispatch_handler`, so `initialize`/`tools/list`/`tools/call`/… all pass through). INFO emits one line per `tools/call`; DEBUG (via `--debug`/`MEMO_LOG_DEBUG`) emits the full session picture for all methods, including the raw `Mcp-Session-Id` header — the intended way to observe how the session id stays stable per connection and is replaced on reconnect, alongside the stable `client_id`. The user is resolved with `auth.current_user()` (the `setdefault` seeding makes this idempotent vs. the tool's own `resolve_caller()`). Logs go to **stderr** (stdout carries the stdio JSON-RPC stream); `_configure_logging` keeps root at INFO and raises only `memo.*` to DEBUG.

### Search

`search_memos_db(keywords: list[str], limit)` searches by title substring (`title LIKE '%kw%'`). Multiple keywords are joined with `OR`, returning any memo matching at least one. On the Python side each memo is annotated with `matched_keywords` (the list of keywords it matched). LIKE wildcards (`%` `_`) and `\` are literalized via `ESCAPE '\'`, so user input containing them does not match everything. SQLite's `LIKE` is case-insensitive over ASCII (the `matched_keywords` check is aligned with `str.lower()`).

The `search_memos` tool splits `query` on commas, drops empty/duplicate entries, and passes the keyword list to the DB layer.

### Semantic Search

`semantic_search_memos(query, limit=5)` is a separate tool that searches by **semantic closeness of the summary**. `service.semantic_search` computes the cosine similarity between the query embedding and each memo summary's embedding, attaches `similarity` (0–1), and returns up to `limit` results in descending order. Empty summaries are excluded. User isolation and admin cross-user reuse candidate fetching via `list_memos_db(..., is_admin=...)`, matching existing behavior.

Embeddings use the OpenAI API (`text-embedding-3-small`, multilingual) and require `OPENAI_API_KEY` (overridable via `MEMO_EMBEDDING_MODEL`). A missing key or API failure becomes `EmbeddingError`, which the tool returns as an `Error: ...` string (other tools are unaffected).

Embeddings are computed **lazily at search time** and cached in `memo_embeddings` (not computed in `create_memo`/`update_memo`). They are reused while `summary_hash` and `model` match; only memos whose summary or model changed are recomputed. `_CANDIDATE_CAP` (=1000) caps the ranking set to the newest-by-`updated_at` memos. Cache rows for deleted memos remain but are not read, so they are harmless (to clean them up, use `repository.embedding.delete_embedding`). Note that a first run with many uncached memos makes N+1 API calls (room for future batching).

### Tool result verbosity

`create_memo` / `update_memo` return a concise message similar to `delete_memo` (`Created memo id=N.` / `Updated memo id=N.`) rather than the full record, to limit LLM context consumption. When the record contents are needed, use `get_memo` / `list_memos` / `search_memos`.

### Changing the schema

Update the `CREATE TABLE` statements in `init_db()`. To add a column to an existing DB, follow the lightweight pattern used for the `user` column (`PRAGMA table_info` to check existence → `ALTER TABLE ADD COLUMN` if absent). If a full migration spanning multiple versions becomes necessary, refer to the `_MIGRATIONS` approach in `dynamic_prompt`.

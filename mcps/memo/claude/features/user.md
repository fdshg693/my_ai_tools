# Feature: User

## User switching

`switch_user(target)` changes the connection's current user without reconnecting/restarting, separating a **stable client identity** from the **mutable current user**. The success message also surfaces the target's memo categories (`list_categories_db`) so the caller can immediately scope follow-up `list_memos`/`search_memos`/`semantic_search_memos` calls by `category`:

- **stdio** (per-process, single user): rewrites the module-level `_stdio_user` via `set_stdio_user`. A single-assignment write is atomic under the GIL.
- **HTTP** (shared, multi-client): keyed by the self-supplied `?client_id=` query param, not by `Mcp-Session-Id`. `Mcp-Session-Id` is stable within one connection but **changes on reconnect (re-initialize)**, so it cannot persist switch state; `client_id` is stable across reconnects. `current_user()` seeds `_http_user_by_client[client_id]` from `?user=` with `setdefault` (first value wins), and `switch_user` overwrites it. HTTP without `client_id` cannot hold switch state and `switch_user` returns an error.

**Security**: switching is unauthenticated (personal/local assumption) — any caller can become any registered user incl. `admin`. This is why HTTP `HOST` defaults to `127.0.0.1`. Exposing on `0.0.0.0` requires fronting with real auth.

## User management web UI (`memo-admin`)

`server/web/` provides a browser UI for managing the `users` ledger without touching the DB by hand or going through Claude's `create_user` tool (`app.py` is the Starlette app body, `main.py` the `uvicorn` entry point). It is a **separate process** (`uv run memo-admin`) that opens the same `memo.db` (SQLite WAL makes concurrent multi-process access safe), so it works even when Claude Desktop isn't running. It deliberately follows the `dynamic_prompt` quiz-server precedent: Starlette + uvicorn + vanilla `static/` assets, no new framework and no Node build chain.

`create_app()` (in `server/web/app.py`) returns the Starlette app (used directly by tests); `main()` (in `server/web/main.py`) calls `init_db()` then `uvicorn.run` on `MEMO_ADMIN_HOST` (default `127.0.0.1`) / `MEMO_ADMIN_PORT` (default `8090`, chosen to avoid the memo HTTP `8080` and quiz `8765` defaults). The REST layer is thin — each handler maps to one `service.user` call and translates its domain exception to an HTTP status:

| Method | Path | service.user call | Notes |
|--------|------|-----------------|-------|
| GET | `/` | — | Serves `static/admin.html` |
| GET | `/api/users` | `list_users()` | Array, name-sorted |
| GET | `/api/users/{name}/memos` | `count_memos_db` + `list_memos_db` (repository, read-only) | Paginated memo list for one user (newest-first). Query `page` (1-based) / `per_page` (≤100, default 20) / `category` (optional filter). Returns `{user, items, page, per_page, total, total_pages}`; 404 (`UserNotFound`) |
| POST | `/api/users/{name}/memos` | `create_memo_db(name, title, summary, category)` (repository) | Create a memo owned by `name`. `title` required → 400; optional `category` (empty → `OTHERS`); user absent → 404; 201 on success |
| PUT | `/api/users/{name}/memos/{memo_id}` | `update_memo_db(name, memo_id, title, summary, category)` (repository, `is_admin=False`) | Partial update (omitted field unchanged); empty `title` → 400; memo not under that user → 404 |
| DELETE | `/api/users/{name}/memos/{memo_id}` | `delete_memo_db(name, memo_id)` (repository, `is_admin=False`) | Delete one of that user's memos; not found → 404; `{deleted: memo_id}` on success |
| POST | `/api/users` | `create_user(name, display_name, note)` | 400 (`NameRequired`); 409 (`UserAlreadyExists`); 201 on success |
| GET | `/api/users/{name}` | `get_user(name)` | 404 (`UserNotFound`) |
| PUT | `/api/users/{name}` | `update_user(name, display_name, note)` | Omitted fields stay unchanged (sends `None`); `name` immutable; 404 (`UserNotFound`) |
| DELETE | `/api/users/{name}` | `delete_user(name)` | 403 (`CannotDeleteAdmin`, the guard shared with the `delete_user` tool); 404 (`UserNotFound`) |

**Security**: unauthenticated, same model as `switch_user` — anyone who can reach the port can edit any user incl. `admin`. The default `127.0.0.1` bind keeps it local; `MEMO_ADMIN_HOST=0.0.0.0` logs a warning and must be fronted with real auth.

## Audit logging

`AuditLogMiddleware` (in `server/mcp/logging_middleware.py`, logger name `memo.server.mcp.logging_middleware`, added via `mcp.add_middleware`) records every call from one place by overriding `Middleware.on_message` (the outermost hook in `_dispatch_handler`, so `initialize`/`tools/list`/`tools/call`/… all pass through). INFO emits one line per `tools/call`; DEBUG (via `--debug`/`MEMO_LOG_DEBUG`) emits the full session picture for all methods, including the raw `Mcp-Session-Id` header — the intended way to observe how the session id stays stable per connection and is replaced on reconnect, alongside the stable `client_id`. The user is resolved with `auth.current_user()` (the `setdefault` seeding makes this idempotent vs. the tool's own `resolve_caller()`). Logs go to **stderr** (stdout carries the stdio JSON-RPC stream); `_configure_logging` keeps root at INFO and raises only `memo.*` to DEBUG.

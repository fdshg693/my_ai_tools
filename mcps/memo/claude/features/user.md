# Feature: User

## User switching

`switch_user(target)` changes the connection's current user without reconnecting/restarting, separating a **stable client identity** from the **mutable current user**. The success message also surfaces the target's registered categories (via `service.category.list_categories`, read from the `categories` table — per-user, no admin cross-user) so the caller can immediately pick a category for new memos or scope follow-up `list_memos`/`search_memos`/`semantic_search_memos` calls by `category`:

- **stdio** (per-process, single user): rewrites the module-level `_stdio_user` via `set_stdio_user`. A single-assignment write is atomic under the GIL.
- **HTTP** (shared, multi-client): keyed by the self-supplied `?client_id=` query param, not by `Mcp-Session-Id`. `Mcp-Session-Id` is stable within one connection but **changes on reconnect (re-initialize)**, so it cannot persist switch state; `client_id` is stable across reconnects. `current_user()` seeds `_http_user_by_client[client_id]` from `?user=` with `setdefault` (first value wins), and `switch_user` overwrites it. HTTP without `client_id` cannot hold switch state and `switch_user` returns an error.

**Security**: switching is unauthenticated (personal/local assumption) — any caller can become any registered user incl. `admin`. This is why HTTP `HOST` defaults to `127.0.0.1`. Exposing on `0.0.0.0` requires fronting with real auth.

## Admin tool visibility (server-level default + per-session enable)

The 5 user-management tools (`create_user` / `get_user` / `list_users` / `update_user` / `delete_user`) are tagged `admin` and their visibility uses FastMCP's official **Component Visibility** API (https://gofastmcp.com/servers/visibility) — implemented in `server/mcp/admin_tools.py`, **not** middleware. Two layers compose:

- **Server level (default off).** At startup `apply_server_default(mcp)` calls `mcp.disable(tags={"admin"})` after the tools are registered. So every fresh session — *including a connection that started as `admin`* — does not list the admin tools, and calling one by name returns FastMCP's native `Unknown tool` error (existence is not even leaked).
- **Session level (enable on switch to admin).** `switch_user` is `async` and receives an injected `ctx: Context`. After it rewrites the current user it calls `apply_session_visibility(ctx, target)`: if the new user is `admin` it does `ctx.enable_components(tags={"admin"})`, otherwise `ctx.disable_components(tags={"admin"})`. These apply to **that session only**, and FastMCP automatically emits `notifications/tools/list_changed`, so the client refreshes and sees the tools appear/disappear without reconnecting. (This auto-notification is the concrete reason not to reimplement visibility by filtering `tools/list` in middleware — a filter changes the list without telling the client.)

Because the trigger is `switch_user`, a connection that *started* as `admin` must `switch_user("admin")` once to enable the tools (switching to your own current user re-applies visibility). `switch_user` itself is untagged, so it is always visible — that is how any connection reaches `admin`.

**Safety switch.** "Just becoming `admin` makes destructive user-management tools appear" is risky under the unauthenticated `switch_user` model (anyone can become `admin`). `admin_tools_auto_enable()` reads `MEMO_ADMIN_TOOLS_AUTO_ENABLE` (env first, `mcps/memo/.env` fallback; default on; `0`/`false`/`no`/`off` = off). When off, `apply_session_visibility` skips the enable, so the admin tools stay disabled **even after switching to `admin`** — the only way to manage users then is the `memo-admin` web UI. This visibility layer sits *in front of* each tool's own `resolve_caller()`/`is_admin` check, not as a replacement (with the tools enabled the caller is `admin`, so the in-tool check passes; it remains as defense in depth).

## User management web UI (`memo-admin`)

`server/web/` provides a browser UI for managing the `users` ledger without touching the DB by hand or going through Claude's `create_user` tool (`app.py` is the Starlette app body, `main.py` the `uvicorn` entry point). It is a **separate process** (`uv run memo-admin`) that opens the same `memo.db` (SQLite WAL makes concurrent multi-process access safe), so it works even when Claude Desktop isn't running. It deliberately follows the `dynamic_prompt` quiz-server precedent: Starlette + uvicorn + vanilla `static/` assets, no new framework and no Node build chain.

`create_app()` (in `server/web/app.py`) returns the Starlette app (used directly by tests); `main()` (in `server/web/main.py`) calls `init_db()` then `uvicorn.run` on `MEMO_ADMIN_HOST` (default `127.0.0.1`) / `MEMO_ADMIN_PORT` (default `8090`, chosen to avoid the memo HTTP `8080` and quiz `8765` defaults). The REST layer is thin — each handler maps to one `service.user` call and translates its domain exception to an HTTP status:

| Method | Path | service.user call | Notes |
|--------|------|-----------------|-------|
| GET | `/` | — | Serves `static/admin.html` |
| GET | `/api/users` | `list_users()` | Array, name-sorted |
| GET | `/api/users/{name}/memos` | `count_memos` + `list_memos` (service) | Paginated memo list for one user (newest-first). Query `page` (1-based) / `per_page` (≤100, default 20) / `category` (optional filter). Returns `{user, items, page, per_page, total, total_pages}`; 404 (`UserNotFound`) |
| POST | `/api/users/{name}/memos` | `create_memo(name, title, summary, category)` (service) | Create a memo owned by `name`. `title` required → 400; `category` must be a registered category of `name` (empty → `OTHERS`) else 400 (`UnknownCategory`); user absent → 404; 201 on success |
| PUT | `/api/users/{name}/memos/{memo_id}` | `update_memo(name, memo_id, …, category)` (service) | Partial update (omitted field unchanged); empty `title` → 400; unregistered `category` → 400 (`UnknownCategory`); memo not under that user → 404 |
| DELETE | `/api/users/{name}/memos/{memo_id}` | `delete_memo(name, memo_id)` (service) | Delete one of that user's memos; not found → 404; `{deleted: memo_id}` on success |
| GET | `/api/users/{name}/categories` | `list_categories(name)` | That user's categories, name-sorted; 404 (`UserNotFound`) |
| POST | `/api/users/{name}/categories` | `create_category(name, body.name)` | 400 (`CategoryNameRequired`); 409 (`CategoryAlreadyExists`); 404 (`UserNotFound`); 201 |
| PUT | `/api/users/{name}/categories/{category_id}` | `rename_category_by_id(name, id, body.name)` | Rename; cascades to that user's memos. 400 / 403 (`CannotModifyOthers`) / 404 (`CategoryNotFound`) / 409 (`CategoryAlreadyExists`) |
| DELETE | `/api/users/{name}/categories/{category_id}` | `delete_category_by_id(name, id)` | Delete; reassigns linked memos to `OTHERS`. 403 (`CannotModifyOthers`) / 404 (`CategoryNotFound`); `{deleted: id}` |
| POST | `/api/users` | `create_user(name, display_name, note)` | 400 (`NameRequired`); 409 (`UserAlreadyExists`); 201 on success. Seeds the new user's `OTHERS` category |
| GET | `/api/users/{name}` | `get_user(name)` | 404 (`UserNotFound`) |
| PUT | `/api/users/{name}` | `update_user(name, display_name, note)` | Omitted fields stay unchanged (sends `None`); `name` immutable; 404 (`UserNotFound`) |
| DELETE | `/api/users/{name}` | `delete_user(name)` | 403 (`CannotDeleteAdmin`, the guard shared with the `delete_user` tool); 404 (`UserNotFound`). **Cascade-deletes** that user's memos, categories, and embeddings |

**Security**: unauthenticated, same model as `switch_user` — anyone who can reach the port can edit any user incl. `admin`. The default `127.0.0.1` bind keeps it local; `MEMO_ADMIN_HOST=0.0.0.0` logs a warning and must be fronted with real auth.

## Audit logging

`AuditLogMiddleware` (in `server/mcp/logging_middleware.py`, logger name `memo.server.mcp.logging_middleware`, added via `mcp.add_middleware`) records every call from one place by overriding `Middleware.on_message` (the outermost hook in `_dispatch_handler`, so `initialize`/`tools/list`/`tools/call`/… all pass through). INFO emits one line per `tools/call`; DEBUG (via `--debug`/`MEMO_LOG_DEBUG`) emits the full session picture for all methods, including the raw `Mcp-Session-Id` header — the intended way to observe how the session id stays stable per connection and is replaced on reconnect, alongside the stable `client_id`. The user is resolved with `auth.current_user()` (the `setdefault` seeding makes this idempotent vs. the tool's own `resolve_caller()`). Logs go to **stderr** (stdout carries the stdio JSON-RPC stream); `_configure_logging` keeps root at INFO and raises only `memo.*` to DEBUG.

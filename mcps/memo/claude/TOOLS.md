# Tools

The server exposes 15 MCP tools. **Memo tools (7):** `create_memo`, `get_memo`, `list_memos`, `search_memos`, `semantic_search_memos`, `update_memo`, `delete_memo`. **Category tools (2, create/read only):** `create_category`, `list_categories`. **User management tools (5, admin-only):** `create_user`, `get_user`, `list_users`, `update_user`, `delete_user`. **Session tool (1, not admin-only):** `switch_user`.

## Tool description vs. docstring

The tool description shown to MCP clients (the LLM) is given **explicitly** via the `@mcp.tool(description=...)` argument — it carries the caller-facing usage (purpose + each parameter). The function's **docstring is for coders only** (implementation notes: authorization flow, `is_admin` propagation, where normalization lives) and is *not* the tool description. Keep the two separated so caller-facing wording and code-maintenance notes don't bleed into each other (previously the docstring doubled as both). When adding a tool, supply `description=` for the caller and reserve the docstring for implementation detail. (Pattern precedent: `dynamic_prompt`'s `get_instruction`.)

## Memo tools

All callers — including `admin` — operate only on their own memos; other users' memos are reported as "not found" so existence is not leaked. There is no cross-user mode. See [features/memo.md](features/memo.md) for the access model and search behavior.

| Tool | Args | Behavior |
|------|------|----------|
| `create_memo` | `title`, `summary=""`, `category=""` | Create a memo owned by the connected user. `title` required. `category` normalized (empty → `OTHERS`); must be one of the caller's registered categories else `Error: category 'X' is not registered.` Returns a short message with the new id and normalized category. |
| `get_memo` | `memo_id` | Fetch one memo by id (incl. `category`). Own memos only. |
| `list_memos` | `limit=50`, `category=""` | List memos newest-first (`updated_at` desc). `category` (optional) restricts to one category; empty = all. Own memos only. |
| `search_memos` | `query`, `limit=50`, `category=""` | Title substring search. `query` is comma-split into OR keywords; each result carries `matched_keywords`. `category` (optional) restricts to one category. Own memos only. |
| `semantic_search_memos` | `query`, `limit=5`, `category=""` | Semantic search over **summaries**. Results carry `similarity` (0–1), sorted desc; empty summaries are excluded. `category` (optional) restricts to one category. Own memos only. Needs `OPENAI_API_KEY`. |
| `update_memo` | `memo_id`, `title=None`, `summary=None`, `category=None` | Update only the supplied fields. `category=None` leaves it unchanged; empty string resets to `OTHERS`; a non-empty value must be a registered category else an error. Own memos only. |
| `delete_memo` | `memo_id` | Delete a memo. Own memos only. |

## Category tools (create/read only)

Categories are per-user (see [features/category.md](features/category.md)). MCP exposes only create + list; rename/delete are done from the `memo-admin` web UI. Both scope to the connected user (`admin` sees only its own categories).

| Tool | Args | Behavior |
|------|------|----------|
| `create_category` | `name` | Create a category for the connected user. `name` required, normalized (uppercase). Returns a no-op-style message if it already exists. |
| `list_categories` | — | List the connected user's categories (JSON array, name-sorted). |

## User management tools (admin-only)

These 5 tools are tagged `admin` and their visibility is controlled by FastMCP's **Component Visibility** API (see [features/user.md](features/user.md) and `server/mcp/admin_tools.py`): they are **disabled at the server level by default**, so a fresh session does not list them and calling one by name returns `Unknown tool`. They become visible/callable **only after `switch_user("admin")`** on that connection (per-session enable), and only while the auto-enable switch `MEMO_ADMIN_TOOLS_AUTO_ENABLE` is on (set it falsy — `0`/`false`/`no`/`off` — to keep them disabled even for `admin`). Switching to a non-admin re-hides them. Behind this each tool still returns an `admin-only` error unless the caller is `admin` (defense in depth).

| Tool | Args | Behavior |
|------|------|----------|
| `create_user` | `name`, `display_name=""`, `note=""` | Register a user. `name` required, unique identifier. Returns a no-op message if it already exists. |
| `get_user` | `name` | Fetch one user. |
| `list_users` | — | List registered users by name. |
| `update_user` | `name`, `display_name=None`, `note=None` | Update attributes (display name / note). `name` (identifier) is immutable. |
| `delete_user` | `name` | Remove a user from the ledger (memos kept). `admin` itself cannot be deleted. |

## Session tool (not admin-only)

Any registered caller may switch the current user. See [features/user.md](features/user.md) for the stdio/HTTP mechanics.

| Tool | Args | Behavior |
|------|------|----------|
| `switch_user` | `target` | Switch the connection's current user to `target` (must be registered; `admin` allowed) without reconnecting/restarting. On success the message also lists the **target's registered categories** (`service.category.list_categories(target)`, read from the `categories` table — per-user) — a hint for picking a category on new memos or for `category` filtering. stdio: rewrites the process user via `set_stdio_user`. HTTP: requires `?client_id=`; updates the `client_id → user` map. Errors if `target` unregistered or (HTTP) `client_id` absent. **Also updates admin-tool visibility for this session**: switching to `admin` enables the admin-tagged tools (unless `MEMO_ADMIN_TOOLS_AUTO_ENABLE` is off), switching away disables them (`list_changed` is sent to the client automatically). |

## Tool result verbosity

`create_memo` / `update_memo` return a concise message similar to `delete_memo` (`Created memo id=N.` / `Updated memo id=N.`) rather than the full record, to limit LLM context consumption. When the record contents are needed, use `get_memo` / `list_memos` / `search_memos`.

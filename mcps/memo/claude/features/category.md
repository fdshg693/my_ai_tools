# Feature: Category

Categories are a **first-class, per-user entity** stored in the `categories` table (`(user, name)` unique), not just a string column derived from memos. Every memo still carries a `memos.category` value, but that value must be one of the owning user's registered categories (or the always-present default `OTHERS`). Category names are normalized on write by `repository.category.normalize_category()` — **trim + uppercase**, empty/`None` → `OTHERS` (`OTHERS_CATEGORY` in `infra/database.py`) — so `work` / `Work` / `WORK` are one category and stored values are always canonical uppercase.

Categories are scoped to the owning user in every operation. `admin` is **not** special for categories: it only manages the `users` ledger and otherwise behaves like a normal user with its own categories (no cross-user category access).

## Ownership & the OTHERS default

- A new user is seeded with **only** `OTHERS` (`service.user.create_user` → `repository.category.ensure_default_category_db`). `init_db()` also seeds `OTHERS` for every existing user and back-fills every distinct `(user, category)` already present on memos, so existing data stays valid.
- `OTHERS` is the default fallback and **cannot be renamed or deleted** (`service.category` raises `CannotModifyOthers`). It always counts as "registered" for memo validation.

## Memo ⇄ category invariant (validation)

A memo can only be linked to a category its owner has registered. Note this is *not* a DB foreign key: `memos.category` is a denormalized string kept in sync by triggers (the "reassign to the owner's `OTHERS`" delete behavior is per-row dynamic and can't be an FK action — see [SCHEMA.md](../SCHEMA.md)). The "must be registered" rule is therefore an application invariant enforced in **`service.memo`** (the repository stays permissive):

- `create_memo` / `update_memo` call `_require_known_category(user, category)`: the normalized category must be `OTHERS` or exist via `repository.category.category_exists_db(user, name)`, else `UnknownCategory` is raised. Each edge translates it (MCP → `Error: category 'X' is not registered. Create it first.`, web → HTTP 400).
- On `update_memo`, `category=None` means unchanged (no check); `category=""` resets to `OTHERS` (always allowed).

## Category CRUD

`service.category` holds the domain rules (mirroring `service.user`), returning dicts or raising domain exceptions (`CategoryError` base: `CategoryNameRequired`, `CategoryAlreadyExists`, `CategoryNotFound`, `CannotModifyOthers`):

- **create** — name required + normalized; duplicate → `CategoryAlreadyExists`.
- **rename** — `OTHERS` forbidden; source must exist; renaming to a different existing name collides (`CategoryAlreadyExists`); renaming to the same normalized name is a no-op-allowed. **Cascade (DB-side)**: `repository.category.rename_category_db` only renames the `categories` row; the `trg_categories_rename_cascade` trigger (`AFTER UPDATE OF name`) repoints `memos.category` for that owner in the same statement, so linked memos follow automatically.
- **delete** — `OTHERS` forbidden; **reassign (DB-side)**: `repository.category.delete_category_db` only deletes the `categories` row; the `trg_categories_delete_reassign` trigger (`BEFORE DELETE`, skipping `OTHERS`) first sets linked memos to `OTHERS`. Both happen in the one delete statement's transaction.

`service.category` also exposes `rename_category_by_id` / `delete_category_by_id` for the web layer, which addresses categories by numeric id (resolves id → name via `get_category_db`, then delegates to the name-based rule).

## Surfaces

- **MCP tools (C/R only)** — `create_category(name)` and `list_categories()` in `tools/category.py`. Update/Delete are intentionally **not** exposed over MCP (managed from the web UI). Both scope to the connected user.
- **Web UI** — full per-user CRUD under `/api/users/{name}/categories` (see [user.md](user.md) for the route table). The memo editor's category field is a `<select>` populated from the user's categories; a category-management panel lists/creates/renames/deletes them (the `OTHERS` row has no rename/delete controls, and the server returns 403 anyway).

## Read filter (unchanged)

Category is still a read filter: `list_memos` / `search_memos` / `semantic_search_memos` (MCP) and the web memo list accept an optional `category` restricting results to one category (empty/`None` = all). The filter is built once in `repository.memo._base_filter(user, category)`, shared by `list_memos_db` / `count_memos_db` / `search_memos_db`; `semantic_search` passes `category` straight through.

## Layering

`repository.category` imports only from `infra` (no `repository.memo` import → no cycle); the cascade to `memos` is done by the DB triggers (defined in `infra.database._create_triggers`), not raw SQL in the repository. `repository.memo` imports `normalize_category` from `repository.category` (one-way `memo → category`). The `switch_user` MCP tool surfaces a user's category list via `service.category.list_categories` (transport edge → service, not repository).

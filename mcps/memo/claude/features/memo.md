# Feature: Memo

## User isolation / registration

A memo is owned by the connected user that created it. **Every** `*_memo_db` helper filters with `WHERE user = ?` (there is no cross-user mode), so other users' memos never appear in list/search, and supplying someone else's id to `get`/`update`/`delete` yields "no match" (None / False) — existence itself is not leaked. This applies to **all** callers including `admin`: `admin` is just a normal user that can also manage the `users` ledger — it cannot read, list, search, update, or delete another user's memos.

Connections are allowed only for users registered in the `users` ledger. `resolve_caller()` rejects both the unidentified case (`current_user()` is None) and the unregistered case (`is_registered_user` is False). `admin` (`ADMIN_USER`) is always seeded by `init_db()` via `INSERT OR IGNORE`, and cannot be deleted (`delete_user` guards it). `resolve_caller()` still returns `is_admin`, but it is used **only** to gate the user-management tools (`*_user` return an `admin-only` error unless `is_admin`); memo and category tools ignore it.

Deleting a user **cascades**: their memos, categories, and embedding cache rows are removed in one transaction (`repository.user.delete_user_db`), so no orphan data is left behind. See [user.md](user.md).

`init_db()` migrates a legacy DB lacking the `user` column via `ALTER TABLE ADD COLUMN user TEXT NOT NULL DEFAULT ''`. Any pre-existing `user=''` rows (orphans from such a migration) are no longer special-cased — with cross-user access removed, they are simply inaccessible.

## Search

`search_memos_db(keywords: list[str], limit)` searches by title substring (`title LIKE '%kw%'`). Multiple keywords are joined with `OR`, returning any memo matching at least one. On the Python side each memo is annotated with `matched_keywords` (the list of keywords it matched). LIKE wildcards (`%` `_`) and `\` are literalized via `ESCAPE '\'`, so user input containing them does not match everything. SQLite's `LIKE` is case-insensitive over ASCII (the `matched_keywords` check is aligned with `str.lower()`).

The `search_memos` tool splits `query` on commas, drops empty/duplicate entries, and passes the keyword list to the DB layer.

## Semantic Search

`semantic_search_memos(query, limit=5)` is a separate tool that searches by **semantic closeness of the summary**. `service.semantic_search` computes the cosine similarity between the query embedding and each memo summary's embedding, attaches `similarity` (0–1), and returns up to `limit` results in descending order. Empty summaries are excluded. User isolation reuses candidate fetching via `list_memos_db(user, ...)` (always the connected user's memos only).

Embeddings use the OpenAI API (`text-embedding-3-small`, multilingual) and require `OPENAI_API_KEY` (overridable via `MEMO_EMBEDDING_MODEL`). A missing key or API failure becomes `EmbeddingError`, which the tool returns as an `Error: ...` string (other tools are unaffected).

Embeddings are computed **lazily at search time** and cached in `memo_embeddings` (not computed in `create_memo`/`update_memo`). They are reused while `summary_hash` and `model` match; only memos whose summary or model changed are recomputed. `_CANDIDATE_CAP` (=1000) caps the ranking set to the newest-by-`updated_at` memos. Cache rows for deleted memos remain but are not read, so they are harmless (to clean them up, use `repository.embedding.delete_embedding`). Note that a first run with many uncached memos makes N+1 API calls (room for future batching).

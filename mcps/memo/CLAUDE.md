# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

> **About this file**: CLAUDE.md is the AI-facing document. Keep implementation and investigation details here, written in **English**. Human-facing material (startup steps, app overview, caveats) belongs in [README.md](./README.md), written in Japanese. Preserve this split when editing either file.
>
> **Structure**: This file is an entry point. Detailed documentation is split under [claude/](./claude/) by topic and imported below. When editing a detail, edit the relevant `claude/` file (not this entry point); add new topics as new `claude/` files and import them here.

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

# Run the standalone user-management web UI (separate process; opens 127.0.0.1:8090)
# Reads/writes the same memo.db. Bind/port via MEMO_ADMIN_HOST / MEMO_ADMIN_PORT.
uv run memo-admin

# Emit the full session picture (Mcp-Session-Id etc.) at DEBUG level on stderr
uv run memo --user alice --debug        # or env MEMO_LOG_DEBUG=1

# Migrate an existing DB to the latest schema (idempotent; same init_db() runs on startup)
# Targets MEMO_DB_PATH / the default memo.db, or pass a path. Prints schema_version before->after.
uv run memo-migrate            # or: uv run memo-migrate /path/to/memo.db

# Unit tests (DB CRUD / search / user isolation / categories / user ledger / switch / audit log / migrations)
uv run --project mcps/memo pytest mcps/memo/src/memo/tests/ -v

# Inspect the registered tools via an MCP client (in-process connection)
uv run python -m memo.tests.test_mcp_client

# To exercise semantic search against the real API you need an OpenAI key
OPENAI_API_KEY=sk-... uv run memo --user admin
```

## Documentation map

Detailed docs live in [claude/](./claude/), split by topic:

@./claude/CONVENTIONS.md
@./claude/SCHEMA.md
@./claude/FOLDER_STRUCTURE.md
@./claude/TOOLS.md
@./claude/features/memo.md
@./claude/features/user.md
@./claude/features/category.md

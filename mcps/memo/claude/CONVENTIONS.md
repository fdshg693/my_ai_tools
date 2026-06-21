# Coding Conventions

How to write code in this package. Read this before adding or changing behavior.

## FastMCP: always follow the official documentation

**Never guess or recall a FastMCP API from memory. Always consult the official docs first: https://gofastmcp.com** (the relevant page for the area you are touching — e.g. Tools, Context, Visibility, Middleware). Inventing method names, arguments, or behavior is not acceptable; FastMCP's API is specific and changes between versions.

Concrete rules:

- **Find the right doc page and use the documented API verbatim.** For example, component visibility is done with the documented `mcp.enable()/disable(tags=...)` (server level) and `ctx.enable_components()/disable_components()/reset_visibility()` (per-session), **not** with hand-rolled middleware that rewrites `tools/list`. The official per-session API also emits `notifications/tools/list_changed` automatically — a middleware filter does not, which is exactly the kind of bug guessing produces.
- **Verify against the installed version before writing.** The pinned version is in `pyproject.toml` / `uv.lock`. A quick `uv run --project mcps/memo python -c "import fastmcp; print(fastmcp.__version__)"` and `inspect.signature(...)` / `hasattr(...)` check confirms the symbol exists and the signature matches the docs before you depend on it.
- **Prefer the framework's built-in mechanism over a custom one.** If FastMCP already provides a feature (visibility, context injection, tags, middleware hooks), use it instead of reimplementing it at a lower layer. Reach for middleware only for genuinely cross-cutting concerns (e.g. the audit log in `logging_middleware.py`), not for per-tool or per-session behavior the framework already models.
- **Link the doc page in comments/docstrings** when the behavior is non-obvious, so the next editor can re-check it (see `server/mcp/admin_tools.py`, which cites the Visibility page).

Reference notes for FastMCP itself (how-to summaries, links) live in [../../../memo/fastmcp/](../../../memo/fastmcp/) (e.g. `basic.md`). Extend those when you learn a new pattern.

## Layering & responsibility

Keep the one-way layer direction described in [FOLDER_STRUCTURE.md](./FOLDER_STRUCTURE.md): `server/{mcp,web}` → `service/*` → `repository/*` → `infra/*`. Don't make a repository call the network or read request context; don't put authorization in `service`. Split files by domain and layer rather than growing one module.

## Environment variables

Read configuration env-first with a `mcps/memo/.env` fallback (`python-dotenv`'s `load_dotenv`), and **let already-set environment variables win** (do not override the process env from `.env`). Mirror the existing helpers (`infra/embedding.py`, `server/mcp/admin_tools.py`): a small named accessor function that parses the value, with a sensible default, rather than scattering `os.environ.get(...)` across call sites. Document every new variable in `README.md` (Japanese, human-facing) and, when relevant, in the AI-facing docs here.

## Documentation split

`CLAUDE.md` and `claude/*` are AI-facing and **English**; `README.md` / `TOOLS.md` / `USECASE.md` are human-facing and **Japanese**. Keep implementation/investigation detail out of the Japanese files and startup/overview material out of the English ones. When you add a topic here, import it from the `CLAUDE.md` documentation map.

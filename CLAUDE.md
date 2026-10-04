# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

MCP server (Python, mcp 2 `MCPServer` over stdio) wrapping the Brewfather v2 REST API. User docs, tool table, and setup live in README.md.

## Commands

```bash
uv sync                                   # install (incl. dev group)
uv run ruff check . && uv run ruff format --check .
uv run pytest                             # unit tests; acceptance auto-skipped
uv run pytest tests/unit/test_server.py::test_find_batches_rejects_unknown_status
uv run pytest --run-acceptance            # live read-only API checks; needs BREWFATHER_USER_ID/API_KEY
uv run python scripts/live_check_writes.py [--inventory]  # manual live write check; creates one scratch recipe (+ one hop)
```

## Architecture

Three modules in `src/mcp_server_brewfather/`, layered one direction:

- `client.py` — httpx wrapper: Basic auth from env, `start_after` pagination (`PAGE_SIZE` 50), and every failure (incl. 429) raised as `BrewfatherError` with a model-readable message. PATCH endpoints return plain text, not JSON.
- `normalize.py` — projects multi-KB API objects down to compact dicts; epoch-ms → ISO; missing/None fields omitted, never returned as null.
- `server.py` — the `@mcp.tool()` functions. Validate all input (statuses, measurement keys, inventory kinds) *before* any request is sent.

Tools must call `client.get_client()` through the module (not `from .client import get_client`): the `fake_api` fixture in `tests/conftest.py` monkeypatches that attribute. `fake_api` routes `(method, path)` to a body, a list of pages (list of lists), or an `httpx.Response`, and records requests for assertions.

## Constraints

- No tool may call a delete endpoint. The API key's scopes are the trust boundary.
- The recipe API accepts any field silently and never computes recipe stats (the app does). Writes go through field allowlists in `server.py`; never make stats writable.
- Batch PATCH ignores undocumented fields and answers `Nothing to update`; batch notes and the log (`batchNotes`, `notes`) can't be written. Don't retry (#25).
- Recipe ingredient lists are replaced wholesale on PATCH — send full raw items, never the compact projection.
- Inventory PATCH merges details (unsent fields kept); a body of only `inventory`/`inventory_adjust` is stock-only. List endpoints omit fields like `origin` unless `complete=true` (#12).
- Keep dependencies to `mcp` and `httpx`.
- Raise `ToolError` (or `BrewfatherError`, a subclass) for anything the model should read: mcp 2 replaces any other exception's message with a generic "Error executing tool".
- Annotate tools `-> dict[str, Any]` or `-> list[dict]`: a bare `-> dict` gets no output schema and no structured content (#13).
- API is metric-only (SG, L, kg/g, °C).
- Acceptance tests must stay read-only. Detail fields added to `normalize.py` should be verified there against live objects.
- Adding/changing a tool: update the README tool table and the `server.py` module docstring.
- Commits use conventional format; PR titles must **not** (CI enforces).
- Releases: release-please (`release-please.yml`, GitHub App token) opens the release PR and syncs `uv.lock` on it; the `v*` tag it creates triggers `release.yml`, which publishes to PyPI via trusted publishing. Never bump versions or tag by hand.

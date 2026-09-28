# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

MCP server (Python, FastMCP over stdio) wrapping the Brewfather v2 REST API. User docs, tool table, and setup live in README.md.

## Commands

```bash
uv sync                                   # install (incl. dev group)
uv run ruff check . && uv run ruff format --check .
uv run pytest                             # unit tests; acceptance auto-skipped
uv run pytest tests/unit/test_server.py::test_find_batches_rejects_unknown_status
uv run pytest --run-acceptance            # live read-only API checks; needs BREWFATHER_USER_ID/API_KEY
```

## Architecture

Three modules in `src/mcp_server_brewfather/`, layered one direction:

- `client.py` — httpx wrapper: Basic auth from env, `start_after` pagination (`PAGE_SIZE` 50), and every failure (incl. 429) raised as `BrewfatherError` with a model-readable message. PATCH endpoints return plain text, not JSON.
- `normalize.py` — projects multi-KB API objects down to compact dicts; epoch-ms → ISO; missing/None fields omitted, never returned as null.
- `server.py` — the `@mcp.tool()` functions. Validate all input (statuses, measurement keys, inventory kinds) *before* any request is sent.

Tools must call `client.get_client()` through the module (not `from .client import get_client`): the `fake_api` fixture in `tests/conftest.py` monkeypatches that attribute. `fake_api` routes `(method, path)` to a body, a list of pages (list of lists), or an `httpx.Response`, and records requests for assertions.

## Constraints

- No tool may call a delete endpoint; recipes stay read-only. The API key's scopes are the trust boundary.
- Keep dependencies to `mcp` and `httpx`. `mcp` is capped `<2` because v2 removed `mcp.server.fastmcp`.
- API is metric-only (SG, L, kg/g, °C).
- Acceptance tests must stay read-only. Detail fields added to `normalize.py` should be verified there against live objects.
- Adding/changing a tool: update the README tool table and the `server.py` module docstring.
- Commits use conventional format; PR titles must **not** (CI enforces).

# mcp-server-brewfather

An MCP server for the [Brewfather](https://brewfather.app) API. It lets an LLM read
your batches, recipes, fermentation readings, and inventory, and make the routine
writes that come up while brewing: advancing a batch's status, logging measured
gravities and volumes, tweaking a recipe, and adjusting stock after brew day.

Brewfather has no official MCP server; this wraps the public
[v2 API](https://docs.brewfather.app/api) directly.

## Tools

| Tool | What it does |
|------|--------------|
| `find_batches(name?, status?)` | Find batches by name substring and/or status → `{id, name, batch_no, status, brewer, brew_date, recipe}` |
| `get_batch(batch_id)` | Batch summary, measured values, notes and log entries, scheduled events (brew day, dry hop, bottling, …), and embedded recipe (stats + ingredient bill) |
| `get_readings(batch_id, limit?)` | Most recent hydrometer/sensor readings, oldest→newest (`limit=0` for all) |
| `get_brewtracker(batch_id)` | Brew-day tracker: current stage and step, seconds left on the stage timer, upcoming steps, next stage |
| `update_batch(batch_id, status?, measurements?)` | Set status and/or `measured*` values (validated before sending) |
| `find_recipes(name?)` | Find recipes by name substring → `{id, name, author, type, style, equipment}` |
| `get_recipe(recipe_id)` | Target stats (OG, FG, ABV, IBU, color, …) and ingredient bill |
| `create_recipe(name, type?, fields?, ingredients?)` | New All Grain or Extract recipe with settings and an ingredient bill |
| `update_recipe(recipe_id, fields?, ingredients?)` | Change settings (batch size, boil time, efficiency, …) and add/change/remove ingredients |
| `list_inventory(kind, name?, in_stock_only?)` | Fermentables, hops, miscs, or yeasts in stock |
| `set_inventory(kind, item_id, amount? \| adjust?)` | Set absolute stock, or add/subtract |
| `create_inventory_item(kind, name, fields?, amount?)` | Add an inventory item with details (supplier, alpha, color, attenuation, …) and optional starting stock |
| `update_inventory_item(kind, item_id, fields)` | Change an item's details (name, supplier, alpha, color/potential, attenuation, …); stock goes through `set_inventory` |

All values are metric (SG, liters, kg/g, °C) — the API accepts nothing else.
Timestamps are returned as ISO-8601 UTC.

Brewfather computes recipe stats (OG, FG, ABV, IBU, color) in the app, not the API.
After `create_recipe` or `update_recipe`, the app shows correct stats as soon as you
open the recipe, but `get_recipe` returns the stored values, which the API never
calculates (a new recipe has none).
Stats can't be written through this server.

Batch notes and log entries are read-only: `get_batch` returns them, but the API
ignores any attempt to write them, so add notes in the Brewfather app.

## Setup

### 1. Generate an API key

In Brewfather: **Settings → API → Generate API Key**. Pick scopes to match what you
want the server to do (see [Security posture](#security-posture)). Note the
**User ID** shown alongside the key.

### 2. Install

Requires Python **3.12+**. With [uv](https://docs.astral.sh/uv/), there is nothing
to install: `uvx` fetches and runs the published package. Otherwise:

```bash
pip install mcp-server-brewfather
# or, isolated:
pipx install mcp-server-brewfather
```

## Register with Claude

Claude Code:

```bash
claude mcp add brewfather --scope user \
  -e BREWFATHER_USER_ID=your_user_id -e BREWFATHER_API_KEY=your_api_key \
  -- uvx mcp-server-brewfather
```

Claude Desktop (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "brewfather": {
      "command": "uvx",
      "args": ["mcp-server-brewfather"],
      "env": {
        "BREWFATHER_USER_ID": "your_user_id",
        "BREWFATHER_API_KEY": "your_api_key"
      }
    }
  }
}
```

## Security posture

- **The API key's scopes are the trust boundary.** For read-only use, grant only
  `batches.read`, `recipes.read`, `inventory.read`. Add `batches.write` /
  `recipes.write` / `inventory.write` to enable `update_batch` / `create_recipe` and
  `update_recipe` / `set_inventory`, `create_inventory_item` and
  `update_inventory_item`. **Never grant `*.delete`** — no tool uses it.
- No delete tools. Every write is checked against an allowlist of fields before
  it's sent, because the API silently accepts unknown fields.
- **Two dependencies only** (`mcp`, `httpx` — the latter already required by `mcp`);
  pinned via the committed `uv.lock`.
- Credentials live in a gitignored `.env` / Claude config.

## Rate limits

Brewfather allows **500 calls per hour per API key**. List tools page 50 items per
call, so `find_*`/`list_inventory` cost one call per 50 items. A rate-limited call
surfaces as an error naming the `Retry-After` delay.

## Development

```bash
cp .env.example .env             # then fill in your user id / API key
source .env
uv sync                          # install deps (incl. dev group)
uv run ruff check .              # lint
uv run ruff format .             # format
uv run pytest                    # unit tests (acceptance auto-skipped)
uv run pytest --run-acceptance   # + live read-only API checks (needs BREWFATHER_* creds)
```

CI (GitHub Actions) runs the PR-title check, ruff lint/format, and the unit tests
on every PR; the `CI Success` job is the aggregate gate. Acceptance tests are not
run in CI — they need live credentials and stay local/manual. They are read-only
and never modify your brewing data.

The write tools have a separate manual live check, also never run in CI:

```bash
uv run python scripts/live_check_writes.py               # needs recipes.read + recipes.write
uv run python scripts/live_check_writes.py --inventory   # also needs inventory.read + inventory.write
```

It creates one scratch recipe named `MCP live-check <timestamp> (delete me)`, runs
`update_recipe` against it (change, add, remove, settings, stale-index guard) and
prints PASS/FAIL per check. With `--inventory` it also creates one scratch hop with
the same name and checks `update_inventory_item` (that a details edit merges rather
than replaces the item) and `set_inventory` on it. It writes to nothing else. The
server can't delete, so delete the scratch recipe (and hop) in the Brewfather app
afterwards; the script prints their names and ids.

Releases are automated: release-please keeps a release PR open from the
conventional commits on `main`, and merging it tags `vX.Y.Z`, which triggers
`release.yml` to publish to PyPI via trusted publishing.

## License

MIT — see [LICENSE](LICENSE).

"""FastMCP server exposing Brewfather batches, recipes, readings, and inventory.

Eight tools: find_batches, get_batch, get_readings, update_batch, find_recipes,
get_recipe, list_inventory, set_inventory. Reads cover everything the v2 API
exposes; writes are limited to batch status/measurements and inventory stock.
Nothing here deletes, and recipes are read-only.
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from . import client
from .normalize import (
    INVENTORY_KINDS,
    compact_batch,
    compact_batch_summary,
    compact_inventory,
    compact_reading,
    compact_recipe,
    compact_recipe_summary,
)

mcp = FastMCP("brewfather")

BATCH_STATUSES = ("Planning", "Brewing", "Fermenting", "Conditioning", "Completed", "Archived")

# Measured values PATCH /batches/:id accepts. Gravities are SG, volumes liters,
# temperatures Celsius — the API is metric-only.
BATCH_MEASUREMENTS = (
    "measuredMashPh",
    "measuredBoilSize",
    "measuredFirstWortGravity",
    "measuredPreBoilGravity",
    "measuredPostBoilGravity",
    "measuredKettleSize",
    "measuredOg",
    "measuredFermenterTopUp",
    "measuredBatchSize",
    "measuredFg",
    "measuredBottlingSize",
    "carbonationTemp",
)


def _matches(obj: dict, needle: str) -> bool:
    return not needle or needle in (obj.get("name") or "").lower()


def _check_kind(kind: str) -> None:
    if kind not in INVENTORY_KINDS:
        raise ValueError(f"unknown inventory kind: {kind!r} (use {', '.join(INVENTORY_KINDS)})")


@mcp.tool()
def find_batches(name: str = "", status: str = "") -> list[dict]:
    """Find batches by name (case-insensitive substring) and/or status.

    ``status`` is one of Planning, Brewing, Fermenting, Conditioning, Completed,
    Archived; empty means any. Returns compact dicts:
    {id, name, batch_no, status, brewer, brew_date, recipe}. Use the id with
    get_batch / get_readings / update_batch.
    """
    if status and status not in BATCH_STATUSES:
        raise ValueError(f"unknown status: {status!r} (use {', '.join(BATCH_STATUSES)})")
    params = {"status": status} if status else {}
    needle = name.strip().lower()
    batches = client.get_client().paginate("batches", params)
    return [compact_batch_summary(b) for b in batches if _matches(b, needle)]


@mcp.tool()
def get_batch(batch_id: str) -> dict:
    """Read one batch: summary, fermentation/bottling dates, estimated targets
    (OG, FG, IBU, color), all measured values, and the embedded recipe (target
    stats + ingredient bill). Units are metric (SG, L, °C).
    """
    return compact_batch(client.get_client().get(f"batches/{batch_id}"))


@mcp.tool()
def get_readings(batch_id: str, limit: int = 20) -> dict:
    """Read a batch's sensor readings (hydrometer, e.g. Tilt/iSpindel), newest last.

    Returns {total, readings: [{time, sg, temp, ...}]} with only the most recent
    ``limit`` readings (0 = all — can be thousands over a fermentation).
    Temperatures are °C.
    """
    raw = client.get_client().get(f"batches/{batch_id}/readings")
    readings = sorted(raw, key=lambda r: r.get("time") or 0)
    if limit > 0:
        readings = readings[-limit:]
    return {"total": len(raw), "readings": [compact_reading(r) for r in readings]}


@mcp.tool()
def update_batch(
    batch_id: str, status: str | None = None, measurements: dict[str, float] | None = None
) -> dict:
    """Update a batch's status and/or measured values.

    ``status``: Planning, Brewing, Fermenting, Conditioning, Completed, Archived.
    ``measurements`` keys (metric only — gravities SG, volumes liters, temps °C):
    measuredMashPh, measuredBoilSize, measuredFirstWortGravity,
    measuredPreBoilGravity, measuredPostBoilGravity, measuredKettleSize,
    measuredOg, measuredFermenterTopUp, measuredBatchSize, measuredFg,
    measuredBottlingSize, carbonationTemp. Returns {batch_id, result}.
    """
    body: dict = {}
    if status is not None:
        if status not in BATCH_STATUSES:
            raise ValueError(f"unknown status: {status!r} (use {', '.join(BATCH_STATUSES)})")
        body["status"] = status
    for key, value in (measurements or {}).items():
        if key not in BATCH_MEASUREMENTS:
            raise ValueError(f"unknown measurement: {key!r} (use {', '.join(BATCH_MEASUREMENTS)})")
        body[key] = value
    if not body:
        raise ValueError("nothing to update: pass status and/or measurements")
    result = client.get_client().patch(f"batches/{batch_id}", body)
    return {"batch_id": batch_id, "result": result}


@mcp.tool()
def find_recipes(name: str = "") -> list[dict]:
    """Find recipes by name (case-insensitive substring; empty returns all).

    Returns compact dicts: {id, name, author, type, style, equipment}.
    """
    needle = name.strip().lower()
    recipes = client.get_client().paginate("recipes")
    return [compact_recipe_summary(r) for r in recipes if _matches(r, needle)]


@mcp.tool()
def get_recipe(recipe_id: str) -> dict:
    """Read one recipe: summary, target stats (batchSize, og, fg, abv, ibu, color, …)
    and ingredient bill (fermentables, hops, miscs, yeasts). Units are metric.
    """
    return compact_recipe(client.get_client().get(f"recipes/{recipe_id}"))


@mcp.tool()
def list_inventory(kind: str, name: str = "", in_stock_only: bool = False) -> list[dict]:
    """List inventory items of one ``kind``: fermentables, hops, miscs, or yeasts.

    Filter by ``name`` (case-insensitive substring) and/or ``in_stock_only``
    (inventory > 0). Returns {id, name, inventory, type, supplier, ...}; amounts
    are in Brewfather's stored metric units.
    """
    _check_kind(kind)
    params = {"inventory_exists": "true"} if in_stock_only else {}
    needle = name.strip().lower()
    items = client.get_client().paginate(f"inventory/{kind}", params)
    return [compact_inventory(i) for i in items if _matches(i, needle)]


@mcp.tool()
def set_inventory(
    kind: str, item_id: str, amount: float | None = None, adjust: float | None = None
) -> dict:
    """Change the stock of one inventory item.

    Pass exactly one of ``amount`` (set absolute stock) or ``adjust`` (add, or
    subtract with a negative number — e.g. after brew day). ``kind`` is
    fermentables, hops, miscs, or yeasts. Returns {item_id, result}.
    """
    _check_kind(kind)
    if (amount is None) == (adjust is None):
        raise ValueError("pass exactly one of amount or adjust")
    body = {"inventory": amount} if amount is not None else {"inventory_adjust": adjust}
    result = client.get_client().patch(f"inventory/{kind}/{item_id}", body)
    return {"item_id": item_id, "result": result}


def main() -> None:
    """Console-script entry point: run the server over stdio."""
    mcp.run()


if __name__ == "__main__":
    main()

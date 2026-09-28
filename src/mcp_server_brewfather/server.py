"""MCP server exposing Brewfather batches, recipes, readings, and inventory.

Ten tools: find_batches, get_batch, get_readings, update_batch, find_recipes,
get_recipe, create_recipe, update_recipe, list_inventory, set_inventory. Writes are
limited to batch status/measurements, recipe creation and settings/ingredients,
and inventory stock.
Nothing here deletes or writes computed recipe stats.

Errors meant for the model are raised as ToolError: mcp 2 hides the message of any
other exception behind a generic "Error executing tool".
"""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

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

mcp = MCPServer("brewfather")

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

# Recipe settings create_recipe/update_recipe may write. Stats (og, fg, abv, ibu, color, …) are
# deliberately absent: the Brewfather app computes them from the ingredients, and
# the API stores whatever it is sent without checking.
RECIPE_FIELDS = ("name", "author", "notes", "batchSize", "boilSize", "boilTime", "efficiency")

# Recipe types seen on live recipes. The API accepts any string, even none.
RECIPE_TYPES = ("All Grain", "Extract")

# Ingredient fields create_recipe/update_recipe may set. The API silently accepts unknown keys,
# so this allowlist is the only guard.
INGREDIENT_FIELDS = (
    "name",
    "amount",
    "unit",
    "type",
    "use",
    "time",
    "alpha",
    "color",
    "potential",
    "attenuation",
    "form",
    "laboratory",
    "origin",
    "supplier",
)

_STALE_STATS = (
    "Brewfather computes og/fg/abv/ibu/color in the app when the recipe is opened; "
    "the stored stats get_recipe returns are not updated by API writes."
)


def _matches(obj: dict, needle: str) -> bool:
    return not needle or needle in (obj.get("name") or "").lower()


def _check_kind(kind: str) -> None:
    if kind not in INVENTORY_KINDS:
        raise ToolError(f"unknown inventory kind: {kind!r} (use {', '.join(INVENTORY_KINDS)})")


def _check_fields(obj: dict, allowed: tuple[str, ...], what: str) -> None:
    for key in obj:
        if key not in allowed:
            raise ToolError(f"unknown {what}: {key!r} (use {', '.join(allowed)})")


def _apply_ingredient_changes(recipe: dict, changes: list[dict]) -> dict[str, list[dict]]:
    """Return the full new ingredient list for each kind that ``changes`` touches.

    The API replaces an ingredient list wholesale, so edits are applied to the raw
    items (keeping fields get_recipe doesn't show) and the complete list is sent.
    Indexes refer to the recipe as read; removals are applied last.
    """
    lists: dict[str, list[dict]] = {}
    removed: dict[str, set[int]] = {}
    for change in changes:
        change = dict(change)
        kind = change.pop("kind", "")
        index = change.pop("index", None)
        remove = change.pop("remove", False)
        current_name = change.pop("current_name", None)
        _check_kind(kind)
        _check_fields(change, INGREDIENT_FIELDS, "ingredient field")
        original = recipe.get(kind) or []
        items = lists.setdefault(kind, [dict(i) for i in original])
        if index is None:
            if remove or "name" not in change or "amount" not in change:
                raise ToolError("a new ingredient needs name and amount (removing needs index)")
            items.append(change)
        elif not 0 <= index < len(original):
            raise ToolError(f"{kind} index {index} out of range (recipe has {len(original)})")
        elif current_name is not None and (
            current_name.strip().lower() != (original[index].get("name") or "").lower()
        ):
            raise ToolError(
                f"{kind} index {index} is {original[index].get('name')!r}, not {current_name!r};"
                " re-read the recipe with get_recipe"
            )
        elif remove:
            removed.setdefault(kind, set()).add(index)
        else:
            items[index].update(change)
    return {
        kind: [item for n, item in enumerate(items) if n not in removed.get(kind, set())]
        for kind, items in lists.items()
    }


@mcp.tool()
def find_batches(name: str = "", status: str = "") -> list[dict]:
    """Find batches by name (case-insensitive substring) and/or status.

    ``status`` is one of Planning, Brewing, Fermenting, Conditioning, Completed,
    Archived; empty means any. Returns compact dicts:
    {id, name, batch_no, status, brewer, brew_date, recipe}. Use the id with
    get_batch / get_readings / update_batch.
    """
    if status and status not in BATCH_STATUSES:
        raise ToolError(f"unknown status: {status!r} (use {', '.join(BATCH_STATUSES)})")
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
            raise ToolError(f"unknown status: {status!r} (use {', '.join(BATCH_STATUSES)})")
        body["status"] = status
    for key, value in (measurements or {}).items():
        if key not in BATCH_MEASUREMENTS:
            raise ToolError(f"unknown measurement: {key!r} (use {', '.join(BATCH_MEASUREMENTS)})")
        body[key] = value
    if not body:
        raise ToolError("nothing to update: pass status and/or measurements")
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
    Stats are as last saved in the Brewfather app, so they can be stale after
    update_recipe.
    """
    return compact_recipe(client.get_client().get(f"recipes/{recipe_id}"))


@mcp.tool()
def create_recipe(
    name: str,
    type: str = "All Grain",
    fields: dict[str, str | float] | None = None,
    ingredients: list[dict] | None = None,
) -> dict:
    """Create a new recipe.

    ``type`` is All Grain or Extract. ``fields`` takes the same settings as
    update_recipe (author, notes, batchSize, boilSize, boilTime, efficiency).
    ``ingredients`` is a list of new items in update_recipe's add form (``kind``,
    name, amount, … — no index). So Brewfather can compute stats, give
    fermentables color and potential (SG, e.g. 1.037), hops alpha, use and time,
    and yeasts attenuation.

    Returns {recipe_id, note}; stats stay empty until the recipe is opened in
    the Brewfather app.
    """
    if not name.strip():
        raise ToolError("a recipe needs a name")
    if type not in RECIPE_TYPES:
        raise ToolError(f"unknown recipe type: {type!r} (use {', '.join(RECIPE_TYPES)})")
    fields = fields or {}
    _check_fields(fields, RECIPE_FIELDS, "recipe field")
    body: dict = {**fields, "name": name.strip(), "type": type}
    body.update(_apply_ingredient_changes({}, ingredients or []))
    result = client.get_client().post("recipes", body)
    return {"recipe_id": result["id"], "note": _STALE_STATS}


@mcp.tool()
def update_recipe(
    recipe_id: str,
    fields: dict[str, str | float] | None = None,
    ingredients: list[dict] | None = None,
) -> dict:
    """Edit a recipe's settings and/or ingredient bill.

    ``fields`` keys (metric — liters, minutes, percent): name, author, notes,
    batchSize, boilSize, boilTime, efficiency. Stats (og, fg, abv, ibu, color)
    can't be set; Brewfather computes them from the ingredients.

    ``ingredients`` is a list of changes, each with ``kind`` (fermentables, hops,
    miscs, yeasts) and:
    - ``index`` + fields to change an item — index is its 0-based position in
      get_recipe's list, e.g. {"kind": "hops", "index": 1, "amount": 50};
    - ``index`` + ``"remove": true`` to delete it;
    - with ``index``, pass ``current_name`` (the item's name as get_recipe showed
      it) and the change is rejected if the item there has a different name;
    - no index to add one; needs name and amount, e.g. {"kind": "hops",
      "name": "Citra", "amount": 30, "alpha": 12, "use": "Boil", "time": 5}.
    Ingredient fields: name, amount (kg for fermentables, g for hops), unit,
    type, use, time, alpha, color, potential, attenuation, form, laboratory,
    origin, supplier.

    Returns {recipe_id, result, note}.
    """
    fields = fields or {}
    _check_fields(fields, RECIPE_FIELDS, "recipe field")
    if not fields and not ingredients:
        raise ToolError("nothing to update: pass fields and/or ingredients")
    body: dict = dict(fields)
    if ingredients:
        current = client.get_client().get(f"recipes/{recipe_id}")
        body.update(_apply_ingredient_changes(current, ingredients))
    result = client.get_client().patch(f"recipes/{recipe_id}", body)
    return {"recipe_id": recipe_id, "result": result, "note": _STALE_STATS}


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
        raise ToolError("pass exactly one of amount or adjust")
    body = {"inventory": amount} if amount is not None else {"inventory_adjust": adjust}
    result = client.get_client().patch(f"inventory/{kind}/{item_id}", body)
    return {"item_id": item_id, "result": result}


def main() -> None:
    """Console-script entry point: run the server over stdio."""
    mcp.run()


if __name__ == "__main__":
    main()

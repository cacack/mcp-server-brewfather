"""Compact projections of Brewfather objects.

Full batch and recipe objects embed equipment, water, mash and style profiles and
run to tens of kilobytes. Project them down to what's useful for brewing questions
so we don't blow up the model's context. Epoch-millisecond timestamps become ISO
strings. Missing fields are omitted rather than returned as null.

List-endpoint default fields are documented by Brewfather; the richer detail
fields below (og, measured*, ingredient amounts, …) follow the objects the
Brewfather app exports, and are checked by the acceptance suite.
"""

from __future__ import annotations

from datetime import UTC, datetime

INVENTORY_KINDS = ("fermentables", "hops", "miscs", "yeasts")

_RECIPE_STATS = ("batchSize", "boilTime", "efficiency", "og", "fg", "abv", "ibu", "color")
_INGREDIENT_FIELDS = (
    "name",
    "amount",
    "unit",
    "type",
    "use",
    "time",
    "alpha",
    "attenuation",
    "laboratory",
    "productId",
)
_INVENTORY_FIELDS = (
    "name",
    "inventory",
    "unit",
    "type",
    "supplier",
    "use",
    "alpha",
    "attenuation",
    "laboratory",
    "productId",
)
_READING_FIELDS = ("sg", "temp", "angle", "battery", "type", "id")


def pick(obj: dict, keys: tuple[str, ...]) -> dict:
    """Return the subset of ``obj`` at ``keys``, skipping missing/None values."""
    return {k: obj[k] for k in keys if obj.get(k) is not None}


def iso_date(ms: int | None) -> str | None:
    """Epoch milliseconds → ``YYYY-MM-DD`` (UTC)."""
    if ms is None:
        return None
    return datetime.fromtimestamp(ms / 1000, UTC).date().isoformat()


def iso_datetime(ms: int | None) -> str | None:
    """Epoch milliseconds → ISO-8601 timestamp (UTC, second precision)."""
    if ms is None:
        return None
    return datetime.fromtimestamp(ms / 1000, UTC).isoformat(timespec="seconds")


def compact_batch_summary(b: dict) -> dict:
    """``{id, name, batch_no, status, brewer, brew_date, recipe}`` — list-endpoint fields."""
    out = {
        "id": b.get("_id"),
        "name": b.get("name"),
        "batch_no": b.get("batchNo"),
        "status": b.get("status"),
        "brewer": b.get("brewer"),
        "brew_date": iso_date(b.get("brewDate")),
        "recipe": (b.get("recipe") or {}).get("name"),
    }
    return {k: v for k, v in out.items() if v is not None}


def compact_batch(b: dict) -> dict:
    """Batch summary plus every ``measured*`` value and the embedded recipe, compacted."""
    out = compact_batch_summary(b)
    if b.get("fermentationStartDate") is not None:
        out["fermentation_start"] = iso_date(b["fermentationStartDate"])
    measured = {k: v for k, v in b.items() if k.startswith("measured") and v is not None}
    if measured:
        out["measured"] = measured
    if b.get("recipe"):
        out["recipe"] = compact_recipe(b["recipe"])
    return out


def compact_recipe_summary(r: dict) -> dict:
    """``{id, name, author, type, style, equipment}`` — list-endpoint fields."""
    out = {
        "id": r.get("_id"),
        "name": r.get("name"),
        "author": r.get("author"),
        "type": r.get("type"),
        "style": (r.get("style") or {}).get("name"),
        "equipment": (r.get("equipment") or {}).get("name"),
    }
    return {k: v for k, v in out.items() if v is not None}


def compact_recipe(r: dict) -> dict:
    """Recipe summary plus target stats and a compact ingredient bill."""
    out = compact_recipe_summary(r)
    out.update(pick(r, _RECIPE_STATS))
    for kind in INVENTORY_KINDS:
        items = [pick(i, _INGREDIENT_FIELDS) for i in r.get(kind) or []]
        if items:
            out[kind] = items
    return out


def compact_inventory(item: dict) -> dict:
    """``{id, name, inventory, …}`` for any inventory kind."""
    return {"id": item.get("_id"), **pick(item, _INVENTORY_FIELDS)}


def compact_reading(r: dict) -> dict:
    """``{time, sg, temp, …}`` for a hydrometer/sensor reading."""
    return {"time": iso_datetime(r.get("time")), **pick(r, _READING_FIELDS)}

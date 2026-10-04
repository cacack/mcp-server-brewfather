"""Compact projections of Brewfather objects.

Full batch and recipe objects embed equipment, water, mash and style profiles and
run to tens of kilobytes. Project them down to what's useful for brewing questions
so we don't blow up the model's context. Epoch-millisecond timestamps become ISO
strings. Missing fields are omitted rather than returned as null.

List-endpoint default fields are documented by Brewfather; the richer detail
fields below (og, estimated*, measured*, ingredient amounts, …) were confirmed
against live API objects and are checked by the acceptance suite.
"""

from __future__ import annotations

import html
import re
import time
from datetime import UTC, datetime

INVENTORY_KINDS = ("fermentables", "hops", "miscs", "yeasts")

_RECIPE_STATS = ("batchSize", "boilTime", "efficiency", "og", "fg", "abv", "ibu", "color")
_BATCH_ESTIMATES = ("estimatedOg", "estimatedFg", "estimatedIbu", "estimatedColor")
_INGREDIENT_FIELDS = (
    "name",
    "amount",
    "percentage",
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
    "origin",
    "use",
    "alpha",
    "color",
    "potential",
    "attenuation",
    "laboratory",
    "productId",
    "form",
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


def _log_entry(n: dict) -> dict:
    """``{time, status, note, type}`` for one batch log entry.

    Entries the user typed have no ``type``; automatic ones carry one (only
    ``statusChanged`` seen so far). ``note`` is plain text on live batches.
    """
    out = {
        "time": iso_datetime(n.get("timestamp")),
        "status": n.get("status"),
        "note": n.get("note") or None,
        "type": n.get("type"),
    }
    return {k: v for k, v in out.items() if v is not None}


def _batch_event(e: dict) -> dict:
    """``{time, event, description, active}`` for one scheduled batch event.

    ``time`` is a date for all-day events, a timestamp otherwise. ``active`` is true
    while the event is still upcoming (live events: future ones true, past ones false).
    """
    to_iso = iso_date if e.get("dayEvent") else iso_datetime
    # Dry-hop events carry no eventText; name them from eventType instead.
    kind = (e.get("eventType") or "").removeprefix("event-batch-").replace("-", " ")
    out = {
        "time": to_iso(e.get("time")),
        # eventText holds HTML entities ("Brew Day &mdash; Reminder").
        "event": _html_text(e.get("eventText")) or kind or "event",
        # description is plain text (the markup lives in descriptionHTML), so it is
        # passed through: stripping tags would eat text like "SG < 1.015".
        "description": e.get("description") or None,
        "active": e.get("active"),
    }
    return {k: v for k, v in out.items() if v is not None}


def compact_batch(b: dict) -> dict:
    """Batch summary, dates, notes, log, scheduled events, estimated and measured
    values, and the embedded recipe.
    """
    out = compact_batch_summary(b)
    # The brewer's free-text notes (plain text). Not the API's own ``notes`` field,
    # which is the batch log and becomes ``log`` below.
    if b.get("batchNotes"):
        out["notes"] = b["batchNotes"]
    # The API stores the log out of order; entries hidden in the app stay hidden.
    log = sorted(
        (n for n in b.get("notes") or [] if not n.get("hidden")),
        key=lambda n: n.get("timestamp") or 0,
    )
    if log:
        out["log"] = [_log_entry(n) for n in log]
    events = sorted(b.get("events") or [], key=lambda e: e.get("time") or 0)
    if events:
        out["events"] = [_batch_event(e) for e in events]
    if b.get("fermentationStartDate") is not None:
        out["fermentation_start"] = iso_date(b["fermentationStartDate"])
    if b.get("bottlingDate") is not None:
        out["bottling_date"] = iso_date(b["bottlingDate"])
    estimated = pick(b, _BATCH_ESTIMATES)
    if estimated:
        out["estimated"] = estimated
    # Skip boolean flags such as measuredOgSet; keep only the measured values.
    measured = {
        k: v
        for k, v in b.items()
        if k.startswith("measured") and v is not None and not isinstance(v, bool)
    }
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


_BR = re.compile(r"<\s*/?\s*br\s*/?\s*>", re.IGNORECASE)
_TAG = re.compile(r"<[^>]+>")


def _html_text(s: str | None) -> str | None:
    """Brew tracker step descriptions are HTML fragments; flatten them to text."""
    if s is None:
        return None
    lines = html.unescape(_TAG.sub("", _BR.sub("\n", s))).splitlines()
    return "\n".join(" ".join(line.split()) for line in lines if line.strip()) or None


def _tracker_step(s: dict) -> dict:
    """``{name, description, at, value, waits_for_you}`` for one brew tracker step."""
    out = {
        "name": s.get("name"),
        "description": _html_text(s.get("description")),
        "at": s.get("time"),
        # Steps without a target (sparge, "Mashing Complete", …) carry value 0.
        "value": s.get("value") or None,
        "waits_for_you": True if s.get("pauseBefore") else None,
    }
    return {k: v for k, v in out.items() if v is not None}


def compact_brewtracker(t: dict, now_ms: int | None = None) -> dict:
    """Current stage and step, time left on the stage timer, and what comes next.

    The API's stage ``position`` (seconds left) is a snapshot taken when the timer was
    last resumed at ``start`` (two live captures 60 s apart returned the same
    position), so a running stage's remaining time is computed here. A tracker with
    no current stage gets a ``message`` instead of ``stage``.
    """
    out = {
        "active": t.get("active"),
        "completed": t.get("completed"),
        "started": iso_datetime(t.get("startTime")),
    }
    stages = t.get("stages") or []
    index = t.get("stage")
    if not (isinstance(index, int) and 0 <= index < len(stages)):
        out["message"] = (
            "The brew tracker is complete."
            if t.get("completed")
            else "The brew tracker has no current stage."
        )
    else:
        stage = stages[index]
        remaining = stage.get("position")
        running = t.get("active") and not stage.get("paused") and stage.get("start") is not None
        if remaining is not None and running:
            now_ms = int(time.time() * 1000) if now_ms is None else now_ms
            remaining = max(0, round(remaining - (now_ms - stage["start"]) / 1000))
        steps = stage.get("steps") or []
        step = stage.get("step")
        out.update(
            {
                "stage": stage.get("name") or f"Stage {index + 1}",
                "paused": stage.get("paused"),
                "stage_duration": stage.get("duration"),
                "stage_remaining": remaining,
            }
        )
        if isinstance(step, int) and 0 <= step < len(steps):
            out["current_step"] = _tracker_step(steps[step])
            upcoming = [_tracker_step(s) for s in steps[step + 1 :]]
            if upcoming:
                out["upcoming"] = upcoming
        if index + 1 < len(stages):
            out["next_stage"] = stages[index + 1].get("name")
    return {k: v for k, v in out.items() if v is not None}

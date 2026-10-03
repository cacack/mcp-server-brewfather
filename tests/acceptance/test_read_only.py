"""Acceptance tests against the live Brewfather API.

Gated: skipped unless run with ``--run-acceptance`` and BREWFATHER_* credentials
(see conftest.py). Read-only by design — they never write to your real brewing
data — and they confirm the detail-field projections match live objects.

Run with:
    uv run pytest --run-acceptance
"""

from __future__ import annotations

import re

import pytest

from mcp_server_brewfather import server
from mcp_server_brewfather.normalize import INVENTORY_KINDS

pytestmark = pytest.mark.acceptance


def test_recipes_roundtrip():
    recipes = server.find_recipes()
    if not recipes:
        pytest.skip("account has no recipes")
    for r in recipes:
        server._check_id(r["id"], "recipe_id")  # live ids pass the path allowlist
    recipe = server.get_recipe(recipes[0]["id"])
    assert recipe["name"] == recipes[0]["name"]
    # Detail fields beyond the documented list defaults — confirms the projection.
    assert "og" in recipe, f"no target stats in projected recipe: {sorted(recipe)}"
    assert "fermentables" in recipe


def test_batches_roundtrip():
    batches = server.find_batches()
    if not batches:
        pytest.skip("account has no batches")
    for b in batches:
        server._check_id(b["id"], "batch_id")  # live ids pass the path allowlist
    batch = server.get_batch(batches[0]["id"])
    assert batch["id"] == batches[0]["id"]
    assert "recipe" in batch
    assert "estimated" in batch, f"no estimated stats in projected batch: {sorted(batch)}"
    readings = server.get_readings(batch["id"], limit=5)
    assert readings["total"] >= len(readings["readings"])
    latest = server.get_readings(batch["id"], limit=1)
    assert latest["readings"] == readings["readings"][-1:]


_LEFTOVER_MARKUP = re.compile(r"<[^>]+>|&[#\w]+;")


def test_batch_notes_log_and_events_project():
    # A batch that has left Planning has logged at least one status change.
    batches = [b for b in server.find_batches() if b.get("status") != "Planning"]
    if not batches:
        pytest.skip("account has no batches past Planning")
    for summary in batches:
        batch = server.get_batch(summary["id"])
        assert batch.get("log"), f"{summary['id']}: no log in {sorted(batch)}"
        times = [e["time"] for e in batch["log"]]
        assert all(times) and times == sorted(times)
        assert all(e["status"] for e in batch["log"])
        texts = [batch.get("notes", "")] + [e.get("note", "") for e in batch["log"]]
        for event in batch.get("events", []):
            assert event["time"] and event["event"], event
            texts += [event["event"], event.get("description", "")]
        # Notes and descriptions are plain text; eventText entities get unescaped.
        leftovers = [t for t in texts if _LEFTOVER_MARKUP.search(t)]
        assert not leftovers, f"{summary['id']}: markup left in {leftovers}"


def test_brewtracker_projects_or_reports_none():
    batches = server.find_batches(status="Brewing") or server.find_batches()[:1]
    if not batches:
        pytest.skip("account has no batches")
    for batch in batches:
        tracker = server.get_brewtracker(batch["id"])
        if "message" in tracker:
            continue
        # A live tracker must project a current step and a sane stage timer.
        assert "current_step" in tracker, f"{batch['id']}: {sorted(tracker)}"
        assert 0 <= tracker["stage_remaining"] <= tracker["stage_duration"]


@pytest.mark.parametrize("kind", INVENTORY_KINDS)
def test_inventory_lists(kind):
    items = server.list_inventory(kind)
    assert all("id" in i and "name" in i for i in items)
    for i in items:
        server._check_id(i["id"], "item_id")  # live ids pass the path allowlist

"""Acceptance tests against the live Brewfather API.

Gated: skipped unless run with ``--run-acceptance`` and BREWFATHER_* credentials
(see conftest.py). Read-only by design — they never write to your real brewing
data — and they confirm the detail-field projections match live objects.

Run with:
    uv run pytest --run-acceptance
"""

from __future__ import annotations

import pytest

from mcp_server_brewfather import server
from mcp_server_brewfather.normalize import INVENTORY_KINDS

pytestmark = pytest.mark.acceptance


def test_recipes_roundtrip():
    recipes = server.find_recipes()
    if not recipes:
        pytest.skip("account has no recipes")
    recipe = server.get_recipe(recipes[0]["id"])
    assert recipe["name"] == recipes[0]["name"]
    # Detail fields beyond the documented list defaults — confirms the projection.
    assert "og" in recipe, f"no target stats in projected recipe: {sorted(recipe)}"
    assert "fermentables" in recipe


def test_batches_roundtrip():
    batches = server.find_batches()
    if not batches:
        pytest.skip("account has no batches")
    batch = server.get_batch(batches[0]["id"])
    assert batch["id"] == batches[0]["id"]
    assert "recipe" in batch
    assert "estimated" in batch, f"no estimated stats in projected batch: {sorted(batch)}"
    readings = server.get_readings(batch["id"], limit=5)
    assert readings["total"] >= len(readings["readings"])
    latest = server.get_readings(batch["id"], limit=1)
    assert latest["readings"] == readings["readings"][-1:]


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

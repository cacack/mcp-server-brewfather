"""Unit tests for the server tools, exercised against the mocked Brewfather API.

These assert the behavior that's easy to get wrong: filtering, projection of large
objects, reading order/limit, and input validation before any write is sent.
"""

from __future__ import annotations

import pytest

from mcp_server_brewfather import server

# 2026-09-01T12:00:00Z in epoch ms, as Brewfather stores timestamps.
_SEP1 = 1788264000000


def _batch(bid, name, status="Fermenting", **extra):
    return {
        "_id": bid,
        "name": name,
        "batchNo": 7,
        "status": status,
        "brewer": "Chris",
        "brewDate": _SEP1,
        "recipe": {"name": name},
        **extra,
    }


def test_find_batches_filters_by_name_and_passes_status(fake_api):
    api = fake_api({("GET", "batches"): [[_batch("b1", "Hazy IPA"), _batch("b2", "Dry Stout")]]})
    out = server.find_batches("hazy", status="Fermenting")
    assert out == [
        {
            "id": "b1",
            "name": "Hazy IPA",
            "batch_no": 7,
            "status": "Fermenting",
            "brewer": "Chris",
            "brew_date": "2026-09-01",
            "recipe": "Hazy IPA",
        }
    ]
    assert api.requests[0].url.params["status"] == "Fermenting"


def test_find_batches_rejects_unknown_status(fake_api):
    api = fake_api({})
    with pytest.raises(ValueError, match="unknown status"):
        server.find_batches(status="Drinking")
    assert api.requests == []


def test_get_batch_projects_measured_and_recipe(fake_api):
    recipe = {
        "name": "Hazy IPA",
        "style": {"name": "Hazy IPA", "ibuMin": 15},
        "og": 1.065,
        "hops": [{"name": "Citra", "amount": 100, "use": "Dry Hop", "time": 3, "_id": "h"}],
        "water": {"huge": "profile"},
    }
    fake_api(
        {
            ("GET", "batches/b1"): _batch(
                "b1",
                "Hazy IPA",
                measuredOg=1.066,
                measuredOgSet=True,
                measuredFg=None,
                estimatedOg=1.065,
                bottlingDate=_SEP1,
                recipe=recipe,
            )
        }
    )
    out = server.get_batch("b1")
    assert out["measured"] == {"measuredOg": 1.066}
    assert out["estimated"] == {"estimatedOg": 1.065}
    assert out["bottling_date"] == "2026-09-01"
    assert out["recipe"]["og"] == 1.065
    assert out["recipe"]["style"] == "Hazy IPA"
    assert out["recipe"]["hops"] == [{"name": "Citra", "amount": 100, "use": "Dry Hop", "time": 3}]
    assert "water" not in out["recipe"]


def test_get_readings_sorts_and_limits(fake_api):
    readings = [{"time": _SEP1 + i * 1000, "sg": 1060 - i, "temp": 19} for i in (2, 0, 1)]
    fake_api({("GET", "batches/b1/readings"): readings})
    out = server.get_readings("b1", limit=2)
    assert out["total"] == 3
    assert [r["sg"] for r in out["readings"]] == [1059, 1058]
    assert out["readings"][-1]["time"] == "2026-09-01T12:00:02+00:00"


def test_update_batch_sends_status_and_measurements(fake_api):
    api = fake_api({("PATCH", "batches/b1"): "Updated"})
    out = server.update_batch("b1", status="Conditioning", measurements={"measuredFg": 1.012})
    assert out == {"batch_id": "b1", "result": "Updated"}
    assert api.bodies() == [{"status": "Conditioning", "measuredFg": 1.012}]


@pytest.mark.parametrize(
    "kwargs, match",
    [
        ({}, "nothing to update"),
        ({"status": "Drinking"}, "unknown status"),
        ({"measurements": {"og": 1.05}}, "unknown measurement"),
    ],
)
def test_update_batch_validates_before_sending(fake_api, kwargs, match):
    api = fake_api({})
    with pytest.raises(ValueError, match=match):
        server.update_batch("b1", **kwargs)
    assert api.requests == []


def test_find_recipes_filters_by_name(fake_api):
    fake_api(
        {
            ("GET", "recipes"): [
                [
                    {"_id": "r1", "name": "Dry Stout", "style": {"name": "Irish Stout"}},
                    {"_id": "r2", "name": "Pils", "equipment": {"name": "Grainfather"}},
                ]
            ]
        }
    )
    assert server.find_recipes("STOUT") == [
        {"id": "r1", "name": "Dry Stout", "style": "Irish Stout"}
    ]


def test_list_inventory_in_stock_filter(fake_api):
    api = fake_api(
        {
            ("GET", "inventory/hops"): [
                [{"_id": "h1", "name": "Citra", "inventory": 250, "alpha": 12}]
            ]
        }
    )
    out = server.list_inventory("hops", in_stock_only=True)
    assert out == [{"id": "h1", "name": "Citra", "inventory": 250, "alpha": 12}]
    assert api.requests[0].url.params["inventory_exists"] == "true"


def test_list_inventory_rejects_unknown_kind(fake_api):
    with pytest.raises(ValueError, match="unknown inventory kind"):
        server.list_inventory("grains")


def test_set_inventory_adjust(fake_api):
    api = fake_api({("PATCH", "inventory/hops/h1"): "Updated"})
    server.set_inventory("hops", "h1", adjust=-100)
    assert api.bodies() == [{"inventory_adjust": -100}]


def test_set_inventory_absolute(fake_api):
    api = fake_api({("PATCH", "inventory/yeasts/y1"): "Updated"})
    server.set_inventory("yeasts", "y1", amount=2)
    assert api.bodies() == [{"inventory": 2}]


@pytest.mark.parametrize("kwargs", [{}, {"amount": 1, "adjust": 1}])
def test_set_inventory_requires_exactly_one(fake_api, kwargs):
    api = fake_api({})
    with pytest.raises(ValueError, match="exactly one"):
        server.set_inventory("hops", "h1", **kwargs)
    assert api.requests == []


def _recipe():
    return {
        "_id": "r1",
        "name": "Pale",
        "og": 1.050,
        "hops": [
            {"name": "Magnum", "amount": 20, "time": 60, "_rev": "x"},
            {"name": "Cascade", "amount": 30, "time": 10, "_rev": "y"},
        ],
        "fermentables": [{"name": "Pale Malt", "amount": 4.0, "potential": 1.037}],
    }


def test_update_recipe_fields_only_skips_read(fake_api):
    api = fake_api({("PATCH", "recipes/r1"): "Updated"})
    out = server.update_recipe("r1", fields={"batchSize": 23, "name": "Pale v2"})
    assert out["result"] == "Updated"
    assert "recalculates" in out["note"]
    assert api.bodies() == [{"batchSize": 23, "name": "Pale v2"}]
    assert [r.method for r in api.requests] == ["PATCH"]


def test_update_recipe_sends_full_ingredient_lists(fake_api):
    api = fake_api({("GET", "recipes/r1"): _recipe(), ("PATCH", "recipes/r1"): "Updated"})
    server.update_recipe(
        "r1",
        ingredients=[
            {"kind": "hops", "index": 1, "current_name": "cascade", "amount": 50},
            {"kind": "hops", "index": 0, "remove": True},
            {"kind": "hops", "name": "Citra", "amount": 25, "time": 5},
        ],
    )
    # Untouched kinds are left out; touched lists keep fields get_recipe hides.
    assert api.bodies() == [
        {
            "hops": [
                {"name": "Cascade", "amount": 50, "time": 10, "_rev": "y"},
                {"name": "Citra", "amount": 25, "time": 5},
            ]
        }
    ]


@pytest.mark.parametrize(
    "kwargs, match",
    [
        ({}, "nothing to update"),
        ({"fields": {"og": 1.08}}, "unknown recipe field"),
        ({"ingredients": [{"kind": "grains", "index": 0}]}, "unknown inventory kind"),
        ({"ingredients": [{"kind": "hops", "index": 0, "ibu": 5}]}, "unknown ingredient field"),
        ({"ingredients": [{"kind": "hops", "index": 2, "amount": 1}]}, "out of range"),
        ({"ingredients": [{"kind": "hops", "name": "Citra"}]}, "needs name and amount"),
        ({"ingredients": [{"kind": "hops", "remove": True}]}, "removing needs index"),
        (
            {"ingredients": [{"kind": "hops", "index": 0, "current_name": "Cascade", "time": 5}]},
            "is 'Magnum', not 'Cascade'",
        ),
    ],
)
def test_update_recipe_validates_before_writing(fake_api, kwargs, match):
    api = fake_api({("GET", "recipes/r1"): _recipe()})
    with pytest.raises(ValueError, match=match):
        server.update_recipe("r1", **kwargs)
    assert api.bodies() == []

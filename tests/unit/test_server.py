"""Unit tests for the server tools, exercised against the mocked Brewfather API.

These assert the behavior that's easy to get wrong: filtering, projection of large
objects, reading order/limit, and input validation before any write is sent.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import anyio
import httpx
import pytest
from mcp.server.mcpserver.exceptions import ToolError

from mcp_server_brewfather import server
from mcp_server_brewfather.normalize import INVENTORY_KINDS, compact_brewtracker

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
    with pytest.raises(ToolError, match="unknown status"):
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


def test_get_batch_projects_notes_log_and_events(fake_api):
    # Shapes from live batches: log stored out of order, typed notes lack ``type``,
    # hidden status changes, and date-only (dayEvent) vs timed events.
    notes = [
        {"note": "", "type": "statusChanged", "status": "Conditioning", "timestamp": _SEP1 + 3000},
        {"note": "Added 4oz Simcoe", "status": "Fermenting", "timestamp": _SEP1 + 2000},
        {
            "note": "",
            "hidden": True,
            "type": "statusChanged",
            "status": "Fermenting",
            "timestamp": _SEP1 + 1500,
        },
        {
            "note": "Pitched warm",
            "type": "statusChanged",
            "status": "Fermenting",
            "timestamp": _SEP1 + 1000,
        },
    ]
    events = [
        {
            "eventType": "event-batch-dry-hop",
            "time": _SEP1 + 86_400_000,
            "dayEvent": False,
            "active": True,
            "description": "Dry hop 100 g Citra when SG < 1.015",
            "descriptionHTML": "<b>Dry hop</b>",
            "title": "Dry Hop - Batch #7",
            "notifyTime": 0,
        },
        {
            "eventText": "Brew Day &mdash; Reminder",
            "eventType": "event-batch-brew-day-reminder",
            "time": _SEP1,
            "dayEvent": True,
            "active": False,
            "description": "Brew Day (Hazy IPA)",
        },
    ]
    fake_api(
        {
            ("GET", "batches/b1"): _batch(
                "b1", "Hazy IPA", batchNotes="Pump failure", notes=notes, events=events
            )
        }
    )
    out = server.get_batch("b1")
    assert out["notes"] == "Pump failure"
    assert out["log"] == [
        {
            "time": "2026-09-01T12:00:01+00:00",
            "status": "Fermenting",
            "note": "Pitched warm",
            "type": "statusChanged",
        },
        {"time": "2026-09-01T12:00:02+00:00", "status": "Fermenting", "note": "Added 4oz Simcoe"},
        {"time": "2026-09-01T12:00:03+00:00", "status": "Conditioning", "type": "statusChanged"},
    ]
    assert out["events"] == [
        {
            "time": "2026-09-01",
            "event": "Brew Day — Reminder",
            "description": "Brew Day (Hazy IPA)",
            "active": False,
        },
        {
            "time": "2026-09-02T12:00:00+00:00",
            # No eventText on live dry-hop events: named from eventType.
            "event": "dry hop",
            # Plain-text description kept as-is, "<" included.
            "description": "Dry hop 100 g Citra when SG < 1.015",
            "active": True,
        },
    ]


def test_get_batch_names_an_event_without_text_or_type(fake_api):
    fake_api({("GET", "batches/b1"): _batch("b1", "Hazy IPA", events=[{"time": _SEP1}])})
    assert server.get_batch("b1")["events"] == [
        {"time": "2026-09-01T12:00:00+00:00", "event": "event"}
    ]


def test_get_batch_omits_empty_notes_log_and_events(fake_api):
    hidden_only = [{"note": "", "hidden": True, "type": "statusChanged", "timestamp": _SEP1}]
    fake_api(
        {
            ("GET", "batches/b1"): _batch(
                "b1", "Hazy IPA", batchNotes=None, notes=hidden_only, events=[]
            )
        }
    )
    out = server.get_batch("b1")
    assert not {"notes", "log", "events"} & out.keys()


def test_get_readings_sorts_and_limits(fake_api):
    readings = [{"time": _SEP1 + i * 1000, "sg": 1060 - i, "temp": 19} for i in (2, 0, 1)]
    fake_api({("GET", "batches/b1/readings"): readings})
    out = server.get_readings("b1", limit=2)
    assert out["total"] == 3
    assert [r["sg"] for r in out["readings"]] == [1059, 1058]
    assert out["readings"][-1]["time"] == "2026-09-01T12:00:02+00:00"


def test_get_readings_limit_one_is_newest_of_list(fake_api):
    # readings/last ignores readings trimmed from the batch, so it isn't used (#22).
    readings = [{"time": _SEP1 + i * 1000, "sg": 1012 - i, "temp": 18} for i in (1, 0)]
    api = fake_api({("GET", "batches/b1/readings"): readings})
    out = server.get_readings("b1", limit=1)
    assert [r.url.path for r in api.requests] == ["/v2/batches/b1/readings"]
    assert out == {
        "total": 2,
        "readings": [{"time": "2026-09-01T12:00:01+00:00", "sg": 1011, "temp": 18}],
    }


def test_get_readings_unknown_batch_errors(fake_api):
    fake_api({})
    with pytest.raises(ToolError, match="HTTP 404"):
        server.get_readings("nope")


# Live GET /batches/:id/brewtracker captured 2026-09-29, running on the mash
# temperature step; ids scrubbed.
_BREWTRACKER = json.loads(
    (Path(__file__).parent / "fixtures" / "brewtracker_running.json").read_text()
)
_MASH_START = _BREWTRACKER["stages"][0]["start"]


def test_compact_brewtracker_running_stage():
    out = compact_brewtracker(_BREWTRACKER, now_ms=_MASH_START + 83_000)
    assert out["active"] is True
    assert out["completed"] is False
    assert out["started"] == "2026-09-29T17:08:38+00:00"
    assert out["stage"] == "Mash"
    assert out["paused"] is False
    assert out["stage_duration"] == 3600
    # position (3599) is a snapshot at ``start``; remaining counts down from it.
    assert out["stage_remaining"] == 3516
    assert out["current_step"] == {
        "name": "Temperature",
        "description": "Temperature - 60 min @ 158 °F",
        "at": 3600,
        "value": 70,
    }
    assert [s.get("name") for s in out["upcoming"]] == ["Sparge", "Mash", "Sparge", "Sparge"]
    assert out["upcoming"][1] == {
        "name": "Mash",
        "description": "Mashing Complete",
        "at": 0,
        "waits_for_you": True,
    }
    assert out["next_stage"] == "Boil"


def test_compact_brewtracker_strips_html_on_last_stage():
    tracker = copy.deepcopy(_BREWTRACKER)
    tracker["stage"] = 1
    out = compact_brewtracker(tracker)
    assert out["stage"] == "Boil"
    assert out["current_step"] == {"name": "Start", "description": "Start Boil Tracker", "at": 3600}
    assert out["upcoming"][1]["description"] == (
        "15 min boil additions:\n12 oz Milk Sugar (Lactose)\n0.6 oz Crystal\n0.5 oz Willamette"
    )
    assert "next_stage" not in out


# Mash keeps its ``start`` in both tests below; only the flag stops the countdown.
def test_compact_brewtracker_paused_stage_keeps_position():
    tracker = copy.deepcopy(_BREWTRACKER)
    tracker["stages"][0]["paused"] = True
    out = compact_brewtracker(tracker, now_ms=_MASH_START + 83_000)
    assert out["paused"] is True
    assert out["stage_remaining"] == 3599


def test_compact_brewtracker_inactive_tracker_keeps_position():
    tracker = {**_BREWTRACKER, "active": False}
    assert compact_brewtracker(tracker, now_ms=_MASH_START + 83_000)["stage_remaining"] == 3599


def test_compact_brewtracker_remaining_never_negative():
    out = compact_brewtracker(_BREWTRACKER, now_ms=_MASH_START + 10**9)
    assert out["stage_remaining"] == 0


def test_compact_brewtracker_last_step_has_no_upcoming():
    tracker = copy.deepcopy(_BREWTRACKER)
    tracker["stages"][0]["step"] = len(tracker["stages"][0]["steps"]) - 1
    out = compact_brewtracker(tracker)
    assert out["current_step"]["description"] == "Sparge Complete"
    assert "upcoming" not in out


@pytest.mark.parametrize(
    ("stage", "completed", "message"),
    [
        (2, True, "The brew tracker is complete."),
        (-1, False, "The brew tracker has no current stage."),
        (None, False, "The brew tracker has no current stage."),
    ],
)
def test_compact_brewtracker_without_current_stage_says_so(stage, completed, message):
    tracker = {**_BREWTRACKER, "stage": stage, "completed": completed}
    out = compact_brewtracker(tracker)
    assert out["message"] == message
    assert "stage" not in out


def test_compact_brewtracker_unnamed_stage_gets_a_label():
    tracker = copy.deepcopy(_BREWTRACKER)
    del tracker["stages"][0]["name"]
    assert compact_brewtracker(tracker)["stage"] == "Stage 1"


def test_get_brewtracker_projects_tracker(fake_api):
    api = fake_api({("GET", "batches/b1/brewtracker"): _BREWTRACKER})
    out = server.get_brewtracker("b1")
    assert out["stage"] == "Mash"
    assert out["current_step"]["name"] == "Temperature"
    assert [r.url.path for r in api.requests] == ["/v2/batches/b1/brewtracker"]


@pytest.mark.parametrize("body", [{}, "", None])
def test_get_brewtracker_empty_body_says_no_tracker(fake_api, body):
    fake_api({("GET", "batches/b1/brewtracker"): httpx.Response(200, json=body)})
    assert server.get_brewtracker("b1") == {
        "active": False,
        "message": server.NO_BREWTRACKER,
    }


def test_get_brewtracker_404_on_existing_batch_says_no_tracker(fake_api):
    api = fake_api({("GET", "batches/b1"): _batch("b1", "Hazy IPA", status="Brewing")})
    assert server.get_brewtracker("b1") == {"active": False, "message": server.NO_BREWTRACKER}
    assert [r.url.path for r in api.requests] == [
        "/v2/batches/b1/brewtracker",
        "/v2/batches/b1",
    ]


def test_get_brewtracker_unknown_batch_errors(fake_api):
    fake_api({})
    with pytest.raises(ToolError, match="HTTP 404"):
        server.get_brewtracker("nope")


def test_get_brewtracker_batch_check_errors_propagate(fake_api):
    fake_api({("GET", "batches/b1"): httpx.Response(500, text="boom")})
    with pytest.raises(ToolError, match="HTTP 500"):
        server.get_brewtracker("b1")


def test_get_brewtracker_other_errors_propagate(fake_api):
    api = fake_api({("GET", "batches/b1/brewtracker"): httpx.Response(500, text="boom")})
    with pytest.raises(ToolError, match="HTTP 500"):
        server.get_brewtracker("b1")
    assert len(api.requests) == 1


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
    with pytest.raises(ToolError, match=match):
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


def test_list_inventory_requests_complete_items(fake_api):
    # Without complete=true the list omits fields update_inventory_item edits (origin, …).
    api = fake_api({("GET", "inventory/hops"): [[]]})
    server.list_inventory("hops")
    params = api.requests[0].url.params
    assert params["complete"] == "true"
    assert "inventory_exists" not in params


def test_list_inventory_rejects_unknown_kind(fake_api):
    with pytest.raises(ToolError, match="unknown inventory kind"):
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
    with pytest.raises(ToolError, match="exactly one"):
        server.set_inventory("hops", "h1", **kwargs)
    assert api.requests == []


def test_inventory_fields_cover_every_kind():
    assert tuple(server.INVENTORY_FIELDS) == INVENTORY_KINDS


_ITEM_FIELDS = {
    "fermentables": {"color": 6, "potential": 1.037},
    "hops": {"alpha": 12.5},
    "miscs": {"unit": "g", "use": "Boil"},
    "yeasts": {"attenuation": 81, "laboratory": "Fermentis", "productId": "US-05", "form": "Dry"},
}


@pytest.mark.parametrize("kind", list(_ITEM_FIELDS))
def test_create_inventory_item_posts_each_kind(fake_api, kind):
    api = fake_api({("POST", f"inventory/{kind}"): {"id": "new1"}})
    fields = {"supplier": "Acme", **_ITEM_FIELDS[kind]}
    out = server.create_inventory_item(kind, " New item ", fields=fields)
    assert out == {"item_id": "new1"}
    assert [r.url.path for r in api.requests] == [f"/v2/inventory/{kind}"]
    assert api.bodies("POST") == [{**fields, "name": "New item"}]


def test_create_inventory_item_sets_starting_stock(fake_api):
    api = fake_api({("POST", "inventory/hops"): {"id": "new1"}})
    server.create_inventory_item("hops", "Citra", fields={"alpha": 12}, amount=100)
    assert api.bodies("POST") == [{"alpha": 12, "name": "Citra", "inventory": 100}]


@pytest.mark.parametrize("kind", list(_ITEM_FIELDS))
def test_update_inventory_item_patches_only_given_fields(fake_api, kind):
    api = fake_api({("PATCH", f"inventory/{kind}/i1"): "Updated"})
    fields = {"name": "Renamed", "supplier": "Acme", **_ITEM_FIELDS[kind]}
    out = server.update_inventory_item(kind, "i1", fields=fields)
    assert out == {"item_id": "i1", "result": "Updated"}
    assert api.bodies() == [fields]


@pytest.mark.parametrize(
    "call, match",
    [
        (lambda: server.create_inventory_item("hops", "  "), "needs a name"),
        (lambda: server.create_inventory_item("grains", "Pale"), "unknown inventory kind"),
        (
            lambda: server.create_inventory_item("hops", "Citra", fields={"ibu": 40}),
            "unknown hops field",
        ),
        (
            lambda: server.create_inventory_item("yeasts", "US-05", fields={"alpha": 5}),
            "unknown yeasts field",
        ),
        (
            lambda: server.create_inventory_item("hops", "Citra", fields={"inventory": 5}),
            "unknown hops field",
        ),
        (lambda: server.update_inventory_item("grains", "i1", {"name": "x"}), "unknown inventory"),
        (lambda: server.update_inventory_item("hops", "i1", {}), "nothing to update"),
        (lambda: server.update_inventory_item("hops", "i1", {"ibu": 5}), "unknown hops field"),
        (
            lambda: server.update_inventory_item("yeasts", "i1", {"alpha": 5}),
            "unknown yeasts field",
        ),
        (lambda: server.update_inventory_item("hops", "i1", {"inventory": 5}), "set_inventory"),
        (
            lambda: server.update_inventory_item("hops", "i1", {"inventory_adjust": -5}),
            "set_inventory",
        ),
        (
            lambda: server.create_inventory_item("hops", "Citra", fields={"name": "Mosaic"}),
            "not in fields",
        ),
        (lambda: server.update_inventory_item("hops", "i1", {"name": "  "}), "needs a name"),
    ],
)
def test_inventory_item_tools_validate_before_sending(fake_api, call, match):
    api = fake_api({})
    with pytest.raises(ToolError, match=match):
        call()
    assert api.requests == []


_ID_CALLS = {
    "get_batch": lambda i: server.get_batch(i),
    "get_readings": lambda i: server.get_readings(i),
    "get_brewtracker": lambda i: server.get_brewtracker(i),
    "update_batch": lambda i: server.update_batch(i, status="Completed"),
    "get_recipe": lambda i: server.get_recipe(i),
    "update_recipe": lambda i: server.update_recipe(i, fields={"name": "x"}),
    "set_inventory": lambda i: server.set_inventory("hops", i, adjust=1),
    "update_inventory_item": lambda i: server.update_inventory_item("hops", i, fields={"alpha": 5}),
}


@pytest.mark.parametrize("bad_id", ["../../x", "a/b", "a\\b", "a?b", "a#b", "..", "%2F", ""])
@pytest.mark.parametrize("tool", _ID_CALLS)
def test_ids_are_checked_before_any_request(fake_api, tool, bad_id):
    api = fake_api({})
    with pytest.raises(ToolError, match="invalid"):
        _ID_CALLS[tool](bad_id)
    assert api.requests == []


def test_set_inventory_accepts_dashed_default_id(fake_api):
    # Stock items copied from Brewfather's defaults keep ids like this one.
    api = fake_api({("PATCH", "inventory/hops/default-0c4aeb7c"): "Updated"})
    server.set_inventory("hops", "default-0c4aeb7c", adjust=1)
    assert api.bodies() == [{"inventory_adjust": 1}]


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
    assert "not updated by API writes" in out["note"]
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
    with pytest.raises(ToolError, match=match):
        server.update_recipe("r1", **kwargs)
    assert api.bodies() == []


def test_error_message_reaches_the_client(fake_api):
    # mcp 2 replaces the message of anything but a ToolError with a generic one.
    from mcp.client import Client

    fake_api({("GET", "recipes/r1"): httpx.Response(403, text="Forbidden")})

    async def call():
        async with Client(server.mcp) as c:
            return [
                await c.call_tool("find_batches", {"status": "Drinking"}),
                await c.call_tool("get_recipe", {"recipe_id": "r1"}),
            ]

    bad_input, api_error = anyio.run(call)
    assert bad_input.is_error and "unknown status: 'Drinking'" in bad_input.content[0].text
    assert api_error.is_error and "HTTP 403" in api_error.content[0].text


def test_server_reports_package_version():
    from mcp.client import Client

    from mcp_server_brewfather import __version__

    async def info():
        async with Client(server.mcp) as c:
            return c.server_info

    assert anyio.run(info).version == __version__


def test_create_recipe_posts_settings_and_ingredients(fake_api):
    api = fake_api({("POST", "recipes"): {"id": "r9"}})
    out = server.create_recipe(
        " Pale ",
        type="Extract",
        fields={"batchSize": 20},
        ingredients=[
            {"kind": "hops", "name": "Citra", "amount": 30, "alpha": 12},
            {"kind": "yeasts", "name": "US-05", "amount": 1},
        ],
    )
    assert out["recipe_id"] == "r9"
    assert api.bodies("POST") == [
        {
            "batchSize": 20,
            "name": "Pale",
            "type": "Extract",
            "hops": [{"name": "Citra", "amount": 30, "alpha": 12}],
            "yeasts": [{"name": "US-05", "amount": 1}],
        }
    ]


@pytest.mark.parametrize(
    "kwargs, match",
    [
        ({"name": "  "}, "needs a name"),
        ({"name": "Pale", "type": "BIAB"}, "unknown recipe type"),
        ({"name": "Pale", "fields": {"ibu": 40}}, "unknown recipe field"),
        (
            {"name": "Pale", "ingredients": [{"kind": "hops", "index": 0, "amount": 5}]},
            "out of range",
        ),
        (
            {"name": "Pale", "ingredients": [{"kind": "hops", "name": "Citra"}]},
            "needs name and amount",
        ),
    ],
)
def test_create_recipe_validates_before_posting(fake_api, kwargs, match):
    api = fake_api({})
    with pytest.raises(ToolError, match=match):
        server.create_recipe(**kwargs)
    assert api.requests == []

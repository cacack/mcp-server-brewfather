"""Manual live check of the write tools against the real Brewfather API.

Creates ONE scratch recipe, then exercises update_recipe on it (change, add,
remove, settings, stale-index guard) and prints PASS/FAIL per check.

With --inventory it then also creates ONE scratch hop and exercises
update_inventory_item (does a details PATCH merge or replace the item?) and
set_inventory on it. This needs inventory.read and inventory.write too.

Every write targets an object this script created; it never touches an existing
recipe, batch or inventory item. The server has no delete, so remove the scratch
objects in the Brewfather app afterwards (names and ids are printed at the end).

Needs BREWFATHER_USER_ID / BREWFATHER_API_KEY with recipes.read and
recipes.write. Opt-in and manual — never run in CI:

    source .env && uv run python scripts/live_check_writes.py [--inventory]
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime

from mcp.server.mcpserver.exceptions import ToolError

from mcp_server_brewfather import server

NAME = f"MCP live-check {datetime.now(UTC):%Y-%m-%d %H:%M:%S} (delete me)"
FIELDS = {"author": "live-check", "batchSize": 20, "boilTime": 60, "efficiency": 72}
INGREDIENTS = [
    {"kind": "fermentables", "name": "Pale Ale Malt", "amount": 4.5, "color": 3,
     "potential": 1.037, "type": "Grain"},
    {"kind": "hops", "name": "Magnum", "amount": 20, "alpha": 13, "use": "Boil", "time": 60},
    {"kind": "hops", "name": "Cascade", "amount": 30, "alpha": 6, "use": "Boil", "time": 10},
    {"kind": "yeasts", "name": "US-05", "amount": 1, "attenuation": 78},
]  # fmt: skip

HOP_FIELDS = {"alpha": 10, "supplier": "live-check", "origin": "US"}

failures = 0
scratch: list[str] = []  # one line per scratch object created, for the final notice


def check(name: str, ok: bool, detail: str = "") -> None:
    global failures
    failures += not ok
    print(f"{'PASS' if ok else 'FAIL'} {name}" + (f": {detail}" if detail and not ok else ""))


def names(recipe: dict, kind: str) -> list[str]:
    return [i.get("name") for i in recipe.get(kind, [])]


def recipe_checks() -> None:
    recipe_id = server.create_recipe(NAME, fields=FIELDS, ingredients=INGREDIENTS)["recipe_id"]
    scratch.append(f"Scratch recipe: {NAME!r} (id {recipe_id})")
    try:
        server._check_id(recipe_id, "recipe_id")
        check("create: returned id passes the path allowlist", True)
    except ToolError as e:
        check("create: returned id passes the path allowlist", False, str(e))

    r = server.get_recipe(recipe_id)
    check("create: name", r.get("name") == NAME, repr(r.get("name")))
    got = {k: r.get(k) for k in FIELDS}
    check("create: fields", got == FIELDS, repr(got))
    for kind in ("fermentables", "hops", "yeasts"):
        want = [i["name"] for i in INGREDIENTS if i["kind"] == kind]
        check(f"create: {kind}", names(r, kind) == want, repr(names(r, kind)))
    before = r

    # change: hops[0] amount only; everything else must survive the wholesale PATCH.
    server.update_recipe(
        recipe_id,
        ingredients=[{"kind": "hops", "index": 0, "current_name": "Magnum", "amount": 25}],
    )
    r = server.get_recipe(recipe_id)
    check("change: hop amount", r["hops"][0].get("amount") == 25, repr(r["hops"][0]))
    check("change: other hop kept", r["hops"][1] == before["hops"][1], repr(r["hops"][1]))
    check(
        "change: fermentables kept",
        r.get("fermentables") == before.get("fermentables"),
        repr(r.get("fermentables")),
    )

    # add
    server.update_recipe(
        recipe_id,
        ingredients=[{"kind": "hops", "name": "Citra", "amount": 40, "alpha": 12,
                      "use": "Boil", "time": 0}],
    )  # fmt: skip
    r = server.get_recipe(recipe_id)
    want = ["Magnum", "Cascade", "Citra"]
    check("add: hop appended", names(r, "hops") == want, repr(names(r, "hops")))

    # remove the hop just added
    server.update_recipe(
        recipe_id,
        ingredients=[{"kind": "hops", "index": 2, "current_name": "Citra", "remove": True}],
    )
    r = server.get_recipe(recipe_id)
    want = ["Magnum", "Cascade"]
    check("remove: hop removed", names(r, "hops") == want, repr(names(r, "hops")))

    # settings
    server.update_recipe(recipe_id, fields={"boilTime": 75, "efficiency": 68})
    after = server.get_recipe(recipe_id)
    got = (after.get("boilTime"), after.get("efficiency"))
    check("settings: boilTime and efficiency", got == (75, 68), repr(got))
    check(
        "settings: ingredients kept",
        all(after.get(k) == r.get(k) for k in ("fermentables", "hops", "yeasts")),
    )

    # guard: a stale index is refused with a readable error and nothing is written.
    try:
        server.update_recipe(
            recipe_id,
            ingredients=[{"kind": "hops", "index": 0, "current_name": "Citra", "amount": 1}],
        )
        check("guard: stale current_name refused", False, "no error raised")
    except ToolError as e:
        check("guard: stale current_name refused", "re-read the recipe" in str(e), str(e))
    check("guard: recipe unchanged", server.get_recipe(recipe_id) == after)


def find_hop(item_id: str) -> dict | None:
    """The scratch hop, looked up by its exact scratch name and id."""
    return next((i for i in server.list_inventory("hops", name=NAME) if i["id"] == item_id), None)


def hop_details(hop: dict | None) -> dict:
    return {k: (hop or {}).get(k) for k in HOP_FIELDS}


def inventory_checks() -> None:
    item_id = server.create_inventory_item("hops", NAME, fields=HOP_FIELDS, amount=0)["item_id"]
    scratch.append(f"Scratch hop: {NAME!r} (id {item_id})")
    try:
        server._check_id(item_id, "item_id")
        check("inventory create: returned id passes the path allowlist", True)
    except ToolError as e:
        check("inventory create: returned id passes the path allowlist", False, str(e))

    found = server.list_inventory("hops", name=NAME)
    check("inventory create: exactly one hop listed", len(found) == 1, repr(found))
    hop = find_hop(item_id)
    check("inventory create: details", hop_details(hop) == HOP_FIELDS, repr(hop))

    # merge vs replace: PATCH only alpha; supplier and origin must survive.
    server.update_inventory_item("hops", item_id, fields={"alpha": 11})
    hop = find_hop(item_id)
    check("inventory update: alpha changed", (hop or {}).get("alpha") == 11, repr(hop))
    want = {**HOP_FIELDS, "alpha": 11}
    merged = hop_details(hop) == want
    check("inventory: details PATCH merges (supplier/origin kept)", merged, repr(hop))

    server.set_inventory("hops", item_id, adjust=1)
    hop = find_hop(item_id)
    check("inventory stock: adjust +1 gives 1", (hop or {}).get("inventory") == 1, repr(hop))
    check("inventory stock: details unchanged", hop_details(hop) == want, repr(hop))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--inventory",
        action="store_true",
        help="also create one scratch hop and check the inventory write tools "
        "(needs inventory.write)",
    )
    args = parser.parse_args()
    try:
        recipe_checks()
        if args.inventory:
            inventory_checks()
    except Exception as e:  # report and fall through to the scratch-object notice
        check("run completed", False, f"{type(e).__name__}: {e}")
    finally:
        print()
        for line in scratch:
            print(f"{line}. Delete it in the Brewfather app.")
        if not scratch:
            print("No scratch objects were created.")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

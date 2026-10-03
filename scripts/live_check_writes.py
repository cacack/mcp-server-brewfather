"""Manual live check of the recipe write tools against the real Brewfather API.

Creates ONE scratch recipe, then exercises update_recipe on it (change, add,
remove, settings, stale-index guard) and prints PASS/FAIL per check. Every write
targets the recipe this script created; it never touches an existing recipe,
batch or inventory item. The server has no delete, so remove the scratch recipe
in the Brewfather app afterwards (its name and id are printed at the end).

Needs BREWFATHER_USER_ID / BREWFATHER_API_KEY with recipes.read and
recipes.write. Opt-in and manual — never run in CI:

    source .env && uv run python scripts/live_check_writes.py
"""

from __future__ import annotations

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

failures = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global failures
    failures += not ok
    print(f"{'PASS' if ok else 'FAIL'} {name}" + (f": {detail}" if detail and not ok else ""))


def names(recipe: dict, kind: str) -> list[str]:
    return [i.get("name") for i in recipe.get(kind, [])]


def main() -> int:
    recipe_id = None
    try:
        recipe_id = server.create_recipe(NAME, fields=FIELDS, ingredients=INGREDIENTS)["recipe_id"]
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
    except Exception as e:  # report and fall through to the scratch-recipe notice
        check("run completed", False, f"{type(e).__name__}: {e}")
    finally:
        if recipe_id:
            print(f"\nScratch recipe: {NAME!r} (id {recipe_id}). Delete it in the Brewfather app.")
        else:
            print("\nNo scratch recipe was created.")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

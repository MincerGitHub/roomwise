"""Small functional furniture groups for ordinary whole-room proposals.

These are explainable candidate templates, not a style model or an ergonomic
standard. Explicit user requests use the separate local constraint search.
"""
from __future__ import annotations

from copy import deepcopy
import math

from .geometry import assert_invariants, footprint, placement_errors, validate_scene
from .window_constraints import evaluate_layout_requirements, evaluate_wall_preference
from .bedside_constraints import bedside_assignments, bedside_placements, bed_placements_for_locked_stands, evaluate_bedside_groups


BEDS = {"double_bed", "single_bed", "kids_bed"}
TABLES = {"desk", "table", "dressing_table"}
SEATS = {"chair", "dressing_chair", "stool"}
WALL_BACKS = {"wardrobe", "bookshelf", "shelf", "cabinet", "children_cabinet", "tv_stand", "sofa"}


def _local_transform(anchor, x, z):
    angle = math.radians(anchor.get("rotation", 0))
    return (anchor["x"] + math.cos(angle) * x + math.sin(angle) * z,
            anchor["z"] - math.sin(angle) * x + math.cos(angle) * z)


def _chair_positions(chair, table):
    if chair.get("locked"):
        yield deepcopy(chair)
        return
    # The procedural desk's front and chair's face both use local +z.
    for gap in (.12, .24, .08):
        distance = table["depth"] / 2 + chair["depth"] / 2 + gap
        for offset in (0., -.10, .10):
            x, z = _local_transform(table, offset, distance)
            yield {**chair, "x": x, "z": z, "rotation": (table.get("rotation", 0) + 180) % 360}


def _nightstand_positions(stand, bed, side):
    for index, candidate in enumerate(bedside_placements(stand, bed, "left" if side < 0 else "right")):
        if index in (0, 3):
            yield candidate
        if index >= 3:
            break


def _groups(items, assignments=None):
    """Bind existing objects only; never create or remove an owned object."""
    used = set()
    groups = []
    beds = [item for item in items if item["category"] in BEDS]
    for bed in beds:
        stands = [item for item in items if item["category"] == "nightstand" and item["id"] not in used]
        # With several beds, a stand belongs to its closest existing bed.
        stands = [stand for stand in stands if (assignments or {}).get(stand["id"], {}).get("targetId", min(beds, key=lambda b: math.dist((stand["x"], stand["z"]), (b["x"], b["z"])))["id"]) == bed["id"]]
        stands.sort(key=lambda item: math.dist((item["x"], item["z"]), (bed["x"], bed["z"])))
        attached = stands[:2]
        used.update(item["id"] for item in [bed, *attached])
        groups.append((bed, attached, "bed"))
    for table in [item for item in items if item["category"] in TABLES]:
        chair_categories = {"dressing_chair", "stool"} if table["category"] == "dressing_table" else {"chair", "stool"}
        chairs = [item for item in items if item["category"] in chair_categories and item["id"] not in used]
        chairs.sort(key=lambda item: math.dist((item["x"], item["z"]), (table["x"], table["z"])))
        attached = chairs[:1]
        used.update(item["id"] for item in [table, *attached])
        groups.append((table, attached, "table"))
    for item in items:
        if item["id"] not in used:
            groups.append((item, [], "wall" if item["category"] in WALL_BACKS else "other"))
            used.add(item["id"])
    # Allocate the main activity zones before inserting small isolated objects.
    order = {"bed": 0, "table": 1, "wall": 2, "other": 3}
    groups.sort(key=lambda group: (order[group[2]], group[0]["category"] == "rug",
                                   -group[0]["width"] * group[0]["depth"]))
    return groups


def _anchor_positions(anchor, attached, kind, scene, rng):
    # Runtime import intentionally avoids the generator/template module cycle.
    from .generator import _placements, _wall_placements, _window_placements

    if anchor.get("locked"):
        yield deepcopy(anchor)
        return
    room = scene["room"]
    wall_preference = {"kind": "near_wall", "itemId": anchor["id"]}
    if kind == "table":
        # A fixed chair can anchor its movable desk, rather than being moved.
        fixed = next((chair for chair in attached if chair.get("locked")), None)
        if fixed:
            angle = math.radians(fixed.get("rotation", 0))
            for gap in (.12, .24, .08):
                distance = anchor["depth"] / 2 + fixed["depth"] / 2 + gap
                yield {**anchor, "x": fixed["x"] + math.sin(angle) * distance,
                       "z": fixed["z"] + math.cos(angle) * distance,
                       "rotation": (fixed.get("rotation", 0) + 180) % 360}
        preferences = [p for p in scene.get("preferences", []) if p["itemId"] == anchor["id"] and p["kind"] == "near_window"]
        for preference in preferences:
            yield from _window_placements(anchor, room, preference, rng)
        if anchor["category"] == "table" or evaluate_wall_preference(anchor, room, wall_preference)["satisfied"]:
            yield deepcopy(anchor)
        yield from _wall_placements(anchor, room, wall_preference, rng)
    elif kind in ("bed", "wall"):
        if kind == "bed":
            yield from bed_placements_for_locked_stands(anchor, [stand for stand in attached if stand.get("locked")])
        yield from _wall_placements(anchor, room, wall_preference, rng)
    else:
        yield from _placements(anchor, room, rng, scene.get("preferences", []))


def _group_positions(anchor, attached, kind):
    if kind == "table" and attached:
        for chair in _chair_positions(attached[0], anchor):
            yield [anchor, chair]
    elif kind == "bed" and attached:
        sides = [(-1,), (1,)] if len(attached) == 1 else [(-1, 1), (1, -1)]
        for arrangement in sides:
            first_options = list(_nightstand_positions(attached[0], anchor, arrangement[0]))
            for first in first_options:
                if len(attached) == 1:
                    yield [anchor, first]
                else:
                    for second in _nightstand_positions(attached[1], anchor, arrangement[1]):
                        yield [anchor, first, second]
    else:
        yield [anchor]


def _facing_table(chair, table):
    dx, dz = table["x"] - chair["x"], table["z"] - chair["z"]
    length = math.hypot(dx, dz)
    angle = math.radians(chair.get("rotation", 0))
    return length > 1e-8 and (math.sin(angle) * dx + math.cos(angle) * dz) / length >= math.cos(math.radians(20))


def functional_template(scene, rng, budget=None):
    """Return one complete independently validated proposal, otherwise None.

    The bounded recursive search places a few alternatives per functional
    group. Locked pieces are obstacles from the beginning. A failed attempt
    never escapes as a partial scene or a scene with fewer objects.
    """
    from .generator import _location_cost, _candidate_quality_cost

    if any(preference.get("required") for preference in scene.get("preferences", [])):
        return None
    groups = _groups(scene["items"], bedside_assignments(scene))
    fixed = [deepcopy(item) for item in scene["items"] if item.get("locked")]
    if any(placement_errors(item, scene["room"], fixed[:index], gap=0) for index, item in enumerate(fixed)):
        return None
    # Cheap geometry calls and recursion are both bounded even without a
    # caller-provided SearchBudget (for offline tests and other consumers).
    calls_left = 9000
    nodes_left = 70
    exhausted = False

    def take():
        nonlocal calls_left, exhausted
        calls_left -= 1
        if calls_left < 0 or (budget is not None and not budget.take()):
            exhausted = True
            return False
        return True

    def solve(index, placed):
        nonlocal nodes_left
        nodes_left -= 1
        if nodes_left < 0 or exhausted:
            return None
        if index == len(groups):
            by_id = {item["id"]: item for item in placed}
            proposed = deepcopy(scene)
            proposed["items"] = [by_id[item["id"]] for item in scene["items"]]
            assert_invariants(scene, proposed)
            if validate_scene(proposed)["valid"] and evaluate_layout_requirements(proposed)["satisfied"] and evaluate_bedside_groups(proposed, scene)["satisfied"]:
                return proposed
            return None
        anchor, attached, kind = groups[index]
        group_ids = {item["id"] for item in [anchor, *attached]}
        obstacles = [item for item in placed if item["id"] not in group_ids]
        options = []
        seen = set()
        # Enumerate enough real wall anchors while limiting attachment products.
        for number, candidate in enumerate(_anchor_positions(anchor, attached, kind, scene, rng)):
            if number >= 150 or not take():
                break
            if placement_errors(candidate, scene["room"], obstacles, gap=.025):
                continue
            for group in _group_positions(candidate, attached, kind):
                if not take():
                    break
                if kind == "table" and attached and not _facing_table(group[1], group[0]):
                    # If both are locked an existing bad relationship cannot be
                    # silently corrected; this template simply yields no result.
                    continue
                accepted = []
                for item in group:
                    if placement_errors(item, scene["room"], [*obstacles, *accepted], gap=.025):
                        break
                    accepted.append(item)
                if len(accepted) != len(group):
                    continue
                fingerprint = tuple((item["id"], round(item["x"], 3), round(item["z"], 3), round(item.get("rotation", 0), 2)) for item in group)
                if fingerprint in seen:
                    continue
                seen.add(fingerprint)
                local = sum(_location_cost(item, scene, scene, [*obstacles, *[other for other in group if other["id"] != item["id"]]], .15) for item in group)
                options.append((local + rng.uniform(0, .04), group))
        if not options or exhausted:
            return None
        options.sort(key=lambda option: option[0])
        # Rank complete groups together; sequential chair placement must not
        # undo the functional relationship after choosing a table.
        shortlist = options[:10]
        ranked = []
        for local, group in shortlist:
            partial_scene = {**scene, "items": [*obstacles, *group]}
            cost = _candidate_quality_cost(group[-1], partial_scene, [*obstacles, *group[:-1]], local)
            ranked.append((cost, group))
        ranked.sort(key=lambda option: option[0])
        for _, group in ranked[:5]:
            result = solve(index + 1, [*obstacles, *group])
            if result is not None:
                return result
        return None

    return solve(0, fixed)

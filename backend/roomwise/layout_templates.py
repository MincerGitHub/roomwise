"""Small functional furniture groups for ordinary whole-room proposals.

These are explainable candidate templates, not a style model or an ergonomic
standard. Explicit user requests use the separate local constraint search.
"""
from __future__ import annotations

from copy import deepcopy
import math

from .geometry import assert_invariants, footprint, layout_quality, search_placement_errors as placement_errors, validate_scene
from .window_constraints import evaluate_layout_requirements, evaluate_wall_preference
from .bedside_constraints import bedside_assignments, bedside_placements, bed_placements_for_locked_stands, evaluate_bedside_groups
from .supports import WALL_APPLIANCES
from .wall_placements import appliance_placements
from .functional_constraints import evaluate_functional_spaces, functional_pairs, front_rotation, front_sign, local_position


BEDS = {"double_bed", "single_bed", "kids_bed"}
TABLES = {"desk", "table", "dressing_table"}
SEATS = {"chair", "dressing_chair", "stool"}
WALL_BACKS = {"wardrobe", "bookshelf", "shelf", "cabinet", "children_cabinet", "tv_stand", "sofa"}


def _local_transform(anchor, x, z):
    angle = math.radians(anchor.get("rotation", 0))
    return (anchor["x"] + math.cos(angle) * x + math.sin(angle) * z,
            anchor["z"] - math.sin(angle) * x + math.cos(angle) * z)


def _chair_positions(chair, table, lateral=0., side=1.):
    if chair.get("locked"):
        yield deepcopy(chair)
        return
    for gap in (.12, .24, .08):
        distance = table["depth"] / 2 + chair["depth"] / 2 + gap
        x, z = local_position(table, lateral, front_sign(table) * side * distance)
        toward_table = 180 if side > 0 else 0
        yield {**chair, "x": x, "z": z,
               "rotation": (front_rotation(table) + toward_table - (180 if front_sign(chair) < 0 else 0)) % 360}


def _nightstand_positions(stand, bed, side):
    for index, candidate in enumerate(bedside_placements(stand, bed, "left" if side < 0 else "right")):
        if index in (0, 3):
            yield candidate
        if index >= 3:
            break


def _seat_offsets(table, seats):
    count = len(seats)
    if count == 1:
        return [(0., 1.)]
    if count == 2:
        required_span = (seats[0]["width"] + seats[1]["width"]) / 2 + .05
        max_span = table["width"] - max(chair["width"] for chair in seats) - .10
        if required_span <= max_span:
            return [(-required_span / 2, 1.), (required_span / 2, 1.)]
        return [(0., 1.), (0., -1.)]
    offsets = []
    for side_start in range(0, count, 2):
        side_seats = seats[side_start:side_start + 2]
        span = ((side_seats[0]["width"] + side_seats[1]["width"]) / 2 + .05
                if len(side_seats) == 2 else 0.)
        lane = span / 2
        side = 1. if side_start == 0 else -1.
        offsets.extend([(-lane, side), (lane, side)] if len(side_seats) == 2 else [(0., side)])
    return offsets


def _groups(items, assignments=None, pairs=None):
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
    tables = [item for item in items if item["category"] in TABLES]
    partners = {}
    for kind, aid, bid in (functional_pairs({"items": items}) if pairs is None else pairs):
        if kind == "work":
            partners.setdefault(aid, []).append(bid)
    by_id = {item["id"]: item for item in items}
    for table in tables:
        attached = [by_id[seat_id] for seat_id in partners.get(table["id"], [])]
        used.update(item["id"] for item in [table, *attached])
        groups.append((table, attached, "table"))
    for item in items:
        if item["id"] not in used:
            groups.append((item, [], "appliance" if item["category"] in WALL_APPLIANCES else "wall" if item["category"] in WALL_BACKS else "other"))
            used.add(item["id"])
    # Allocate the main activity zones before inserting small isolated objects.
    order = {"appliance": -1, "bed": 0, "table": 1, "wall": 2, "other": 3}
    groups.sort(key=lambda group: (order[group[2]], group[0]["category"] == "rug",
                                   -group[0]["width"] * group[0]["depth"]))
    return groups


def _anchor_positions(anchor, attached, kind, scene, rng):
    # Runtime import intentionally avoids the generator/template module cycle.
    from .generator import _placements, _wall_placements, _window_placements

    if anchor.get("locked"):
        yield deepcopy(anchor)
        return
    if anchor["category"] in WALL_APPLIANCES:
        yield from appliance_placements(anchor,scene["room"])
        return
    room = scene["room"]
    wall_preference = {"kind": "near_wall", "itemId": anchor["id"]}
    if kind == "table":
        # A fixed chair can anchor its movable desk, rather than being moved.
        fixed = next((chair for chair in attached if chair.get("locked")), None)
        if fixed:
            angle = math.radians(front_rotation(fixed))
            for gap in (.12, .24, .08):
                distance = anchor["depth"] / 2 + fixed["depth"] / 2 + gap
                yield {**anchor, "x": fixed["x"] + math.sin(angle) * distance,
                       "z": fixed["z"] + math.cos(angle) * distance,
                       "rotation": (front_rotation(fixed) + 180 - (180 if front_sign(anchor) < 0 else 0)) % 360}
        preferences = [p for p in scene.get("preferences", []) if p["itemId"] == anchor["id"] and p["kind"] == "near_window"]
        for preference in preferences:
            yield from _window_placements(anchor, room, preference, rng)
        if anchor["category"] == "table" and len(attached) > 1:
            # A dining table with several seats needs room on multiple sides;
            # only searching wall anchors can trap one seat against the wall.
            yield from _placements(anchor, room, rng, scene.get("preferences", []))
        if anchor["category"] == "table" or evaluate_wall_preference(anchor, room, wall_preference)["satisfied"]:
            yield deepcopy(anchor)
        for candidate in _wall_placements(anchor, room, wall_preference, rng):
            if front_sign(anchor) < 0:
                candidate = {**candidate, "rotation": (candidate["rotation"] + 180) % 360}
            yield candidate
    elif kind in ("bed", "wall"):
        if kind == "bed":
            yield from bed_placements_for_locked_stands(anchor, [stand for stand in attached if stand.get("locked")])
        yield from _wall_placements(anchor, room, wall_preference, rng)
    else:
        yield from _placements(anchor, room, rng, scene.get("preferences", []))


def _group_positions(anchor, attached, kind, room=None):
    if kind == "table" and attached:
        offsets = _seat_offsets(anchor, attached)

        def place_seats(index, placed):
            if index == len(attached):
                yield [anchor, *placed]
                return
            lateral, side = offsets[index]
            for chair in _chair_positions(attached[index], anchor, lateral, side):
                if room is not None and placement_errors(chair, room, [anchor, *placed], gap=.025):
                    continue
                yield from place_seats(index + 1, [*placed, chair])
        yield from place_seats(0, [])
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
    angle = math.radians(front_rotation(chair))
    return length > 1e-8 and (math.sin(angle) * dx + math.cos(angle) * dz) / length >= math.cos(math.radians(20))


def functional_template(scene, rng, budget=None):
    """Return one complete independently validated proposal, otherwise None.

    The bounded recursive search places a few alternatives per functional
    group. Locked pieces are obstacles from the beginning. A failed attempt
    never escapes as a partial scene or a scene with fewer objects.
    """
    from .generator import _location_cost

    if any(preference.get("required") for preference in scene.get("preferences", [])):
        return None
    groups = _groups(scene["items"], bedside_assignments(scene), functional_pairs(scene))
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
            if (validate_scene(proposed)["valid"] and evaluate_layout_requirements(proposed)["satisfied"]
                    and evaluate_bedside_groups(proposed, scene)["satisfied"]
                    and evaluate_functional_spaces(proposed, scene)["satisfied"]
                    and evaluate_functional_spaces(proposed)["satisfied"]):
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
            for group in _group_positions(candidate, attached, kind, scene["room"]):
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
        ranked = []
        for local, group in options:
            if not take():
                return None
            partial_scene = {**scene, "items": [*obstacles, *group]}
            # Each newly placed group must also preserve previously allocated
            # chair pullout, bed access and declared front use spaces. Reject
            # blockers here so recursion can try another pose or backtrack.
            functional = evaluate_functional_spaces(partial_scene, scene)
            if not functional["satisfied"]:
                continue
            cost = local + 1.15 * layout_quality(partial_scene)["penalty"] + functional["penalty"]
            ranked.append((cost, group))
            if len(ranked) >= 10:
                break
        ranked.sort(key=lambda option: option[0])
        for _, group in ranked[:5]:
            result = solve(index + 1, [*obstacles, *group])
            if result is not None:
                return result
        return None

    return solve(0, fixed)

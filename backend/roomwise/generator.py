from __future__ import annotations

from copy import deepcopy
from .layout_templates import functional_template
import importlib
import math
import random
import time
import uuid

import numpy as np

from .bedside_constraints import bedside_assignments, bedside_placements, bed_placements_for_locked_stands, evaluate_bedside_groups, evaluate_bedside_preference

from .geometry import (
    assert_invariants,
    footprint,
    layout_quality,
    opening_center,
    placement_errors,
    preference_penalty,
    room_polygon,
    validate_scene,
)
from .window_constraints import (
    EXPLICIT_SPATIAL_KINDS,
    evaluate_layout_requirements,
    evaluate_spatial_preference,
    evaluate_wall_preference,
    evaluate_window_preference,
    matching_wall_segments,
    matching_windows,
)


MAX_GENERATION_ITEMS = 32
SEARCH_SECONDS = 8.0
SEARCH_PLACEMENT_CHECKS = 12000


class SearchBudget:
    def __init__(self):
        self.deadline = time.monotonic() + SEARCH_SECONDS
        self.remaining = SEARCH_PLACEMENT_CHECKS
        self.exhausted = False

    def take(self):
        self.remaining -= 1
        if self.remaining < 0 or time.monotonic() > self.deadline:
            self.exhausted = True
            return False
        return True


def learning_status():
    try:
        module = importlib.import_module("roomwise.learning")
        status = module.model_status()
        if not isinstance(status, dict):
            return {"available": False, "loaded": False, "reason": "模型状态格式无效"}
        return status
    except Exception as exc:
        return {"available": False, "loaded": False, "reason": f"模型不可用：{type(exc).__name__}"}


def _available(status):
    return bool(status.get("available", status.get("loaded", status.get("modelLoaded", False))))


def _sanitize_model_output(original, proposed):
    """Only transforms are an ML output; source metadata remains authoritative."""
    if not isinstance(proposed, dict) or not isinstance(proposed.get("items"), list):
        raise ValueError("模型未返回有效场景")
    items = {i["id"]: i for i in proposed["items"]}
    if len(items) != len(original["items"]) or set(items) != {i["id"] for i in original["items"]}:
        raise ValueError("模型返回的家具列表不完整")
    result = deepcopy(original)
    for item in result["items"]:
        if item.get("locked"):
            continue
        for key in ("x", "z", "rotation"):
            value = float(items[item["id"]][key])
            if not math.isfinite(value):
                raise ValueError("模型输出包含非有限坐标")
            item[key] = value % 360 if key == "rotation" else value
    assert_invariants(original, result)
    return result


def _location_cost(item, scene, original, placed, anchor_strength=0):
    cost = 0.
    room = scene["room"]
    diag = math.hypot(room["width"], room["depth"])
    if anchor_strength:
        anchor = next(i for i in original["items"] if i["id"] == item["id"])
        cost += anchor_strength * math.hypot(item["x"] - anchor["x"], item["z"] - anchor["z"]) / diag
    prefs = [p for p in scene.get("preferences", []) if p["itemId"] == item["id"]]
    for pref in prefs:
        if pref["kind"] == "min_move":
            old = next(i for i in original["items"] if i["id"] == item["id"])
            cost += math.hypot(item["x"] - old["x"], item["z"] - old["z"]) * 3 / diag
        elif pref["kind"] == "near_window":
            windows = [w for w in room.get("windows", []) if not pref.get("targetId") or w["id"] == pref["targetId"]]
            if windows:
                cost += min(math.dist((item["x"], item["z"]), opening_center(room, w)) for w in windows) * 3 / diag
        elif pref["kind"] == "face_window":
            check = evaluate_window_preference(item, room, pref)
            cost += check["metrics"].get("angularErrorDegrees", 180) / 60
        elif pref["kind"] == "near_wall":
            check = evaluate_wall_preference(item, room, pref)
            cost += check["metrics"].get("distanceMeters", diag) * 3
            cost += check["metrics"].get("backAlignmentErrorDegrees", 180) / 60
    poly = footprint(item)
    if item["category"] in {"wardrobe", "double_bed", "single_bed", "kids_bed", "bookshelf", "cabinet", "desk", "sofa", "tv_stand"}:
        # A soft near-wall heuristic; no assumption that it is always desirable.
        cost += poly.distance(room_polygon(room).boundary) * .6
    if item["category"] in {"chair", "dressing_chair", "nightstand"}:
        partner_categories = {"desk", "table", "dressing_table"} if item["category"] != "nightstand" else {"double_bed", "single_bed", "kids_bed"}
        partners = [p for p in placed if p["category"] in partner_categories]
        if partners:
            target_gap = .08 if item["category"] == "nightstand" else .12
            grouping_strength = 1.5 if item["category"] == "nightstand" else .8
            distance = min(poly.distance(footprint(p)) for p in partners)
            cost += max(0.0, distance - target_gap) * grouping_strength
    return cost


def _candidate_quality_cost(candidate, result, placed, local_cost):
    """Run the more expensive whole-layout score only on promising placements."""
    partial = deepcopy(result)
    partial["items"] = [*placed, candidate]
    return local_cost + 1.15 * layout_quality(partial)["penalty"]


def _wall_placements(item, room, preference, rng):
    """Align furniture backs with actual boundary segments, including slopes."""
    if item.get("locked"):
        yield deepcopy(item)
        return
    walls = matching_wall_segments(room, preference)
    # Nearest viable wall first; the final cost also penalises unnecessary moves.
    walls.sort(key=lambda wall: footprint(item).distance(wall["segment"]))
    for wall in walls:
        start, tangent, inward = wall["start"], wall["tangent"], wall["inward"]
        left, right = item["width"] / 2 + .03, wall["length"] - item["width"] / 2 - .03
        if left > right:
            continue
        original_projection = (item["x"] - start[0]) * tangent[0] + (item["z"] - start[1]) * tangent[1]
        projection = min(right, max(left, original_projection))
        projections = list(dict.fromkeys([projection, (left + right) / 2,
                                         *map(float, np.linspace(left, right, min(15, max(3, int((right - left) / .3) + 2))))]))
        rotation = math.degrees(math.atan2(inward[0], inward[1])) % 360
        for gap in (.03, .09, .14):
            for along in projections:
                distance = item["depth"] / 2 + gap
                yield {**item, "x": start[0] + tangent[0] * along + inward[0] * distance,
                       "z": start[1] + tangent[1] * along + inward[1] * distance, "rotation": rotation}


def _placements(item, room, rng, preferences=()):
    # Include the original transform, wall-adjacent grid placements and samples.
    yield deepcopy(item)
    for preference in preferences:
        if preference["kind"] == "near_wall" and preference["itemId"] == item["id"]:
            yield from _wall_placements(item, room, preference, rng)
    rotations = list(dict.fromkeys([item.get("rotation", 0) % 360, 0., 90., 180., 270.]))
    rng.shuffle(rotations)
    for angle in rotations:
        trial = {**item, "x": 0, "z": 0, "rotation": angle}
        minx, minz, maxx, maxz = footprint(trial).bounds
        left, right = -minx + .03, room["width"] - maxx - .03
        south, north = -minz + .03, room["depth"] - maxz - .03
        if left > right or south > north:
            continue
        xs = np.linspace(left, right, min(24, max(2, int((right - left) / .25) + 2)))
        zs = np.linspace(south, north, min(24, max(2, int((north - south) / .25) + 2)))
        edge_points = [(float(x), south) for x in xs] + [(float(x), north) for x in xs] + [(left, float(z)) for z in zs] + [(right, float(z)) for z in zs]
        rng.shuffle(edge_points)
        for x, z in edge_points[:60]:
            yield {**item, "x": x, "z": z, "rotation": angle}
        for _ in range(28):
            yield {**item, "x": rng.uniform(left, right), "z": rng.uniform(south, north), "rotation": angle}


def _required_item_passes(item, room, preferences):
    return all(evaluate_spatial_preference(item, room, preference)["satisfied"]
               for preference in preferences
               if preference.get("required") and preference["itemId"] == item["id"]
               and preference["kind"] in ("near_window", "face_window", "near_wall"))


def _dependent_placements(item, scene, original, placed, rng):
    """A nightstand follows its assigned bed's final transform, never a grid."""
    assignments = bedside_assignments(scene, original)
    assignment = assignments.get(item["id"])
    if assignment:
        bed = next((candidate for candidate in placed if candidate["id"] == assignment["targetId"]), None)
        if bed is None:
            return
        side = assignment.get("side") or "either"
        sides = [side] if assignment.get("required") or side == "either" else [side, "left" if side == "right" else "right"]
        for selected_side in sides:
            for candidate in bedside_placements(item, bed, selected_side):
                functional = assignment if assignment.get("required") else {**assignment, "side": "either"}
                if evaluate_bedside_preference(candidate, bed, functional)["satisfied"]:
                    yield candidate
        return
    fixed_stands = [stand for stand in original["items"] if stand.get("locked") and assignments.get(stand["id"], {}).get("targetId") == item["id"]]
    yield from bed_placements_for_locked_stands(item, fixed_stands)
    yield from _placements(item, scene["room"], rng, scene.get("preferences", []))


def _window_placements(item, room, preference, rng):
    """Place a table front toward the room, with its back at an actual window."""
    if item.get("locked"):
        yield deepcopy(item)
        return
    windows = matching_windows(room, preference)
    rng.shuffle(windows)
    for window in windows:
        rotation = {"north": 180., "south": 0., "east": 270., "west": 90.}[window["wall"]]
        # Include the present projected centre to minimise unnecessary moves.
        horizontal = window["wall"] in ("north", "south")
        present = item["x"] if horizontal else item["z"]
        center = window["offset"] + window["width"] / 2
        projections = [center, present, *np.linspace(window["offset"] - item["width"] / 2 + .18,
                                                    window["offset"] + window["width"] + item["width"] / 2 - .18, 9)]
        # Windows of arbitrary height do not promise that furniture clears the sill;
        # this is a floor-plan request, not a mesh reconstruction or opening test.
        for gap in (.04, .16, .34, .54):
            for projection in projections:
                coords = {"north": (projection, room["depth"] - item["depth"] / 2 - gap),
                          "south": (projection, item["depth"] / 2 + gap),
                          "east": (room["width"] - item["depth"] / 2 - gap, projection),
                          "west": (item["depth"] / 2 + gap, projection)}[window["wall"]]
                yield {**item, "x": float(coords[0]), "z": float(coords[1]), "rotation": rotation}


def _chair_pair_placements(chair, table, room, preference):
    if chair.get("locked"):
        yield deepcopy(chair)
        return
    windows = matching_windows(room, preference)
    if not windows:
        return
    # Choose the room side of the window and face back across the table at it.
    window = min(windows, key=lambda w: math.dist(opening_center(room, w), (table["x"], table["z"])))
    out_angle = {"north": 180., "south": 0., "east": 270., "west": 90.}[window["wall"]]
    outward = math.sin(math.radians(out_angle)), math.cos(math.radians(out_angle))
    tangent = outward[1], -outward[0]
    # Use rotated table depth along the window normal, including locked tables.
    bounds = footprint(table).bounds
    normal_depth = bounds[3] - bounds[1] if window["wall"] in ("north", "south") else bounds[2] - bounds[0]
    for gap in (.08, .16, .28):
        distance = normal_depth / 2 + chair["depth"] / 2 + gap
        for offset in (0., -.12, .12):
            x = table["x"] + outward[0] * distance + tangent[0] * offset
            z = table["z"] + outward[1] * distance + tangent[1] * offset
            # Desk and chair form a usable group: chair faces the table, not a
            # diagonal direction unrelated to its work surface. The separate
            # face-window check rejects groups too far sideways from the window.
            rotation = (out_angle + 180) % 360
            yield {**chair, "x": x, "z": z, "rotation": rotation}


def _place_remaining(result, original, placed, movable, rng, anchor_strength, budget):
    jitter = {i["id"]: rng.uniform(.85, 1.15) for i in movable}
    movable.sort(key=lambda i: (i["category"] in ("nightstand", "rug"), i["category"] == "rug", -i["width"] * i["depth"] * jitter[i["id"]]))
    for item in movable:
        options = []
        preferences = result.get("preferences", [])
        face_preferences = [p for p in preferences if p["itemId"] == item["id"] and p["kind"] == "face_window" and p.get("required")]
        for candidate in _dependent_placements(item, result, original, placed, rng):
            if budget and not budget.take():
                return None
            if face_preferences:
                windows = matching_windows(result["room"], face_preferences[0])
                if not windows:
                    return None
                window = min(windows, key=lambda w: math.dist(opening_center(result["room"], w), (candidate["x"], candidate["z"])))
                wx, wz = opening_center(result["room"], window)
                candidate["rotation"] = math.degrees(math.atan2(wx - candidate["x"], wz - candidate["z"])) % 360
            if not _required_item_passes(candidate, result["room"], preferences):
                continue
            if not placement_errors(candidate, result["room"], placed, gap=.025):
                local = _location_cost(candidate, result, original, placed, anchor_strength)
                options.append((local + rng.uniform(0, .025), local, candidate))
        if not options:
            return None
        options.sort(key=lambda row: row[0])
        shortlist = options[:min(6, len(options))]
        ranked = [(_candidate_quality_cost(candidate, result, placed, local) + jitter_score, candidate)
                  for jitter_score, local, candidate in shortlist]
        ranked.sort(key=lambda row: row[0])
        placed.append(ranked[rng.randrange(min(2, len(ranked)))][1])
    return placed


def _constraint_rule_candidate(original, rng, anchor_strength, budget):
    """Preserve unrelated items first; keep explicit window desk/chair grouping."""
    room = original["room"]
    preferences = original.get("preferences", [])
    items = {item["id"]: item for item in original["items"]}
    window_requests = [p for p in preferences if p.get("required") and p["kind"] in ("near_window", "face_window")]
    if any(not matching_windows(room, p) for p in window_requests):
        return None
    if any(items[p["itemId"]].get("locked") and not evaluate_window_preference(items[p["itemId"]], room, p)["satisfied"] for p in window_requests):
        return None
    groups, used_chairs = [], set()
    for preference in window_requests:
        table = items[preference["itemId"]]
        if preference["kind"] != "near_window" or table["category"] not in {"desk", "table", "dressing_table"}:
            continue
        chairs = [item for item in original["items"] if item["category"] in {"chair", "dressing_chair", "stool"} and item["id"] not in used_chairs]
        # An explicitly facing chair gets paired first; remaining ties use distance.
        facing_ids = {p["itemId"] for p in window_requests if p["kind"] == "face_window" and
                      (not p.get("targetId") or not preference.get("targetId") or p["targetId"] == preference["targetId"])}
        chair = min(chairs, key=lambda c: (c["id"] not in facing_ids, math.dist((c["x"], c["z"]), (table["x"], table["z"])))) if chairs else None
        if chair:
            used_chairs.add(chair["id"])
        groups.append((table, chair, preference))
    # A soft wall request still names furniture that the user expects the
    # layout search to reconsider.  It must not be treated as an unrelated
    # item merely because a separate hard request (for example, a desk near a
    # window) sends us through the constraint-preserving branch.
    affected_ids = {p["itemId"] for p in preferences
                    if (p.get("required") and p["kind"] in EXPLICIT_SPATIAL_KINDS)
                    or p["kind"] == "near_wall"} | used_chairs
    assignments = bedside_assignments(original)
    initial_relations = evaluate_bedside_groups(original)
    affected_ids.update(check["itemId"] for check in initial_relations["unsatisfied"])
    affected_ids.update(assignment["targetId"] for stand_id, assignment in assignments.items()
                        if assignment.get("required") and items[stand_id].get("locked")
                        and not items[assignment["targetId"]].get("locked"))
    affected_ids.update(stand_id for stand_id, assignment in assignments.items() if assignment["targetId"] in affected_ids)

    def finish_preserving_clear(placed, movable):
        """Backtrack remaining blockers before releasing unrelated furniture.

        Greedy placements can each fit while jointly cutting the route to a
        fixed wardrobe. Try a small set of complete alternatives under the
        original shared budget rather than treating that as a reason to move
        an otherwise unobstructing shelf.
        """
        pending = sorted(movable, key=lambda item: (item["category"] in ("nightstand", "rug"), item["category"] == "rug", -item["width"] * item["depth"]))
        nodes_left = 24

        def search(index, staged):
            nonlocal nodes_left
            nodes_left -= 1
            if nodes_left < 0 or (budget and not budget.take()):
                return None
            if index == len(pending):
                by_id = {item["id"]: item for item in staged}
                proposed = {**original, "items": [by_id[item["id"]] for item in original["items"]]}
                return staged if evaluate_layout_requirements(proposed)["satisfied"] and evaluate_bedside_groups(proposed, original)["satisfied"] and validate_scene(proposed)["valid"] else None
            item = pending[index]
            options = []
            face_preferences = [preference for preference in preferences if preference["itemId"] == item["id"] and preference["kind"] == "face_window" and preference.get("required")]
            for candidate in _dependent_placements(item, original, original, staged, rng):
                if budget and not budget.take():
                    return None
                if face_preferences:
                    windows = matching_windows(room, face_preferences[0])
                    if not windows:
                        return None
                    window = min(windows, key=lambda window: math.dist(opening_center(room, window), (candidate["x"], candidate["z"])))
                    wx, wz = opening_center(room, window)
                    candidate["rotation"] = math.degrees(math.atan2(wx - candidate["x"], wz - candidate["z"])) % 360
                if not _required_item_passes(candidate, room, preferences) or placement_errors(candidate, room, staged, gap=.025):
                    continue
                local = _location_cost(candidate, original, original, staged, max(anchor_strength, 2.5))
                options.append((local + rng.uniform(0, .025), candidate))
            options.sort(key=lambda option: option[0])
            # A larger shortlist than the fast greedy pass exposes alternate
            # approach paths; the expensive score is still bounded.
            ranked = [(_candidate_quality_cost(candidate, original, staged, local), candidate)
                      for local, candidate in options[:18]]
            ranked.sort(key=lambda option: option[0])
            for _, candidate in ranked[:12]:
                if budget and not budget.take():
                    return None
                partial = {**original, "items": [*staged, candidate]}
                if not validate_scene(partial)["valid"]:
                    continue
                completed = search(index + 1, [*staged, candidate])
                if completed is not None:
                    return completed
            return None

        return search(0, placed)

    for preserve_others in (True, "keep_clear", False):
        result = deepcopy(original)
        placed = [deepcopy(i) for i in original["items"] if i.get("locked") or (preserve_others is True and i["id"] not in affected_ids)]
        # Keeping an already colliding original arrangement is not a successful local edit.
        if any(placement_errors(item, room, placed[:index], gap=0) for index, item in enumerate(placed)):
            continue
        failed = False
        for table, chair, preference in groups:
            group_ids = {table["id"]} | ({chair["id"]} if chair else set())
            obstacles = [item for item in placed if item["id"] not in group_ids]
            options = []
            for table_candidate in _window_placements(table, room, preference, rng):
                if budget and not budget.take():
                    return None
                if not _required_item_passes(table_candidate, room, preferences) or placement_errors(table_candidate, room, obstacles, gap=.025):
                    continue
                chair_options = _chair_pair_placements(chair, table_candidate, room, preference) if chair else [None]
                for chair_candidate in chair_options:
                    if budget and not budget.take():
                        return None
                    if chair_candidate and (not _required_item_passes(chair_candidate, room, preferences) or placement_errors(chair_candidate, room, [*obstacles, table_candidate], gap=.025)):
                        continue
                    group = [table_candidate, *([chair_candidate] if chair_candidate else [])]
                    cost = sum(_location_cost(member, result, original, [*obstacles, *[g for g in group if g["id"] != member["id"]]], max(anchor_strength, .7)) for member in group)
                    # Prefer a desk close to the actual window and a chair centred before it.
                    cost += evaluate_window_preference(table_candidate, room, preference)["metrics"].get("distanceMeters", 0) * .8
                    options.append((cost + rng.uniform(0, .015), group))
            if not options:
                failed = True
                break
            options.sort(key=lambda row: row[0])
            # Keep only inexpensive finalists for whole-layout quality scoring.
            shortlist = options[:4]
            ranked = []
            for cost, group in shortlist:
                partial = {**result, "items": [*obstacles, *group]}
                ranked.append((cost + layout_quality(partial)["penalty"] * .6, group))
            ranked.sort(key=lambda row: row[0])
            selected = ranked[rng.randrange(min(2, len(ranked)))][1]
            placed = [*obstacles, *selected]
        if failed:
            continue
        if preserve_others == "keep_clear":
            # Preserve every unrelated piece that does not block the new group.
            # Only blockers are searched again; a later broad pass remains a fallback.
            existing_ids = {item["id"] for item in placed}
            for item in original["items"]:
                assignment = assignments.get(item["id"])
                bed = next((candidate for candidate in placed if assignment and candidate["id"] == assignment["targetId"]), None)
                valid_bedside = not assignment or bool(bed and evaluate_bedside_preference(item, bed, assignment)["satisfied"])
                if item["id"] not in affected_ids and item["id"] not in existing_ids and valid_bedside and not placement_errors(item, room, placed):
                    placed.append(deepcopy(item))
        placed_ids = {item["id"] for item in placed}
        movable = [deepcopy(i) for i in original["items"] if i["id"] not in placed_ids]
        preserved_base = deepcopy(placed)
        placed = _place_remaining(result, original, placed, movable, rng, max(anchor_strength, 2.5), budget)
        if preserve_others == "keep_clear" and (placed is None or not validate_scene({**result, "items": placed})["valid"] or not evaluate_bedside_groups({**result, "items": placed}, original)["satisfied"]):
            placed = finish_preserving_clear(preserved_base, movable)
        if placed is None:
            continue
        by_id = {item["id"]: item for item in placed}
        result["items"] = [by_id[item["id"]] for item in original["items"]]
        assert_invariants(original, result)
        if evaluate_layout_requirements(result)["satisfied"] and evaluate_bedside_groups(result, original)["satisfied"] and validate_scene(result)["valid"]:
            return result
    return None


def rule_candidate(original: dict, rng: random.Random, anchor_strength=0, budget=None):
    if any(p.get("required") and p["kind"] in EXPLICIT_SPATIAL_KINDS for p in original.get("preferences", [])):
        return _constraint_rule_candidate(original, rng, anchor_strength, budget)
    result = deepcopy(original)
    room = result["room"]
    placed = [deepcopy(i) for i in result["items"] if i.get("locked")]
    movable = [deepcopy(i) for i in result["items"] if not i.get("locked")]
    # Large solid furniture first; small pieces are inserted around it, rugs last.
    jitter = {i["id"]: rng.uniform(.85, 1.15) for i in movable}
    movable.sort(key=lambda i: (i["category"] in ("nightstand", "rug"), i["category"] == "rug", -i["width"] * i["depth"] * jitter[i["id"]]))
    for item in movable:
        options = []
        for candidate in _dependent_placements(item, result, original, placed, rng):
            if budget and not budget.take():
                return None
            if not placement_errors(candidate, room, placed, gap=.025):
                local = _location_cost(candidate, result, original, placed, anchor_strength)
                options.append((local + rng.uniform(0, .025), local, candidate))
        if not options:
            return None
        options.sort(key=lambda row: row[0])
        # Enumerating hundreds of possible positions is cheap; computing a
        # whole-layout polygon score for each position is not. Refine only a
        # small shortlist with the explainable global quality terms.
        shortlist = options[:min(6, len(options))]
        ranked = [(_candidate_quality_cost(candidate, result, placed, local) + jitter,
                   candidate)
                  for jitter, local, candidate in shortlist]
        ranked.sort(key=lambda row: row[0])
        selected = ranked[rng.randrange(min(2, len(ranked)))][1]
        placed.append(selected)
    by_id = {i["id"]: i for i in placed}
    result["items"] = [by_id[i["id"]] for i in original["items"]]
    assert_invariants(original, result)
    return result


def _fingerprint(scene):
    return tuple((i["id"], round(i["x"], 2), round(i["z"], 2), round(i.get("rotation", 0) % 360, 1)) for i in scene["items"])


def generate_layouts(scene: dict, mode="hybrid", count=3, seed=42):
    started = time.monotonic()
    rng = random.Random(seed)
    candidates = []
    fingerprints = set()
    rejected = {"geometry": 0, "requirements": 0, "functionalRelations": 0, "placementFailed": 0, "model": 0}
    budget = SearchBudget()
    has_spatial_requirements = any(preference.get("required") and preference["kind"] in EXPLICIT_SPATIAL_KINDS
                                  for preference in scene.get("preferences", []))
    # Keep arbitrary imports editable, but bound a single search request.
    if len(scene["items"]) > MAX_GENERATION_ITEMS:
        return {"baseVersion": scene.get("version", 0), "candidates": [], "diagnostics": {"message": f"单次自动布局最多支持{MAX_GENERATION_ITEMS}件家具，当前有{len(scene['items'])}件。请分房间或减少本次参与物品；系统未自动删除。", "generationItemLimit": MAX_GENERATION_ITEMS, "elapsedSeconds": 0}}
    original_check = validate_scene(scene)
    locked_scene = deepcopy(scene)
    locked_scene["items"] = [i for i in scene["items"] if i.get("locked")]
    locked_check = validate_scene(locked_scene, check_access=False)
    status = learning_status()
    diagnostics = {"modelStatus": status, "seed": seed, "attempts": 0, "modelProposals": 0, "rawModelAccepted": 0, "repairedModelAccepted": 0, "rejected": rejected, "searchLimits": {"items": MAX_GENERATION_ITEMS, "seconds": SEARCH_SECONDS, "placementChecks": SEARCH_PLACEMENT_CHECKS}, "message": "", "limitations": ["候选必须通过独立占地、门口及近似可达性检查", "未找到候选不能证明所有数学可能性都无解；请调整条件后重试"]}
    if not locked_check["valid"]:
        diagnostics.update(message="锁定家具本身存在越界、门口或相互碰撞。请先修正或明确解锁。", lockedIssues=locked_check["issues"])
        return {"baseVersion": scene.get("version", 0), "candidates": [], "diagnostics": diagnostics}
    original_requirements = evaluate_layout_requirements(scene)
    diagnostics["requirements"] = original_requirements
    diagnostics["functionalRelations"] = evaluate_bedside_groups(scene, scene)
    locked_ids = {item["id"] for item in scene["items"] if item.get("locked")}
    blocked_requirements = [check for check in original_requirements["unsatisfied"]
                            if ((check["itemId"] in locked_ids and (check["kind"] != "bedside" or check.get("targetId") in locked_ids)) or not (
                                check.get("targetId") in {item["id"] for item in scene["items"]} if check["kind"] == "bedside" else
                                matching_wall_segments(scene["room"], {"wall": check.get("requestedWall")}) if check["kind"] == "near_wall"
                                else matching_windows(scene["room"], check)))]
    if blocked_requirements:
        diagnostics["message"] = "未找到同时满足明确要求的布局：" + "；".join(check["message"] for check in blocked_requirements)
        if any(check["itemId"] in locked_ids for check in blocked_requirements):
            diagnostics["message"] += "相关家具已锁定，请先解锁或调整要求。"
        return {"baseVersion": scene.get("version", 0), "candidates": [], "diagnostics": diagnostics}
    if mode == "model" and not _available(status):
        diagnostics["message"] = "尚无可用训练模型。模型模式不会使用规则冒充模型结果；可选择规则模式。"
        return {"baseVersion": scene.get("version", 0), "candidates": [], "diagnostics": diagnostics}

    def accept(proposed, actual_method):
        if proposed is None:
            return False
        assert_invariants(scene, proposed)
        check = validate_scene(proposed)
        if not check["valid"]:
            rejected["geometry"] += 1
            return False
        requirements = evaluate_layout_requirements(proposed)
        if not requirements["satisfied"]:
            rejected["requirements"] += 1
            diagnostics["lastUnsatisfiedRequirements"] = requirements["unsatisfied"]
            return False
        relations = evaluate_bedside_groups(proposed, scene)
        if not relations["satisfied"]:
            rejected["functionalRelations"] += 1
            diagnostics["lastUnsatisfiedFunctionalRelations"] = relations["unsatisfied"]
            return False
        fingerprint = _fingerprint(proposed)
        if fingerprint in fingerprints:
            return False
        fingerprints.add(fingerprint)
        quality = layout_quality(proposed)
        preferences = preference_penalty(proposed, scene)
        # A candidate must first pass hard geometry checks. This soft score
        # ranks common arrangement cues; it is not a design-quality probability.
        total_penalty = preferences + quality["penalty"]
        score = round(100 / (1 + total_penalty), 2)
        candidates.append({"id": uuid.uuid4().hex[:12], "scene": proposed, "validation": check, "score": score, "mode": actual_method, "summary": f"{len(proposed['items'])}件家具全部保留，{sum(i.get('locked', False) for i in proposed['items'])}件保持锁定；通过占地与入口近似检查。"})
        candidates[-1]["quality"] = {
            "penalty": round(quality["penalty"], 4),
            "components": quality["components"],
            "preferencePenalty": round(preferences, 4),
        }
        candidates[-1]["requirements"] = requirements
        candidates[-1]["functionalRelations"] = relations
        if relations["warnings"]:
            candidates[-1]["summary"] += "锁定的床头柜仍有床头位置问题，未自动移动；请查看功能关系提示。"
        requested_ids = {preference["itemId"] for preference in scene.get("preferences", []) if preference.get("required")}
        if requested_ids:
            before = {item["id"]: item for item in scene["items"]}
            moved = [item for item in proposed["items"]
                     if math.dist((item["x"], item["z"]), (before[item["id"]]["x"], before[item["id"]]["z"])) > .02
                     or abs((item.get("rotation", 0) - before[item["id"]].get("rotation", 0) + 180) % 360 - 180) > 1]
            other_moved = [item for item in moved if item["id"] not in requested_ids]
            candidates[-1]["changes"] = {"movedItemIds": [item["id"] for item in moved],
                                          "otherMovedItemIds": [item["id"] for item in other_moved]}
            candidates[-1]["summary"] += "已逐项核验明确提出的空间要求。"
            if other_moved:
                candidates[-1]["summary"] += "为完成布置，同时调整了未锁定的" + "、".join(item["label"] for item in other_moved) + "。"
            else:
                candidates[-1]["summary"] += "未提及的家具保持原位。"
        return True

    if mode in ("rules", "hybrid") and not has_spatial_requirements:
        diagnostics["functionalTemplates"] = {"attempts": 0, "accepted": 0}
        for _ in range(min(count + 2, 5)):
            if len(candidates) >= count or not budget.take():
                break
            diagnostics["attempts"] += 1
            diagnostics["functionalTemplates"]["attempts"] += 1
            proposed = functional_template(scene, rng, budget)
            if accept(proposed, "rules"):
                diagnostics["functionalTemplates"]["accepted"] += 1
                candidates[-1]["provenance"] = {"initialization": "functional_group_template",
                    "layoutNetwork": False, "geometricRepair": False, "functionalGroups": True}
                candidates[-1]["summary"] += "本次按床与床头柜、桌椅等功能组搜索摆放，使用规则模板，未运行布局网络。"

    if mode == "hybrid" and has_spatial_requirements:
        # The denoiser was trained on whole bedrooms, without window requests.
        # A local explicit edit must not first perturb unrelated furniture.
        diagnostics["explicitRequirementSearch"] = {"used": True, "layoutNetwork": False,
                                                     "reason": "明确空间要求使用优先保留未提及家具的约束搜索；未先运行全屋布局网络。"}
    if mode in ("model", "hybrid") and len(candidates) < count and _available(status) and not (mode == "hybrid" and has_spatial_requirements):
        module = importlib.import_module("roomwise.learning")
        for trial in range(min(count + 2, 5)):
            if not budget.take():
                break
            diagnostics["attempts"] += 1
            try:
                # Pure model experiments must not secretly receive a rule-built
                # layout. Only hybrid may use the search to initialise attempts.
                initialization = "user_scene"
                input_scene = deepcopy(scene)
                if trial > 0 and mode == "hybrid":
                    input_scene = rule_candidate(scene, rng, budget=budget)
                    initialization = "rules_search"
                elif trial > 0:
                    initialization = "jittered_user_scene"
                    for item in input_scene["items"]:
                        if not item.get("locked"):
                            item["x"] += rng.uniform(-.15, .15)
                            item["z"] += rng.uniform(-.15, .15)
                if input_scene is None:
                    continue
                refined = module.refine_scene(input_scene, iterations=3)
                proposed = _sanitize_model_output(scene, refined)
                diagnostics["modelProposals"] += 1
                accepted = accept(proposed, "model")
                if accepted:
                    diagnostics["rawModelAccepted"] += 1
                    candidates[-1]["provenance"] = {"initialization": initialization, "layoutNetwork": True, "geometricRepair": False}
                    if initialization == "rules_search":
                        candidates[-1]["summary"] += "模型以规则布局为初始化，此后未进行几何修复。"
                elif mode == "hybrid":
                    # Geometry repair remains an explicit algorithm stage, not
                    # a raw model success. Prefer changes near the ML proposal.
                    repaired = rule_candidate(proposed, rng, anchor_strength=2.5, budget=budget)
                    if accept(repaired, "hybrid"):
                        diagnostics["repairedModelAccepted"] += 1
                        changes = [math.hypot(a["x"] - b["x"], a["z"] - b["z"]) for a, b in zip(proposed["items"], repaired["items"])]
                        candidates[-1]["repair"] = {"totalPositionChangeMeters": round(sum(changes), 3), "method": "constrained_geometric_search"}
                        candidates[-1]["provenance"] = {"initialization": initialization, "layoutNetwork": True, "geometricRepair": True}
                        candidates[-1]["summary"] += "模型建议经过几何规则修复，并非模型独立通过。"
            except Exception as exc:
                rejected["model"] += 1
                diagnostics["modelError"] = f"{type(exc).__name__}: {str(exc)[:180]}"
            if len(candidates) >= count:
                break
    if mode in ("rules", "hybrid"):
        attempts = max(10, min(28, count * 8))
        for _ in range(attempts):
            if len(candidates) >= count or not budget.take():
                break
            diagnostics["attempts"] += 1
            proposed = rule_candidate(scene, rng, budget=budget)
            if proposed is None:
                rejected["placementFailed"] += 1
                continue
            if accept(proposed, "rules") and has_spatial_requirements:
                candidates[-1]["provenance"] = {"initialization": "user_scene", "layoutNetwork": False,
                                                 "geometricRepair": False, "constraintSearch": True}
                candidates[-1]["summary"] += "本次使用空间约束搜索，包含所需的桌椅成组处理，未运行布局网络。"
    if not candidates and mode != "model" and original_check["valid"]:
        accept(deepcopy(scene), "current")
    candidates.sort(key=lambda c: c["score"], reverse=True)
    if candidates:
        diagnostics["message"] = f"已找到{len(candidates)}个通过检查的候选；分数只表示定义的布局偏好，不代表设计质量概率。"
        if mode == "hybrid" and not _available(status):
            diagnostics["message"] += "当前模型不可用，本次使用规则搜索。"
        elif mode == "hybrid" and has_spatial_requirements:
            diagnostics["message"] += "为保留未提及家具，本次使用局部空间约束搜索，未运行布局网络。"
    else:
        diagnostics["message"] = "当前条件下未找到通过检查的布局。系统未删除家具、修改尺寸或移动锁定物品；可解锁部分位置或调整家具清单。"
        if any(preference.get("required") for preference in scene.get("preferences", [])):
            diagnostics["message"] = "当前搜索预算内未找到同时满足明确要求与占地、入口检查的布局。未返回违反靠墙、靠窗或朝向要求的替代方案；请检查目标位置空间、锁定家具，或调整要求。"
    diagnostics["elapsedSeconds"] = round(time.monotonic() - started, 3)
    diagnostics["searchBudgetExhausted"] = budget.exhausted
    if budget.exhausted:
        diagnostics["message"] += "已达到搜索预算；这不表示数学上不存在可行布局。"
    return {"baseVersion": scene.get("version", 0), "candidates": candidates[:count], "diagnostics": diagnostics}

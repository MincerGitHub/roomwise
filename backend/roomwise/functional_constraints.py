"""Declared furniture use spaces, with advisory defaults for unknown assets."""
from __future__ import annotations

from copy import deepcopy
from functools import lru_cache
import json
import math

from .geometry import footprint, room_polygon
from .schemas import FunctionalProfile
from .storage import runtime_directory

BEDS = {"double_bed", "single_bed", "kids_bed"}
TABLES = {"desk", "table", "dressing_table"}
SEATS = {"chair", "armchair", "stool", "dressing_chair"}


@lru_cache(maxsize=4)
def _registry(path, stamp):
    try:
        records = json.loads(path.read_text(encoding="utf-8"))
        return {key: {**value, "profile": FunctionalProfile.model_validate(value["profile"]).model_dump(exclude_none=True)}
                for key, value in records.items()}
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return {}


def functional_profile(item):
    snapshot = item.get("furnitureSnapshot") or {}
    declared = item.get("functionalProfile", snapshot.get("functionalProfile"))
    if declared is not None:
        return {key: value for key, value in declared.items() if value is not None}
    # Local compatibility metadata lets old saved snapshots use the declared
    # profiles without rewriting scenes. Never depend on experiment directories.
    if not item.get("furnitureAssetId"):
        return {}
    path = runtime_directory() / "furniture-functional-profiles.json"
    if not path.exists():
        return {}
    record = _registry(path, path.stat().st_mtime_ns).get(item["furnitureAssetId"], {})
    if record.get("assetUrl") != item.get("assetUrl") or any(
            abs(float(record.get(key, -1)) - item[key]) > 1e-6 for key in ("width", "depth", "height")):
        return {}
    return record.get("profile", {})


def decorate_asset(asset):
    """Expose local legacy metadata in new instances and the furniture editor."""
    item = {**asset["snapshot"], "furnitureAssetId": asset["id"], "assetUrl": asset["assetUrl"]}
    profile = functional_profile(item)
    if profile and "functionalProfile" not in asset["snapshot"]:
        asset["snapshot"]["functionalProfile"] = deepcopy(profile)
        asset["properties"]["functionalProfile"] = deepcopy(profile)
    return asset


def local_position(anchor, x, z):
    angle = math.radians(anchor.get("rotation", 0))
    return (anchor["x"] + math.cos(angle) * x + math.sin(angle) * z,
            anchor["z"] - math.sin(angle) * x + math.cos(angle) * z)


def front_sign(item):
    return -1 if (item.get("furnitureSnapshot") or {}).get("frontDirection") == "negative_z" else 1


def front_rotation(item):
    return (item.get("rotation", 0) + (180 if front_sign(item) < 0 else 0)) % 360


def _relative(anchor, other):
    angle = math.radians(front_rotation(anchor))
    x, z = other["x"] - anchor["x"], other["z"] - anchor["z"]
    return math.cos(angle) * x - math.sin(angle) * z, math.sin(angle) * x + math.cos(angle) * z


def _seat_capacity(table):
    profile = functional_profile(table)
    if profile.get("seatCapacity") is not None:
        return int(profile["seatCapacity"])
    snapshot = table.get("furnitureSnapshot") or {}
    parameters = snapshot.get("parameters") or table.get("parameters") or {}
    if isinstance(parameters, dict) and parameters.get("seatCount") is not None:
        return int(parameters["seatCount"])
    return 1 if table.get("category") in {"desk", "dressing_table"} else 4


def _minimum_cost_maximum_assignment(seat_ids, table_ids, capacities, costs):
    """Min-cost maximum bipartite assignment with table seat capacities."""
    if not seat_ids or not table_ids:
        return []
    slots = [table_id for table_id in table_ids for _ in range(capacities.get(table_id, 0))]
    if not slots:
        return []
    row_count, real_columns = len(seat_ids), len(slots)
    column_count = real_columns + row_count  # one unmatched dummy per seat
    forbidden, unmatched = 10**15, 10**12
    matrix = [[costs.get((seat_id, slots[column]), forbidden) if column < real_columns
               else unmatched + column - real_columns for column in range(column_count)]
              for seat_id in seat_ids]

    # Rectangular Hungarian algorithm; rows <= columns due to dummy slots.
    u, v = [0] * (row_count + 1), [0] * (column_count + 1)
    p, way = [0] * (column_count + 1), [0] * (column_count + 1)
    for row in range(1, row_count + 1):
        p[0] = row
        column0 = 0
        minimum = [forbidden] * (column_count + 1)
        used = [False] * (column_count + 1)
        while True:
            used[column0] = True
            row0 = p[column0]
            delta, column1 = forbidden, 0
            for column in range(1, column_count + 1):
                if used[column]:
                    continue
                reduced = matrix[row0 - 1][column - 1] - u[row0] - v[column]
                if reduced < minimum[column]:
                    minimum[column], way[column] = reduced, column0
                if minimum[column] < delta:
                    delta, column1 = minimum[column], column
            for column in range(column_count + 1):
                if used[column]:
                    u[p[column]] += delta
                    v[column] -= delta
                else:
                    minimum[column] -= delta
            column0 = column1
            if p[column0] == 0:
                break
        while True:
            column1 = way[column0]
            p[column0] = p[column1]
            column0 = column1
            if column0 == 0:
                break
    assigned = []
    for column in range(1, real_columns + 1):
        if p[column] and matrix[p[column] - 1][column - 1] < unmatched:
            assigned.append((seat_ids[p[column] - 1], slots[column - 1]))
    return assigned


def functional_pair_candidates(scene):
    """Return every compatible table/seat edge before final assignment."""
    items = scene["items"]
    candidates = []
    preferences = scene.get("preferences", [])
    profiles = {item["id"]: functional_profile(item) for item in items}
    for anchor_category, dependent_categories, kind in ((TABLES, SEATS, "work"), ({"sofa"}, {"coffee_table"}, "lounge")):
        anchors = [item for item in items if item["category"] in anchor_category]
        for dependent in (item for item in items if item["category"] in dependent_categories):
            requests = [pref for pref in preferences if pref["itemId"] == dependent["id"]]
            targets = {pref.get("targetId") for pref in requests if pref["kind"] in {"face_item", "vanity_seating"}}
            priority = 0 if targets else 2
            facing = [pref for pref in requests if pref["kind"] == "face_window"]
            if kind == "work" and not targets and facing:
                windows = scene.get("room", {}).get("windows", [])
                sole_window = windows[0]["id"] if len(windows) == 1 else None
                faced_windows = {pref.get("targetId") or sole_window for pref in facing}
                targets = {pref["itemId"] for pref in preferences if pref["kind"] == "near_window"
                           and pref["itemId"] in {anchor["id"] for anchor in anchors}
                           and (pref.get("targetId") or sole_window) in faced_windows
                           and (pref.get("targetId") or sole_window) is not None}
                if targets:
                    priority = 1
            for anchor in anchors:
                vanity = anchor["category"] == "dressing_table"
                preferred = "dressing_chair" if vanity else "chair"
                anchor_profile, seat_profile = profiles[anchor["id"]], profiles[dependent["id"]]
                surface, seat_height = anchor_profile.get("surfaceHeight"), seat_profile.get("seatHeight")
                if surface is not None and seat_height is not None:
                    difference = surface - seat_height
                    height_priority = -3 if .18 <= difference <= .42 else 4
                elif surface is not None or seat_height is not None:
                    height_priority = 1
                else:
                    height_priority = 2
                requested = not targets or anchor["id"] in targets
                is_window_match = not (facing and targets) or anchor["id"] in targets
                edge_priority = (0 if targets and requested else 3 if targets else priority,
                                 0 if is_window_match else 1, height_priority,
                                 dependent["category"] != preferred, not vanity,
                                 math.dist((anchor["x"], anchor["z"]), (dependent["x"], dependent["z"])),
                                 anchor["id"], dependent["id"])
                candidates.append((kind, anchor["id"], dependent["id"], edge_priority, requested))
    return candidates


def functional_pairs(scene):
    """Choose one global capacity-aware assignment from all compatible edges."""
    items = {item["id"]: item for item in scene["items"]}
    preferences = scene.get("preferences", [])
    pairs = []
    all_edges = functional_pair_candidates(scene)
    for kind, anchor_categories, seat_categories in (
            ("work", TABLES, SEATS), ("lounge", {"sofa"}, {"coffee_table"})):
        anchors = [item for item in scene["items"] if item["category"] in anchor_categories]
        seats = [item for item in scene["items"] if item["category"] in seat_categories
                 and not any(pref["itemId"] == item["id"] and pref["kind"] == "relative_position"
                             for pref in preferences)]
        if not anchors or not seats:
            continue
        capacities = {item["id"]: _seat_capacity(item) if kind == "work" else 1 for item in anchors}
        edge_by_ids = {(edge_kind, aid, bid): edge for edge_kind, aid, bid, *edge in all_edges
                       if edge_kind == kind}
        costs = {}
        table_order = {item["id"]: index for index, item in enumerate(anchors)}
        seat_order = {item["id"]: index for index, item in enumerate(seats)}
        for (edge_kind, aid, bid), (priority, requested) in edge_by_ids.items():
            if not requested:
                continue
            distance_milli = min(999_999, int(priority[5] * 1000))
            # Preference strength and dedicated seat type dominate distance.
            costs[(bid, aid)] = (priority[0] * 10**10 + priority[1] * 10**8
                                 + int(priority[2]) * 10**7 + int(priority[3]) * 10**6
                                 + int(priority[4]) * 10**5 + distance_milli * 100
                                 + table_order[aid] * max(1, len(seats)) + seat_order[bid])
        assignment = _minimum_cost_maximum_assignment(
            [item["id"] for item in seats], [item["id"] for item in anchors], capacities, costs)
        pairs.extend((kind, aid, bid) for bid, aid in assignment)
    return pairs


def evaluate_functional_spaces(scene, original=None):
    original = original or scene
    items = {item["id"]: item for item in scene["items"]}
    profiles = {key: functional_profile(item) for key, item in items.items()}
    polygons = {key: footprint(item) for key, item in items.items()}
    shell = room_polygon(scene["room"]).buffer(1e-6)
    checks, paired = [], set()

    def add(kind, ids, satisfied, message, required, metrics=None, **details):
        checks.append({"kind": kind, "itemId": ids[0], "itemIds": ids, "required": required,
                       "blocking": required, "satisfied": bool(satisfied), "source": "declared" if required else "default",
                       "message": message, "metrics": metrics or {}, **details})

    def zone(anchor, lx, lz, width, depth, ignore):
        x, z = local_position(anchor, lx, lz)
        polygon = footprint({**anchor, "x": x, "z": z, "width": width, "depth": depth})
        blockers = [key for key, item in items.items() if key not in ignore and item.get("supportId") not in ignore
                    and item["category"] != "rug" and item.get("y", 0) < 1.8
                    and polygon.intersection(polygons[key]).area > 1e-5]
        inside = shell.covers(polygon)
        return {"satisfied": inside and not blockers, "blockers": blockers, "insideRoom": inside}

    pairs = functional_pairs(original)
    assigned_counts = {}
    for kind, aid, _ in pairs:
        if kind == "work":
            assigned_counts[aid] = assigned_counts.get(aid, 0) + 1
    for kind, aid, bid in pairs:
        paired.update((aid, bid))
        if aid not in items or bid not in items:
            continue
        a, b = items[aid], items[bid]
        pa, pb = profiles[aid], profiles[bid]
        lateral, forward = _relative(a, b)
        gap = forward - a["depth"] / 2 - b["depth"] / 2
        declared = any(key != "note" for p in (pa, pb) for key in p)
        if kind == "work":
            assigned_count = assigned_counts.get(aid, 1)
            if a["category"] == "table" and assigned_count > 1:
                gap = abs(forward) - a["depth"] / 2 - b["depth"] / 2
                target_rotation = front_rotation(a) + (180 if forward >= 0 else 0)
                error = abs((front_rotation(b) - target_rotation + 180) % 360 - 180)
            else:
                error = abs((front_rotation(b) - front_rotation(a) - 180 + 180) % 360 - 180)
            lane = max(.22, min((a["width"] - b["width"]) / 2, a["width"] * .35)) if assigned_count > 1 else .22
            add("work_position", [aid, bid], .08-1e-6 <= gap <= .50+1e-6 and abs(lateral) <= lane+1e-6 and error <= 20,
                f"{a['label']}与{b['label']}：核对桌前间距、横向对齐和座椅朝向。", declared,
                {"gapMeters": gap, "lateralOffsetMeters": lateral, "allowedLateralMeters": lane,
                 "assignedSeats": assigned_count, "angleErrorDegrees": error})
            rear = pb.get("rearUseDepth", .55)
            area = zone(b, 0, -front_sign(b) * (b["depth"] / 2 + rear / 2), max(.55, b["width"]), rear, {aid, bid})
            add("chair_pullout", [bid, aid], area["satisfied"], f"{b['label']}后方需留出 {rear:.2f} 米后撤空间。",
                "rearUseDepth" in pb, {"depthMeters": rear}, zone=area)
            surface, seat = pa.get("surfaceHeight"), pb.get("seatHeight")
            if surface is not None and seat is not None:
                difference = surface - seat
                add("work_height", [aid, bid], .18-1e-6 <= difference <= .42+1e-6,
                    f"{a['label']}台面与{b['label']}座面高度差需为 0.18～0.42 米。", True,
                    {"surfaceHeightMeters": surface, "seatHeightMeters": seat, "heightDifferenceMeters": difference})
        else:
            add("sofa_coffee", [aid, bid], .30-1e-6 <= gap <= .65+1e-6 and abs(lateral) <= .30+1e-6,
                f"{b['label']}应位于{a['label']}前方，间距 0.30～0.65 米。", declared,
                {"gapMeters": gap, "lateralOffsetMeters": lateral})
            tvs = [item for item in original["items"] if item["category"] in {"tv_stand", "wall_tv"} and item["id"] in items]
            if tvs:
                original_anchor = next(item for item in original["items"] if item["id"] == aid)
                tv_id = min(tvs, key=lambda item: math.dist((item["x"], item["z"]), (original_anchor["x"], original_anchor["z"])))["id"]
                x, z = _relative(a, items[tv_id])
                angle = math.degrees(math.atan2(abs(x), z))
                add("sofa_tv", [aid, tv_id], angle <= 25, f"{a['label']}应朝向{items[tv_id]['label']}，偏差不超过 25°。",
                    declared, {"angleErrorDegrees": angle})

    for key, item in items.items():
        profile = profiles[key]
        if item["category"] in BEDS:
            depth = profile.get("bedsideAccess", .55)
            ignore = {key}
            length = min(1.2, item["depth"])
            # Bedside cabinets occupy the head end. Check access beside the
            # mattress towards the foot, without exempting actual obstacles.
            sides = [zone(item, sign * (item["width"] / 2 + depth / 2), item["depth"] / 2 - length / 2,
                          depth, length, ignore) for sign in (-1, 1)]
            add("bed_side_access", [key], any(side["satisfied"] for side in sides),
                f"{item['label']}至少一侧需留出 {depth:.2f} 米使用空间。", "bedsideAccess" in profile,
                {"depthMeters": depth}, sides=sides)
        default_front = {"bookshelf": .6, "shelf": .6}.get(item["category"])
        front = profile.get("frontUseDepth", default_front)
        if front is not None and key not in paired:
            area = zone(item, 0, front_sign(item) * (item["depth"] / 2 + front / 2), item["width"], front, {key})
            add("front_use", [key], area["satisfied"], f"{item['label']}正面需留出 {front:.2f} 米使用空间。",
                "frontUseDepth" in profile, {"depthMeters": front}, zone=area)
    unsatisfied = [check for check in checks if check["required"] and not check["satisfied"]]
    warnings = [check for check in checks if not check["required"] and not check["satisfied"]]
    return {"satisfied": not unsatisfied, "passed": sum(c["satisfied"] for c in checks), "total": len(checks),
            "checks": checks, "unsatisfied": unsatisfied, "warnings": warnings,
            "penalty": len(warnings) * .5,
            "note": "已声明参数用于验收；默认使用区为排序建议。未填写台面或座面高度时不以总高代替。"}


def repair_functional_spaces(scene, original, budget=None):
    """Bounded deterministic relation edits, followed by every existing check."""
    from .geometry import assert_invariants, validate_scene, evaluate_vanity_seating
    from .bedside_constraints import evaluate_bedside_groups
    from .window_constraints import evaluate_layout_requirements
    best = scene
    result = evaluate_functional_spaces(best, original)
    history = []
    protected = {p.get("targetId") for p in original.get("preferences", []) if p["kind"] == "relative_position"}
    for kind, aid, bid in functional_pairs(original):
        by_id = {item["id"]: item for item in best["items"]}
        anchor, child = by_id[aid], by_id[bid]
        failed = [c for c in result["unsatisfied"] if {aid, bid} <= set(c["itemIds"])]
        if not failed or child.get("locked") or bid in protected:
            continue
        gaps = (.45, .35, .55, .65, .30) if kind == "lounge" else (.12, .24, .35, .48)
        for gap in gaps:
            for offset in (0., -.15, .15):
                if budget is not None and not budget.take():
                    return best, result, history
                proposed = deepcopy(best)
                item = next(i for i in proposed["items"] if i["id"] == bid)
                item["x"], item["z"] = local_position(anchor, offset, front_sign(anchor) * (anchor["depth"] / 2 + child["depth"] / 2 + gap))
                item["rotation"] = (front_rotation(anchor) + (180 if kind == "work" else 0) - (180 if front_sign(child) < 0 else 0)) % 360
                assert_invariants(original, proposed)
                if not validate_scene(proposed)["valid"] or not evaluate_layout_requirements(proposed)["satisfied"]:
                    continue
                if not evaluate_bedside_groups(proposed, original)["satisfied"] or not evaluate_vanity_seating(proposed)["satisfied"]:
                    continue
                check = evaluate_functional_spaces(proposed, original)
                if (len(check["unsatisfied"]), len(check["warnings"])) < (len(result["unsatisfied"]), len(result["warnings"])):
                    history.append({"kind": kind, "itemId": bid, "gapMeters": gap, "lateralOffsetMeters": offset})
                    best, result = proposed, check
                    break
            else:
                continue
            break
    return best, result, history

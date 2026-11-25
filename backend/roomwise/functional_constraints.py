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
SEATS = {"chair", "stool", "dressing_chair"}


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
    path = runtime_directory() / "furniture-functional-profiles.json"
    if not item.get("furnitureAssetId") or not path.exists():
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


def functional_pairs(scene):
    """Bind by the input scene, so movement cannot silently change partners."""
    items = scene["items"]
    pairs, used = [], set()
    preferences = scene.get("preferences", [])
    for anchor_category, dependent_categories, kind in ((TABLES, SEATS, "work"), ({"sofa"}, {"coffee_table"}, "lounge")):
        anchors = [item for item in items if item["category"] in anchor_category]
        for dependent in sorted((item for item in items if item["category"] in dependent_categories), key=lambda item: item["id"]):
            if any(pref["itemId"] == dependent["id"] and pref["kind"] == "relative_position" for pref in preferences):
                continue
            targets = [pref.get("targetId") for pref in preferences if pref["itemId"] == dependent["id"]
                       and pref["kind"] in {"face_item", "vanity_seating"}]
            choices = [item for item in anchors if (kind, item["id"]) not in used and (not targets or item["id"] in targets)]
            if not choices:
                continue
            anchor = min(choices, key=lambda item: (math.dist((item["x"], item["z"]), (dependent["x"], dependent["z"])), item["id"]))
            used.add((kind, anchor["id"]))
            pairs.append((kind, anchor["id"], dependent["id"]))
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

    for kind, aid, bid in functional_pairs(original):
        if aid not in items or bid not in items:
            continue
        a, b = items[aid], items[bid]
        pa, pb = profiles[aid], profiles[bid]
        paired.update((aid, bid))
        lateral, forward = _relative(a, b)
        gap = forward - a["depth"] / 2 - b["depth"] / 2
        declared = any(key != "note" for p in (pa, pb) for key in p)
        if kind == "work":
            error = abs((front_rotation(b) - front_rotation(a) - 180 + 180) % 360 - 180)
            add("work_position", [aid, bid], .08-1e-6 <= gap <= .50+1e-6 and abs(lateral) <= .22+1e-6 and error <= 20,
                f"{a['label']}与{b['label']}：核对桌前间距、横向对齐和座椅朝向。", declared,
                {"gapMeters": gap, "lateralOffsetMeters": lateral, "angleErrorDegrees": error})
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

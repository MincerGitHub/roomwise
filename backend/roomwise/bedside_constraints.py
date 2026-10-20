"""Bed-head relationships in bed coordinates, independent of the camera.

Local -z is the headboard/pillow end. Right is local +x when standing at the
foot looking towards the head. These tolerances are product defaults.
"""
from __future__ import annotations

from copy import deepcopy
import math

from .geometry import footprint

BEDS = {"double_bed", "single_bed", "kids_bed"}
MAX_SIDE_GAP = .35
HEAD_TOLERANCE = .30


def bedside_assignments(scene, original=None):
    items = {item["id"]: item for item in scene["items"]}
    reference = {item["id"]: item for item in (original or scene)["items"]}
    beds = [item for item in items.values() if item["category"] in BEDS]
    assignments = {}
    for stand in items.values():
        if stand["category"] != "nightstand":
            continue
        preferences = [preference for preference in scene.get("preferences", [])
                       if preference["kind"] == "bedside" and preference["itemId"] == stand["id"]]
        preference = next((p for p in preferences if p.get("required")), preferences[0] if preferences else None)
        if preference:
            assignments[stand["id"]] = {**preference, "side": preference.get("side") or "either", "source": "explicit"}
        elif beds:
            before = reference.get(stand["id"], stand)
            bed = min(beds, key=lambda bed: math.dist((before["x"], before["z"]),
                      (reference.get(bed["id"], bed)["x"], reference.get(bed["id"], bed)["z"])))
            assignments[stand["id"]] = {"kind": "bedside", "itemId": stand["id"], "targetId": bed["id"],
                                       "side": "either", "required": False, "source": "default"}
    return assignments


def evaluate_bedside_preference(item, bed, preference):
    base = {"kind": "bedside", "itemId": preference["itemId"], "targetId": preference.get("targetId"),
            "side": preference.get("side") or "either", "required": bool(preference.get("required")),
            "satisfied": False, "metrics": {}, "message": ""}
    if not item or not bed or item.get("category") != "nightstand" or bed.get("category") not in BEDS:
        return {**base, "message": "床头柜关系没有找到对应的床头柜或床。"}
    angle = math.radians(bed.get("rotation", 0))
    c, s = math.cos(angle), math.sin(angle)
    dx, dz = item["x"] - bed["x"], item["z"] - bed["z"]
    local_x, local_z = c * dx - s * dz, s * dx + c * dz
    relative = math.radians(item.get("rotation", 0) - bed.get("rotation", 0))
    span_x = abs(math.cos(relative)) * item["width"] + abs(math.sin(relative)) * item["depth"]
    span_z = abs(math.sin(relative)) * item["width"] + abs(math.cos(relative)) * item["depth"]
    gap = abs(local_x) - bed["width"] / 2 - span_x / 2
    desired_z = -bed["depth"] / 2 + span_z / 2 + .08
    head_error = abs(local_z - desired_z)
    side = "right" if local_x >= 0 else "left"
    overlap = footprint(item).intersection(footprint(bed)).area
    satisfied = (-1e-6 <= gap <= MAX_SIDE_GAP + 1e-6 and head_error <= HEAD_TOLERANCE + 1e-6
                 and overlap <= 1e-6 and (base["side"] == "either" or side == base["side"]))
    return {**base, "satisfied": satisfied, "actualSide": side,
            "metrics": {"sideGapMeters": round(gap, 4), "maxSideGapMeters": MAX_SIDE_GAP,
                        "headOffsetErrorMeters": round(head_error, 4), "maxHeadOffsetErrorMeters": HEAD_TOLERANCE,
                        "bedLocalXMeters": round(local_x, 4), "bedLocalZMeters": round(local_z, 4),
                        "desiredBedLocalZMeters": round(desired_z, 4), "overlapAreaM2": round(overlap, 6)},
            "message": f"{item['label']}在{bed['label']}的{'右' if side == 'right' else '左'}侧，距床侧 {gap:.2f} 米、床头对齐偏差 {head_error:.2f} 米；" + ("满足床头侧关系。" if satisfied else "未满足床头侧位置要求。")}


def evaluate_bedside_groups(scene, original=None):
    items = {item["id"]: item for item in scene["items"]}
    checks = []
    for stand_id, preference in bedside_assignments(scene, original).items():
        stand, bed = items[stand_id], items.get(preference["targetId"])
        check = evaluate_bedside_preference(stand, bed, preference)
        preference_satisfied = check["satisfied"]
        if not preference.get("required") and preference.get("side") not in (None, "either"):
            check = evaluate_bedside_preference(stand, bed, {**preference, "side": "either"})
            check["side"] = preference["side"]
            check["preferenceSatisfied"] = preference_satisfied
            if check["satisfied"] and not preference_satisfied:
                check["message"] += "指定左右侧是尽量偏好，当前选择了另一侧床头位置。"
        check["source"] = preference["source"]
        check["blocking"] = bool(preference.get("required")) or not stand.get("locked")
        if stand.get("locked") and not check["satisfied"]:
            check["message"] += "床头柜已锁定，未自动移动；请解锁或调整床的位置。"
        checks.append(check)
    # Two tables should not both claim the same head side of one bed. Extra
    # owned stands are retained; failure is reported instead of deleting one.
    occupied = {}
    for check in checks:
        if check["satisfied"]:
            slot = check["targetId"], check["actualSide"]
            if slot in occupied:
                check["satisfied"] = False
                check["message"] += "同一床侧已有另一件床头柜。"
            else:
                occupied[slot] = check["itemId"]
    unsatisfied = [check for check in checks if not check["satisfied"] and check["blocking"]]
    warnings = [check for check in checks if not check["satisfied"] and not check["blocking"]]
    return {"satisfied": not unsatisfied, "checks": checks, "unsatisfied": unsatisfied, "warnings": warnings,
            "note": "床头为床的局部 -z 端；左右不随相机变化。距离阈值是产品默认值，不是人体工学标准。"}


def bedside_placements(stand, bed, side="either"):
    if stand.get("locked"):
        yield deepcopy(stand)
        return
    sides = (-1, 1) if side in (None, "either") else (-1,) if side == "left" else (1,)
    angle = math.radians(bed.get("rotation", 0))
    c, s = math.cos(angle), math.sin(angle)
    for sign in sides:
        for gap in (.08, .16, .28):
            for along in (.08, .18, -.08):
                local_x = sign * (bed["width"] / 2 + stand["width"] / 2 + gap)
                local_z = -bed["depth"] / 2 + stand["depth"] / 2 + along
                yield {**stand, "x": bed["x"] + c * local_x + s * local_z,
                       "z": bed["z"] - s * local_x + c * local_z, "rotation": bed.get("rotation", 0)}


def bed_placements_for_locked_stands(bed, stands):
    """Try fitting a movable bed to existing fixed head tables before warning."""
    if bed.get("locked") or not stands:
        return
    first = stands[0]
    for rotation in dict.fromkeys([bed.get("rotation", 0), 0., 90., 180., 270.]):
        angle = math.radians(rotation)
        c, s = math.cos(angle), math.sin(angle)
        relative = math.radians(first.get("rotation", 0) - rotation)
        span_x = abs(math.cos(relative)) * first["width"] + abs(math.sin(relative)) * first["depth"]
        span_z = abs(math.sin(relative)) * first["width"] + abs(math.cos(relative)) * first["depth"]
        for side in (-1, 1):
            for gap in (.08, .20):
                x = side * (bed["width"] / 2 + span_x / 2 + gap)
                z = -bed["depth"] / 2 + span_z / 2 + .08
                yield {**bed, "x": first["x"] - c * x - s * z,
                       "z": first["z"] + s * x - c * z, "rotation": rotation}

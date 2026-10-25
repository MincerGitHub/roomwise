"""Furniture-to-furniture facing constraints in the room's x/z plane."""
from __future__ import annotations

import math


MAX_FACING_ITEM_ANGLE = 20.0
EPSILON = 1e-9
BED_CATEGORIES = {"double_bed", "single_bed", "kids_bed"}


def front_sign(item: dict) -> float:
    """Convert the item's local front convention to its world-facing sign."""
    snapshot = item.get("furnitureSnapshot") or {}
    if item.get("category") in BED_CATEGORIES or snapshot.get("frontDirection") == "negative_z":
        return -1.0
    return 1.0


def facing_rotation(item: dict, target: dict) -> float:
    """Yaw that points an item's declared front toward the target centre."""
    dx = float(target["x"]) - float(item["x"])
    dz = float(target["z"]) - float(item["z"])
    if math.hypot(dx, dz) <= EPSILON:
        return float(item.get("rotation", 0)) % 360
    target_heading = math.degrees(math.atan2(dx, dz))
    if front_sign(item) < 0:
        target_heading -= 180.0
    return target_heading % 360


def evaluate_facing_preference(item: dict | None, target: dict | None, preference: dict):
    base = {"kind": "face_item", "itemId": preference.get("itemId"),
            "targetId": preference.get("targetId"), "required": bool(preference.get("required")),
            "satisfied": False, "message": "", "metrics": {}}
    if not item or not target:
        return {**base, "message": "朝向要求引用的家具不存在。"}
    dx, dz = float(target["x"]) - float(item["x"]), float(target["z"]) - float(item["z"])
    distance = math.hypot(dx, dz)
    if distance <= EPSILON:
        return {**base, "message": "两件家具中心重合，无法判断朝向目标。"}
    angle = math.radians(float(item.get("rotation", 0)))
    sign = front_sign(item)
    dot = sign * (math.sin(angle) * dx + math.cos(angle) * dz) / distance
    error = math.degrees(math.acos(max(-1.0, min(1.0, dot))))
    satisfied = error <= MAX_FACING_ITEM_ANGLE + 1e-6
    return {**base, "satisfied": satisfied,
            "message": f"{item['label']}正面需朝向{target['label']}，方向偏差 {error:.1f}°；"
                       + ("当前满足。" if satisfied else "当前未满足。"),
            "metrics": {"distanceMeters": round(distance, 3),
                        "angularErrorDegrees": round(error, 3),
                        "maxAngleDegrees": MAX_FACING_ITEM_ANGLE}}

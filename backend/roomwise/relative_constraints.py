"""Position one furniture footprint in a target's local front/back/left/right."""
from __future__ import annotations

import math

from .geometry import footprint


MIN_RELATIVE_GAP = .025
MAX_RELATIVE_GAP = 1.5
MIN_LATERAL_OVERLAP = .12


def target_axes(target):
    angle = math.radians(float(target.get("rotation", 0)))
    facing_sign = -1 if (target.get("category") in {"double_bed", "single_bed", "kids_bed"}
                         or (target.get("furnitureSnapshot") or {}).get("frontDirection") == "negative_z") else 1
    forward = (math.sin(angle) * facing_sign, math.cos(angle) * facing_sign)
    right = (math.cos(angle), -math.sin(angle))
    return forward, right


def _interval(item, axis):
    coordinates = list(footprint(item).exterior.coords)
    values = [x * axis[0] + z * axis[1] for x, z in coordinates]
    return min(values), max(values)


def _axes(target, direction):
    forward, right = target_axes(target)
    if direction in ("front", "back"):
        return forward, right, direction == "front"
    if direction in ("left", "right"):
        return right, forward, direction == "right"
    return None


def evaluate_relative_position(item, target, preference):
    """Check target-local side, non-overlap gap and meaningful lateral overlap."""
    direction = preference.get("direction")
    base = {"kind": "relative_position", "itemId": preference.get("itemId"),
            "targetId": preference.get("targetId"), "direction": direction,
            "required": bool(preference.get("required")), "satisfied": False,
            "message": "", "metrics": {}}
    if not item or not target:
        return {**base, "message": "相对位置要求引用的家具不存在。"}
    axes = _axes(target, direction)
    if axes is None:
        return {**base, "message": "相对位置方向无效，请使用前、后、左或右。"}
    axis, lateral, positive = axes
    target_min, target_max = _interval(target, axis)
    item_min, item_max = _interval(item, axis)
    target_side_min, target_side_max = _interval(target, lateral)
    item_side_min, item_side_max = _interval(item, lateral)
    gap = item_min - target_max if positive else target_min - item_max
    overlap = min(target_side_max, item_side_max) - max(target_side_min, item_side_min)
    required_overlap = min(MIN_LATERAL_OVERLAP,
                           min(target_side_max - target_side_min,
                               item_side_max - item_side_min) * .25)
    satisfied = (MIN_RELATIVE_GAP - 1e-6 <= gap <= MAX_RELATIVE_GAP + 1e-6
                 and overlap >= required_overlap - 1e-6)
    names = {"front": "前方", "back": "后方", "left": "左侧", "right": "右侧"}
    return {**base, "satisfied": satisfied,
            "message": f"{item['label']}需位于{target['label']}{names[direction]}，并与目标家具保持可用间距。"
                       + ("当前满足。" if satisfied else "当前未满足。"),
            "metrics": {"gapMeters": round(gap, 3), "maxGapMeters": MAX_RELATIVE_GAP,
                        "lateralOverlapMeters": round(overlap, 3),
                        "minLateralOverlapMeters": round(required_overlap, 3)}}


def relative_position_placements(item, target, preference):
    """Yield deterministic target-local poses; keep target and item sizes intact."""
    axes = _axes(target, preference.get("direction"))
    if axes is None or item.get("locked"):
        return
    axis, lateral, positive = axes
    target_min, target_max = _interval(target, axis)
    target_side_min, target_side_max = _interval(target, lateral)
    target_side_center = (target_side_min + target_side_max) / 2
    target_angle = float(target.get("rotation", 0))
    rotations = list(dict.fromkeys((float(item.get("rotation", 0)) % 360,
                                   target_angle % 360, (target_angle + 90) % 360,
                                   (target_angle + 180) % 360, (target_angle + 270) % 360)))
    offsets = (0., -.12, .12, -.24, .24, -.36, .36)
    for rotation in rotations:
        oriented = {**item, "x": 0., "z": 0., "rotation": rotation}
        item_min, item_max = _interval(oriented, axis)
        side_min, side_max = _interval(oriented, lateral)
        half_axis_span = (item_max - item_min) / 2
        side_half_span = (side_max - side_min) / 2
        side_center_offset = (side_min + side_max) / 2
        target_side_span = target_side_max - target_side_min
        required_overlap = min(MIN_LATERAL_OVERLAP,
                               min(target_side_span, side_max - side_min) * .25)
        # Centre alignment alone can put a large subject behind a wall-mounted
        # target.  Include both edge alignments that retain the required
        # lateral projection overlap.  For example, a bed beside a north-wall
        # wardrobe needs to extend toward the room, rather than share its
        # centre along the wall.
        edge_overlap = required_overlap + .02
        side_centers = list(dict.fromkeys((
            target_side_center + offset for offset in offsets
        )))
        side_centers.extend((
            target_side_min + edge_overlap - side_half_span,
            target_side_max - edge_overlap + side_half_span,
        ))
        for gap in (.08, .18, .30, .45, .65, .90, 1.15, 1.40):
            axis_center = target_max + gap + half_axis_span if positive else target_min - gap - half_axis_span
            for side_center in side_centers:
                # Convert target-local projections back into room x/z axes.
                center_axis = axis_center - (item_min + item_max) / 2
                center_side = side_center - side_center_offset
                x = axis[0] * center_axis + lateral[0] * center_side
                z = axis[1] * center_axis + lateral[1] * center_side
                candidate = {**item, "x": x, "z": z, "rotation": rotation}
                if evaluate_relative_position(candidate, target, preference)["satisfied"]:
                    yield candidate

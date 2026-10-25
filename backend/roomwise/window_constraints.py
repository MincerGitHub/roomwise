"""Explicit, independently checked spatial requests, in metres and degrees.

The thresholds are product defaults, not architectural or ergonomic standards.
Furniture forward is local +z, as used by the browser's procedural chair mesh.
"""
from __future__ import annotations

import math

from shapely.geometry import LineString

from .geometry import footprint, opening_center, room_polygon
from .relative_constraints import MAX_RELATIVE_GAP, MIN_LATERAL_OVERLAP, MIN_RELATIVE_GAP, evaluate_relative_position
from .facing_constraints import evaluate_facing_preference


MAX_WINDOW_GAP = .60
WINDOW_PROJECTION_TOLERANCE = .15
MAX_FACING_ANGLE = 20.0
MAX_WALL_GAP = .15
MAX_WALL_BACK_ANGLE = 20.0
EXPLICIT_SPATIAL_KINDS = ("near_window", "face_window", "face_item", "near_wall", "bedside", "vanity_seating", "relative_position")


def matching_wall_segments(room, preference):
    """Actual exterior segments, with an inward normal for each segment.

    Named walls refer to the room's outer coordinate bounds. A sloping side
    is never silently substituted for an absent north/east/etc wall.
    """
    polygon = room_polygon(room)
    coordinates = list(polygon.exterior.coords)
    ccw = polygon.exterior.is_ccw
    segments = []
    for index, (start, end) in enumerate(zip(coordinates, coordinates[1:])):
        dx, dz = end[0] - start[0], end[1] - start[1]
        length = math.hypot(dx, dz)
        if length < 1e-8:
            continue
        wall = None
        for name, axis, value in (("north", 1, room["depth"]), ("south", 1, 0),
                                  ("east", 0, room["width"]), ("west", 0, 0)):
            if abs(start[axis] - value) < 1e-6 and abs(end[axis] - value) < 1e-6:
                wall = name
                break
        if preference.get("wall") and preference["wall"] != wall:
            continue
        inward = (-dz / length, dx / length) if ccw else (dz / length, -dx / length)
        segments.append({"wall": wall or f"boundary-{index}", "segment": LineString([start, end]),
                         "start": start, "end": end, "length": length,
                         "tangent": (dx / length, dz / length), "inward": inward})
    return segments


def evaluate_wall_preference(item, room, preference):
    """Check footprint gap plus furniture-back orientation against real walls."""
    base = {"kind": "near_wall", "itemId": preference["itemId"], "targetId": None,
            "wall": preference.get("wall"), "requestedWall": preference.get("wall"),
            "required": bool(preference.get("required")),
            "satisfied": False, "message": "", "metrics": {}}
    if not item:
        return {**base, "message": "靠墙要求对应的家具不存在。"}
    walls = matching_wall_segments(room, preference)
    if not walls:
        return {**base, "message": "房间实际轮廓中没有指定方向的墙段，请选择其他墙或使用最近墙。"}
    angle = math.radians(item.get("rotation", 0))
    forward = math.sin(angle), math.cos(angle)
    tangent = math.cos(angle), -math.sin(angle)
    back_center = item["x"] - forward[0] * item["depth"] / 2, item["z"] - forward[1] * item["depth"] / 2
    back = LineString([(back_center[0] - tangent[0] * item["width"] / 2,
                        back_center[1] - tangent[1] * item["width"] / 2),
                       (back_center[0] + tangent[0] * item["width"] / 2,
                        back_center[1] + tangent[1] * item["width"] / 2)])
    shape = footprint(item)
    checks = []
    for wall in walls:
        distance = float(shape.distance(wall["segment"]))
        back_distance = float(back.distance(wall["segment"]))
        dot = forward[0] * wall["inward"][0] + forward[1] * wall["inward"][1]
        angular_error = math.degrees(math.acos(max(-1., min(1., dot))))
        satisfied = distance <= MAX_WALL_GAP + 1e-6 and back_distance <= MAX_WALL_GAP + 1e-6 and angular_error <= MAX_WALL_BACK_ANGLE + 1e-6
        metrics = {"distanceMeters": round(distance, 4), "maxDistanceMeters": MAX_WALL_GAP,
                   "backDistanceMeters": round(back_distance, 4),
                   "backAlignmentErrorDegrees": round(angular_error, 3), "maxBackAngleDegrees": MAX_WALL_BACK_ANGLE}
        checks.append({**base, "wall": wall["wall"], "satisfied": satisfied, "metrics": metrics,
                       "message": f"{item['label']}距墙 {distance:.2f} 米，背面朝墙偏差 {angular_error:.1f}°；" + ("满足靠墙要求。" if satisfied else "未满足靠墙距离或背面朝墙要求。")})
    return min(checks, key=lambda check: (not check["satisfied"],
                check["metrics"]["distanceMeters"] + check["metrics"]["backAlignmentErrorDegrees"] / 180))


def evaluate_spatial_preference(item, room, preference):
    if preference["kind"] == "near_wall":
        return evaluate_wall_preference(item, room, preference)
    return evaluate_window_preference(item, room, preference)


def matching_windows(room, preference):
    return [window for window in room.get("windows", [])
            if not preference.get("targetId") or window["id"] == preference["targetId"]]


def window_segment(room, window):
    start, end = window["offset"], window["offset"] + window["width"]
    return LineString({
        "north": [(start, room["depth"]), (end, room["depth"])],
        "south": [(start, 0), (end, 0)],
        "east": [(room["width"], start), (room["width"], end)],
        "west": [(0, start), (0, end)],
    }[window["wall"]])


def evaluate_window_preference(item, room, preference):
    """Return one check; unbound requests may select any matching window."""
    base = {"kind": preference["kind"], "itemId": preference["itemId"],
            "targetId": preference.get("targetId"), "required": bool(preference.get("required")),
            "satisfied": False, "message": "", "metrics": {}}
    windows = matching_windows(room, preference)
    if not item:
        return {**base, "message": "要求对应的家具不存在。"}
    if not windows:
        return {**base, "message": "房间没有可用的目标窗户，请先添加或选择窗户。"}
    checks = []
    for window in windows:
        if preference["kind"] == "near_window":
            shape = footprint(item)
            distance = float(shape.distance(window_segment(room, window)))
            low_x, low_z, high_x, high_z = shape.bounds
            low, high = (low_x, high_x) if window["wall"] in ("north", "south") else (low_z, high_z)
            overlap = min(high, window["offset"] + window["width"]) - max(low, window["offset"])
            satisfied = distance <= MAX_WINDOW_GAP + 1e-6 and overlap >= -WINDOW_PROJECTION_TOLERANCE - 1e-6
            checks.append({**base, "targetId": window["id"], "satisfied": satisfied,
                           "message": f"{item['label']}距目标窗边 {distance:.2f} 米，" + ("满足靠窗要求。" if satisfied else "未满足靠窗距离或窗前投影要求。"),
                           "metrics": {"distanceMeters": round(distance, 4), "maxDistanceMeters": MAX_WINDOW_GAP,
                                       "projectionOverlapMeters": round(overlap, 4),
                                       "projectionToleranceMeters": WINDOW_PROJECTION_TOLERANCE}})
        elif preference["kind"] == "face_window":
            wx, wz = opening_center(room, window)
            dx, dz = wx - item["x"], wz - item["z"]
            length = math.hypot(dx, dz)
            angle = math.radians(item.get("rotation", 0))
            dot = (math.sin(angle) * dx + math.cos(angle) * dz) / length if length > 1e-9 else -1
            error = math.degrees(math.acos(max(-1., min(1., dot))))
            satisfied = error <= MAX_FACING_ANGLE + 1e-6
            checks.append({**base, "targetId": window["id"], "satisfied": satisfied,
                           "message": f"{item['label']}正面与窗户方向相差 {error:.1f}°，" + ("满足面朝窗户要求。" if satisfied else "超过允许的 20°。"),
                           "metrics": {"angularErrorDegrees": round(error, 3), "maxAngleDegrees": MAX_FACING_ANGLE}})
    if not checks:
        return {**base, "satisfied": True, "message": "移动偏好参与排序，不设置额外窗户限制。"}
    return min(checks, key=lambda check: (not check["satisfied"],
               check["metrics"].get("distanceMeters", check["metrics"].get("angularErrorDegrees", 0))))


def evaluate_layout_requirements(scene):
    """Geometry and explicit requests are separate; only required checks gate acceptance."""
    items = {item["id"]: item for item in scene["items"]}
    from .bedside_constraints import evaluate_bedside_preference
    from .geometry import evaluate_vanity_preference
    checks = [(evaluate_bedside_preference(items.get(pref["itemId"]), items.get(pref.get("targetId")), pref)
               if pref["kind"] == "bedside" else
               evaluate_vanity_preference(items.get(pref["itemId"]), items.get(pref.get("targetId")), pref)
               if pref["kind"] == "vanity_seating" else
               evaluate_relative_position(items.get(pref["itemId"]), items.get(pref.get("targetId")), pref)
               if pref["kind"] == "relative_position" else
               evaluate_facing_preference(items.get(pref["itemId"]), items.get(pref.get("targetId")), pref)
               if pref["kind"] == "face_item" else
               evaluate_spatial_preference(items.get(pref["itemId"]), scene["room"], pref))
              for pref in scene.get("preferences", []) if pref["kind"] in EXPLICIT_SPATIAL_KINDS]
    unsatisfied = [check for check in checks if check["required"] and not check["satisfied"]]
    return {"satisfied": not unsatisfied, "checks": checks, "unsatisfied": unsatisfied,
            "thresholds": {"maxWindowGapMeters": MAX_WINDOW_GAP,
                           "windowProjectionToleranceMeters": WINDOW_PROJECTION_TOLERANCE,
                           "maxFacingAngleDegrees": MAX_FACING_ANGLE,
                           "maxWallGapMeters": MAX_WALL_GAP, "maxWallBackAngleDegrees": MAX_WALL_BACK_ANGLE,
                           "relativePositionMinGapMeters": MIN_RELATIVE_GAP,
                           "relativePositionMaxGapMeters": MAX_RELATIVE_GAP,
                           "relativePositionMinLateralOverlapMeters": MIN_LATERAL_OVERLAP,
                           "maxFurnitureFacingAngleDegrees": 20.0},
            "note": "靠墙、靠窗和朝向阈值是本产品的可调整默认值，不是建筑或人体工学标准；靠墙默认家具背面朝墙、正面朝室内。"}

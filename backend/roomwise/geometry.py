"""Independent 2D footprint and approximate accessibility checks.

Units are metres. Yaw follows Three.js: positive angle turns local +x to -z.
This is a stated engineering check, not a building-code compliance certificate.
"""
from __future__ import annotations

from collections import deque
import math

import numpy as np
from shapely.affinity import rotate, translate
from shapely.geometry import Point, Polygon, box
from shapely.ops import unary_union


SEAT_CATEGORIES = {"chair", "dressing_chair", "stool"}
TABLE_CATEGORIES = {"desk", "table", "dressing_table", "coffee_table"}
ACCESS_CATEGORIES = {"double_bed", "single_bed", "kids_bed", "wardrobe", "desk", "table", "sofa", "armchair", "cabinet", "bookshelf", "children_cabinet", "dressing_table", "tv_stand"}
EPSILON = 1e-6


def room_polygon(room: dict) -> Polygon:
    return Polygon(room["polygon"]) if room.get("polygon") else box(0, 0, room["width"], room["depth"])


def footprint(item: dict) -> Polygon:
    shape = box(-item["width"] / 2, -item["depth"] / 2, item["width"] / 2, item["depth"] / 2)
    shape = rotate(shape, -float(item.get("rotation", 0)), origin=(0, 0))
    return translate(shape, xoff=item.get("x", 0), yoff=item.get("z", 0))


def door_zone(room: dict):
    door = room.get("door")
    if not door:
        return None
    o, w, c = door["offset"], door["width"], door.get("clearance", .9)
    if door["wall"] == "south":
        return box(o, 0, o + w, c)
    if door["wall"] == "north":
        return box(o, room["depth"] - c, o + w, room["depth"])
    if door["wall"] == "west":
        return box(0, o, c, o + w)
    return box(room["width"] - c, o, room["width"], o + w)


def opening_center(room: dict, opening: dict):
    p = opening["offset"] + opening["width"] / 2
    return {
        "south": (p, 0), "north": (p, room["depth"]),
        "west": (0, p), "east": (room["width"], p),
    }[opening["wall"]]


def overlap_kind(a: dict, b: dict, area: float) -> str:
    """Rugs are floor layers; allow limited seat tucking below a taller table.

    This is a conservative category rule, not a claim of detailed mesh safety.
    A full chair hidden under a table remains a collision.
    """
    if a["category"] == "rug" or b["category"] == "rug":
        return "floor_layer"
    if a["category"] in SEAT_CATEGORIES and b["category"] in TABLE_CATEGORIES:
        seat, table = a, b
    elif b["category"] in SEAT_CATEGORIES and a["category"] in TABLE_CATEGORIES:
        seat, table = b, a
    else:
        return "collision"
    fraction = area / (seat["width"] * seat["depth"])
    if fraction <= .4 + EPSILON and table["height"] >= .6:
        return "seat_tuck"
    return "collision"


def placement_errors(item: dict, room: dict, placed: list[dict], gap: float = 0):
    """Fast hard checks used by the generator; excludes accessibility."""
    fp = footprint(item)
    if not room_polygon(room).buffer(EPSILON).covers(fp):
        return True
    if item.get("height", 0) > room["height"] + EPSILON:
        return True
    zone = door_zone(room)
    if zone is not None and item["category"] != "rug" and fp.intersection(zone).area > EPSILON:
        return True
    for other in placed:
        other_fp = footprint(other)
        inter = fp.intersection(other_fp).area
        if inter > EPSILON and overlap_kind(item, other, inter) == "collision":
            return True
        if gap and item["category"] != "rug" and other["category"] != "rug" and inter <= EPSILON and fp.distance(other_fp) < gap:
            return True
    return False


def accessibility(scene: dict, step: float = .18, radius: float = .15):
    """Flood-fill a walking-centre grid from the door to furniture perimeter.

    The .30m body diameter is a configurable prototype approximation. No claim
    is made that this proves regulatory, wheelchair or cupboard-door clearance.
    """
    room = scene["room"]
    door = room.get("door")
    if not door:
        return {"evaluated": False, "reachable": None, "unreachableItemIds": [], "gridStep": step, "walkingDiameter": 2 * radius, "reason": "未设置门，无法检查入口可达性"}
    shell = room_polygon(room).buffer(-radius)
    solids = [footprint(i).buffer(radius, join_style=2) for i in scene["items"] if i["category"] != "rug"]
    obstacle = unary_union(solids) if solids else Polygon()
    space = shell.difference(obstacle)
    minx, minz, maxx, maxz = room_polygon(room).bounds
    # Adaptive cap avoids a huge 100m room exhausting memory.
    step = max(step, max(maxx - minx, maxz - minz) / 180)
    xs = np.arange(minx + step / 2, maxx, step)
    zs = np.arange(minz + step / 2, maxz, step)
    free = np.zeros((len(xs), len(zs)), dtype=bool)
    for ix, x in enumerate(xs):
        for iz, z in enumerate(zs):
            free[ix, iz] = space.covers(Point(float(x), float(z)))
    zone = door_zone(room)
    start = []
    for ix, x in enumerate(xs):
        for iz, z in enumerate(zs):
            if free[ix, iz] and zone.covers(Point(float(x), float(z))):
                start.append((ix, iz))
    if not start:
        return {"evaluated": True, "reachable": False, "unreachableItemIds": [i["id"] for i in scene["items"] if i["category"] in ACCESS_CATEGORIES], "gridStep": step, "walkingDiameter": 2 * radius, "reason": "门内没有可用的步行网格"}
    # A single nearest-to-door seed avoids joining disconnected door-zone cells.
    dx, dz = opening_center(room, door)
    seed = min(start, key=lambda ij: (xs[ij[0]] - dx) ** 2 + (zs[ij[1]] - dz) ** 2)
    visited = np.zeros_like(free)
    visited[seed] = True
    queue = deque([seed])
    while queue:
        x, z = queue.popleft()
        for nx, nz in ((x - 1, z), (x + 1, z), (x, z - 1), (x, z + 1)):
            if 0 <= nx < len(xs) and 0 <= nz < len(zs) and free[nx, nz] and not visited[nx, nz]:
                visited[nx, nz] = True
                queue.append((nx, nz))
    indices = np.argwhere(visited)
    reach_points = [Point(float(xs[ix]), float(zs[iz])) for ix, iz in indices]
    unreachable = []
    for item in scene["items"]:
        if item["category"] not in ACCESS_CATEGORIES:
            continue
        shape = footprint(item)
        # Check a perimeter zone; precise fronts and drawer sweeps are an extension.
        if not any(.12 <= p.distance(shape) <= .55 for p in reach_points):
            unreachable.append(item["id"])
    return {"evaluated": True, "reachable": not unreachable, "unreachableItemIds": unreachable, "gridStep": round(float(step), 4), "walkingDiameter": 2 * radius, "reachableCells": len(indices), "freeCells": int(free.sum()), "reason": "基于家具外围和入口的近似步行检查，未模拟柜门开启"}


def validate_scene(scene: dict, check_access: bool = True):
    room = scene["room"]
    shell = room_polygon(room)
    items = scene["items"]
    issues = []
    polygons = {i["id"]: footprint(i) for i in items}
    collisions = out = door_count = 0
    zone = door_zone(room)
    for item in items:
        fp = polygons[item["id"]]
        if not shell.buffer(EPSILON).covers(fp):
            out += 1
            issues.append({"type": "out_of_bounds", "severity": "error", "itemIds": [item["id"]], "message": f"{item['label']}超出房间轮廓"})
        if item["height"] > room["height"] + EPSILON:
            issues.append({"type": "height", "severity": "error", "itemIds": [item["id"]], "message": f"{item['label']}高度超过层高"})
        if zone is not None and item["category"] != "rug" and fp.intersection(zone).area > EPSILON:
            door_count += 1
            issues.append({"type": "door", "severity": "error", "itemIds": [item["id"]], "message": f"{item['label']}占用了门内预留区域"})
    for index, a in enumerate(items):
        for b in items[index + 1:]:
            area = polygons[a["id"]].intersection(polygons[b["id"]]).area
            if area <= EPSILON:
                continue
            kind = overlap_kind(a, b, area)
            if kind == "floor_layer":
                continue
            if kind == "seat_tuck":
                issues.append({"type": "seat_tuck", "severity": "info", "itemIds": [a["id"], b["id"]], "message": f"{a['label']}与{b['label']}有局部桌椅交叠，须确认实际高度及使用空间"})
                continue
            collisions += 1
            issues.append({"type": "collision", "severity": "error", "itemIds": [a["id"], b["id"]], "message": f"{a['label']}与{b['label']}的占地范围相交", "overlapArea": round(area, 4)})
    access = accessibility(scene) if check_access and not out and not door_count else {"evaluated": False, "reachable": None, "unreachableItemIds": [], "reason": "需先处理越界或门口冲突"}
    if access.get("evaluated") and access.get("reachable") is False:
        issues.append({"type": "unreachable", "severity": "error", "itemIds": access["unreachableItemIds"], "message": "部分家具外围无法从入口沿近似步行网格到达"})
    if not room.get("door"):
        issues.append({"type": "missing_door", "severity": "warning", "itemIds": [], "message": "未设置门，仅检查占地；无法确认入口可达性"})
    free_area = max(0., shell.area - unary_union([polygons[i["id"]] for i in items if i["category"] != "rug"]).intersection(shell).area) if items else shell.area
    return {
        "valid": not any(i["severity"] == "error" for i in issues),
        "issues": issues,
        "metrics": {"collisions": collisions, "outOfBounds": out, "doorConflicts": door_count, "reachable": access.get("reachable"), "checkedItems": len(items), "roomArea": round(shell.area, 3), "freeArea": round(free_area, 3), "accessibility": access},
        "limitations": ["以确认后的二维占地和高度检查，未使用精细家具网格", "局部桌椅交叠与地毯按类别例外处理", "通行检查为工程近似，不能代表建筑规范验收"],
    }


def _axis_deviation_degrees(rotation: float) -> float:
    """Distance from the nearest 0/90-degree orientation (0..45 degrees)."""
    angle = float(rotation) % 90.0
    return min(angle, 90.0 - angle)


def _room_has_cardinal_axes(room: dict) -> bool:
    """Do not assume 0/90-degree furniture angles in irregular floor plans."""
    polygon = room.get("polygon")
    if not polygon:
        return True
    points = [(float(point[0]), float(point[1])) for point in polygon]
    if len(points) > 1 and math.dist(points[0], points[-1]) < 1e-5:
        points.pop()
    if len(points) != 4:
        return False
    for index, point in enumerate(points):
        following = points[(index + 1) % len(points)]
        dx, dz = abs(following[0] - point[0]), abs(following[1] - point[1])
        if min(dx, dz) > 1e-4:
            return False
    return True


def layout_quality(scene: dict) -> dict:
    """Return a small, explainable soft score for a valid furniture layout.

    This is deliberately a preference heuristic, not a claim that a layout is
    beautiful or professionally designed.  Hard safety checks remain in
    :func:`validate_scene`; this function only ranks candidates that already
    passed those checks.  The terms favour common bedroom/living-room practice:
    large pieces sit near a wall, furniture is aligned to the room axes, seats
    stay close to their table/desk, and narrow gaps are avoided.  Locked items
    are included because their positions are part of the room context, but
    their constant contribution cannot make another candidate move them.
    """
    room = scene["room"]
    shell = room_polygon(room)
    diag = max(math.hypot(room["width"], room["depth"]), 1e-6)
    cardinal_room = _room_has_cardinal_axes(room)
    items = [i for i in scene.get("items", []) if i.get("category") != "rug"]
    details = {
        "wallAnchoring": 0.0,
        "axisAlignment": 0.0,
        "functionalGrouping": 0.0,
        "clearance": 0.0,
        "openCenter": 0.0,
        "rugPlacement": 0.0,
        "backAlignment": 0.0,
        "seatFacing": 0.0,
        "bedsidePlacement": 0.0,
    }

    # These pieces normally benefit from an adjacent wall.  Beds get a little
    # more room because a headboard need not touch the wall exactly.
    wall_categories = {
        "double_bed", "single_bed", "kids_bed", "wardrobe", "desk", "sofa",
        "bookshelf", "cabinet", "children_cabinet", "dressing_table", "tv_stand",
    }
    for item in items:
        fp = footprint(item)
        if item.get("category") in wall_categories:
            target = .38 if "bed" in item["category"] else .24
            distance = fp.distance(shell.boundary)
            details["wallAnchoring"] += max(0.0, distance - target) / diag * 1.5
            # A piece far from every wall is also more likely to have a
            # visually awkward diagonal orientation in a rectangular room.
            if cardinal_room and distance <= .8:
                details["axisAlignment"] += _axis_deviation_degrees(item.get("rotation", 0)) / 45.0 * .22
            # A side or front touching the wall is not equivalent to a
            # headboard/cabinet back touching it. Score actual segment normals.
            from .window_constraints import evaluate_wall_preference

            back = evaluate_wall_preference(item, room, {"kind": "near_wall", "itemId": item["id"], "required": False})
            metrics = back.get("metrics", {})
            details["backAlignment"] += max(0., metrics.get("backDistanceMeters", diag)-.18) / diag * .8
            details["backAlignment"] += metrics.get("backAlignmentErrorDegrees", 180) / 180 * .4

    # A table/desk and its seat should read as one group.  A nightstand should
    # sit beside a bed.  We only score relationships when both sides exist;
    # the system must not punish a room for not owning a particular item.
    tables = [i for i in items if i.get("category") in TABLE_CATEGORIES]
    beds = [i for i in items if "bed" in i.get("category", "")]
    nightstands = [i for i in items if i.get("category") == "nightstand"]
    partners = {
        "chair": {"desk", "table"},
        "dressing_chair": {"dressing_table"},
        "stool": {"desk", "table", "dressing_table", "coffee_table"},
    }
    for seat in items:
        partner_categories = partners.get(seat.get("category"), set())
        seat_tables = [table for table in tables if table.get("category") in partner_categories]
        if not seat_tables:
            continue
        table = min(seat_tables, key=lambda candidate: footprint(seat).distance(footprint(candidate)))
        distance = footprint(seat).distance(footprint(table))
        # A seat belongs in front of its matching work surface, close enough
        # to use but with a small pull-out gap. Keep its centre near the
        # tabletop centreline instead of accepting any nearby position.
        details["functionalGrouping"] += max(0.0, distance - .18) / diag * 4.0
        if seat.get("category") in {"chair", "dressing_chair"}:
            dx, dz = seat["x"] - table["x"], seat["z"] - table["z"]
            angle = math.radians(float(table.get("rotation", 0)))
            local_x = math.cos(angle) * dx - math.sin(angle) * dz
            local_z = math.sin(angle) * dx + math.cos(angle) * dz
            details["functionalGrouping"] += max(0.0, abs(local_x) - .10) / diag * 3.0
            if local_z < 0:
                details["functionalGrouping"] += min(.4, abs(local_z) / diag)
            tx, tz = table["x"] - seat["x"], table["z"] - seat["z"]
            length = math.hypot(tx, tz)
            if length > 1e-6:
                rotation = math.radians(float(seat.get("rotation", 0)))
                dot = (math.sin(rotation)*tx + math.cos(rotation)*tz) / length
                details["seatFacing"] += 1.0 * (1-max(-1.,min(1.,dot))) / 2
    from .bedside_constraints import bedside_assignments
    bedside_links = bedside_assignments(scene)
    for stand in nightstands:
        if not beds:
            continue
        linked_id = bedside_links.get(stand["id"], {}).get("targetId")
        bed = next((candidate for candidate in beds if candidate["id"] == linked_id), None) or min(beds, key=lambda candidate: footprint(stand).distance(footprint(candidate)))
        distance = footprint(stand).distance(footprint(bed))
        details["functionalGrouping"] += max(0.0, distance - .45) / diag * 1.6
        # Prefer a nightstand next to the long side of the bed instead of at
        # its foot. Transform the centre offset into the bed's local axes.
        angle = math.radians(float(bed.get("rotation", 0)))
        dx, dz = stand["x"] - bed["x"], stand["z"] - bed["z"]
        local_x = math.cos(angle) * dx - math.sin(angle) * dz
        local_z = math.sin(angle) * dx + math.cos(angle) * dz
        side_extent = bed["width"] / 2 + stand["width"] / 2 + .45
        side_alignment = bed["depth"] * .32 + stand["depth"] * .35
        details["functionalGrouping"] += max(0.0, abs(local_x) - side_extent) / diag * .8
        details["functionalGrouping"] += max(0.0, abs(local_z) - side_alignment) / diag * 1.2
        desired_z = -bed["depth"]/2 + stand["depth"]/2 + .08
        details["bedsidePlacement"] += max(0., abs(local_z-desired_z)-.25) / diag * 1.8

    # Hard collision checks already reject overlap.  This soft term discourages
    # a barely passable .03m gap that looks like furniture has been stacked.
    for index, first in enumerate(items):
        first_fp = footprint(first)
        for second in items[index + 1:]:
            second_fp = footprint(second)
            if first_fp.intersection(second_fp).area > EPSILON:
                # A permitted partial chair tuck is intentional and should not
                # be scored as an ugly gap.
                if overlap_kind(first, second, first_fp.intersection(second_fp).area) == "seat_tuck":
                    continue
                continue
            gap = first_fp.distance(second_fp)
            details["clearance"] += max(0.0, .12 - gap) / .12 * .18

    # Keep the centre visually available when a large item happens to cover it.
    # A coffee table/rug is intentionally excluded because it commonly belongs
    # in the middle of a room.
    center = shell.centroid
    centre_zone = center.buffer(min(room["width"], room["depth"]) * .12).intersection(shell)
    centre_blockers = {"double_bed", "single_bed", "kids_bed", "wardrobe", "desk", "sofa", "cabinet", "bookshelf"}
    occupied_centre = sum(footprint(item).intersection(centre_zone).area
                          for item in items if item.get("category") in centre_blockers)
    if centre_zone.area > EPSILON:
        details["openCenter"] = .45 * min(1.0, occupied_centre / centre_zone.area)

    # Rugs are floor layers.  If present, place them under/near furniture so
    # they do not appear as an unrelated island at the edge of the room.
    rugs = [i for i in scene.get("items", []) if i.get("category") == "rug"]
    all_non_rugs = items
    for rug in rugs:
        if all_non_rugs:
            closest = min(footprint(rug).distance(footprint(item)) for item in all_non_rugs)
            details["rugPlacement"] += max(0.0, closest - .45) / diag * .5

    # Round components for a stable API/debug display, while retaining enough
    # precision for deterministic sorting of candidates.
    penalty = sum(details.values())
    return {"penalty": float(penalty), "components": {k: round(v, 4) for k, v in details.items()}}


def assert_invariants(original: dict, proposed: dict):
    """Reject any omission, identity/size/metadata change or lock violation."""
    originals = {i["id"]: i for i in original["items"]}
    proposals = {i["id"]: i for i in proposed["items"]}
    if len(proposed["items"]) != len(original["items"]) or originals.keys() != proposals.keys():
        raise ValueError("布局不得增删或重复家具")
    if original["room"] != proposed["room"]:
        raise ValueError("布局不得修改房间结构")
    for item_id, item in originals.items():
        candidate = proposals[item_id]
        for key in item.keys():
            if key not in ("x", "z", "rotation") and item.get(key) != candidate.get(key):
                raise ValueError(f"家具 {item_id} 的 {key} 不得改变")
        if item.get("locked") and any(item.get(key, 0) != candidate.get(key, 0) for key in ("x", "z", "rotation")):
            raise ValueError(f"锁定家具 {item_id} 被移动")


def preference_penalty(scene: dict, original: dict):
    by_id = {i["id"]: i for i in scene["items"]}
    old = {i["id"]: i for i in original["items"]}
    room = scene["room"]
    diag = math.hypot(room["width"], room["depth"])
    cost = 0.
    for pref in scene.get("preferences", []):
        item = by_id.get(pref["itemId"])
        if item is None:
            continue
        if pref["kind"] == "min_move":
            prior = old[item["id"]]
            cost += 2 * math.hypot(item["x"] - prior["x"], item["z"] - prior["z"]) / diag
        elif pref["kind"] == "near_window":
            windows = [w for w in room.get("windows", []) if not pref.get("targetId") or w["id"] == pref["targetId"]]
            if windows:
                distances = [math.dist((item["x"], item["z"]), opening_center(room, w)) for w in windows]
                cost += min(distances) / diag
        elif pref["kind"] == "bedside":
            from .bedside_constraints import evaluate_bedside_preference
            check = evaluate_bedside_preference(item, by_id.get(pref.get("targetId")), pref)
            metrics = check.get("metrics", {})
            cost += metrics.get("headOffsetErrorMeters", diag) / diag
            if not check["satisfied"]:
                cost += .4
        elif pref["kind"] in ("near_wall", "face_window"):
            from .window_constraints import evaluate_spatial_preference

            check = evaluate_spatial_preference(item, room, pref)
            metrics = check.get("metrics", {})
            if pref["kind"] == "near_wall":
                cost += 3 * metrics.get("distanceMeters", diag) / diag
                cost += metrics.get("backAlignmentErrorDegrees", 180) / 90
            else:
                cost += metrics.get("angularErrorDegrees", 180) / 90
    return cost

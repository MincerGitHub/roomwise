"""Conservative flat-top support rules, in metres, independent of rendering."""
from math import cos, radians, sin

SURFACE_CATEGORIES = {"desk", "table", "coffee_table", "nightstand", "tv_stand", "cabinet", "children_cabinet"}
EDGE_MARGIN = .03
EPSILON = 1e-5
WALL_APPLIANCES = {"wall_tv", "air_conditioner"}


def elevation(item):
    return float(item.get("y", 0))


def top(item):
    return elevation(item) + item["height"]


def is_surface(item):
    return item["category"] in SURFACE_CATEGORIES and not item.get("supportId") and elevation(item) == 0 and item["height"] <= 1.5


def fits_surface(item, target):
    if item["category"] not in {"storage_box", "laptop"} or item["height"] > .6 or not is_surface(target):
        return False
    angle, parent = radians(item.get("rotation", 0)), radians(target.get("rotation", 0))
    for sx, sz in ((-1, -1), (-1, 1), (1, -1), (1, 1)):
        x = item["x"] + cos(angle) * sx * item["width"] / 2 + sin(angle) * sz * item["depth"] / 2 - target["x"]
        z = item["z"] - sin(angle) * sx * item["width"] / 2 + cos(angle) * sz * item["depth"] / 2 - target["z"]
        local_x, local_z = cos(parent) * x - sin(parent) * z, sin(parent) * x + cos(parent) * z
        if abs(local_x) > target["width"] / 2 - EDGE_MARGIN + EPSILON or abs(local_z) > target["depth"] / 2 - EDGE_MARGIN + EPSILON:
            return False
    return True


def support_errors(scene):
    items = {item["id"]: item for item in scene["items"]}
    errors = []
    for item in items.values():
        if item["category"] in WALL_APPLIANCES:
            errors.extend(wall_mount_errors(item, scene["room"]))
            continue
        target = items.get(item.get("supportId"))
        if not item.get("supportId") and elevation(item) <= EPSILON:
            continue
        if not target or target is item or not fits_surface(item, target) or abs(elevation(item) - top(target)) > EPSILON:
            errors.append({"type": "support", "severity": "error", "itemIds": [item["id"]] + ([target["id"]] if target else []),
                           "message": f"{item['label']}没有完整落在可承托的平整台面内，或离地高度与台面不一致"})
    return errors


def wall_mount_errors(item, room):
    """Check mounting height, back contact and front facing the room."""
    from shapely.geometry import LineString
    from .window_constraints import matching_wall_segments

    angle = radians(item.get("rotation", 0))
    forward = sin(angle), cos(angle)
    back = item["x"] - forward[0]*item["depth"]/2, item["z"] - forward[1]*item["depth"]/2
    tangent = cos(angle), -sin(angle)
    edge = LineString([(back[0]+sign*tangent[0]*item["width"]/2,back[1]+sign*tangent[1]*item["width"]/2) for sign in (-1,1)])
    attached = any(segment["segment"].buffer(.08).covers(edge) and
                   sum(forward[i]*segment["inward"][i] for i in (0,1)) >= cos(radians(20))
                   for segment in matching_wall_segments(room, {}))
    if not item.get("supportId") and elevation(item) > 0 and top(item) <= room["height"]+EPSILON and attached:
        return []
    return [{"type":"wall_mount","severity":"error","itemIds":[item["id"]],
             "message":f"{item['label']}需设置离地安装高度，背面贴合墙内侧且正面朝向房间，顶部不得超过层高。"}]


def separated_vertically(a, b):
    return top(a) <= elevation(b) + EPSILON or top(b) <= elevation(a) + EPSILON


def reconcile_supports(result, original):
    """Carry boxes through exact host edits and detach invalid attachments."""
    before = {item["id"]: item for item in original["items"]}
    after = {item["id"]: item for item in result["items"]}
    for item in result["items"]:
        if not item.get("supportId"):
            continue
        old = before.get(item["id"])
        target, prior = after.get(item["supportId"]), before.get(item["supportId"])
        if target and prior and old and old.get("supportId") == item["supportId"] and all(old.get(key, 0) == item.get(key, 0) for key in ("x", "z", "rotation")):
            if any(target.get(key, 0) != prior.get(key, 0) for key in ("x", "z", "rotation", "height")):
                if item.get("locked"):
                    raise ValueError(f"{item['label']}已锁定，请先解锁再调整承托家具。")
                angle, turn = radians(prior.get("rotation", 0)), radians(target.get("rotation", 0))
                dx, dz = old["x"] - prior["x"], old["z"] - prior["z"]
                lx, lz = cos(angle) * dx - sin(angle) * dz, sin(angle) * dx + cos(angle) * dz
                item.update(x=target["x"] + cos(turn) * lx + sin(turn) * lz,
                            z=target["z"] - sin(turn) * lx + cos(turn) * lz,
                            rotation=(old.get("rotation", 0) + target.get("rotation", 0) - prior.get("rotation", 0)) % 360)
        if target and fits_surface(item, target) and target["height"] + item["height"] <= result["room"]["height"] + EPSILON:
            item["y"] = target["height"]
            continue
        if item.get("locked"):
            raise ValueError(f"{item['label']}已锁定，请先解锁再更改承托家具。")
        item.update(y=0, supportId=None)
    return result

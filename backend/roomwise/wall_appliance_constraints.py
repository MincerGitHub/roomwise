"""Conservative 3D use-space checks for wall appliances; all lengths in metres."""
import math

from .supports import WALL_APPLIANCES, elevation, top

EPS = 1e-6


def window_heights(window, room):
    """Match the displayed window; legacy scenes use the existing 1.05m height."""
    height = window.get("height")
    if height is None:
        height = min(1.05, max(.1, room["height"] - window["sillHeight"] - .1))
    bottom = max(0., min(window["sillHeight"], max(0., room["height"] - height - .1))) if window.get("height") is None else window["sillHeight"]
    return bottom, bottom + height


def window_conflicts(item, room):
    from .geometry import footprint
    if item["category"] not in WALL_APPLIANCES:
        return []
    shape = footprint(item)
    minx, minz, maxx, maxz = shape.bounds
    conflicts = []
    for window in room.get("windows", []):
        bottom, upper = window_heights(window, room)
        if min(top(item), upper) - max(elevation(item), bottom) <= EPS:
            continue
        wall = window["wall"]
        horizontal = wall in ("north", "south")
        plane = room["depth"] if wall == "north" else room["width"] if wall == "east" else 0.
        normal_min, normal_max = (minz, maxz) if horizontal else (minx, maxx)
        if normal_min > plane + .08 or normal_max < plane - .08:
            continue
        lo, hi = (minx, maxx) if horizontal else (minz, maxz)
        overlap = min(hi, window["offset"] + window["width"]) - max(lo, window["offset"])
        if overlap > EPS:
            conflicts.append({"windowId": window["id"], "overlapWidthMeters": overlap,
                              "windowBottomMeters": bottom, "windowTopMeters": upper})
    return conflicts


def _axes(item):
    angle = math.radians(item.get("rotation", 0))
    return (math.sin(angle), math.cos(angle)), (math.cos(angle), -math.sin(angle))


def _front_zone(item, width, depth):
    from .geometry import footprint
    forward, _ = _axes(item)
    distance = item["depth"] / 2 + depth / 2
    return footprint({**item, "width": width, "depth": depth,
                      "x": item["x"] + forward[0]*distance, "z": item["z"] + forward[1]*distance})


def clearance_checks(item, items, room):
    from .geometry import footprint
    if item["category"] not in WALL_APPLIANCES:
        return []
    if item["category"] == "wall_tv":
        zones = [("tv_front_clearance", _front_zone(item, item["width"], .6), elevation(item), top(item),
                  "屏幕前0.60米净空", False)]
    else:
        zones = [
            ("ac_airflow", _front_zone(item, item["width"]+.1, .6), max(0.,elevation(item)-.3), top(item),
             "前方0.60米及出风口下方0.30米使用区", False),
            ("ac_service", _front_zone(item, item["width"]+.2, .6), max(0.,elevation(item)-.15), top(item)+.15,
             "前方0.60米检修区", False),
            ("ac_return", footprint(item).buffer(.03,join_style=2), top(item), top(item)+.1,
             "顶部0.10米回风净空", True),
        ]
    checks = []
    for kind, shape, low, high, label, ceiling in zones:
        blockers = [other for other in items if other["id"] != item["id"] and other["category"] != "rug"
                    and min(high,top(other))-max(low,elevation(other)) > EPS
                    and shape.intersection(footprint(other)).area > EPS]
        ceiling_blocked = ceiling and high > room["height"] + EPS
        names = "、".join(other["label"] for other in blockers)
        checks.append({"kind":kind,"itemId":item["id"],"itemIds":[item["id"],*[other["id"] for other in blockers]],
                       "required":True,"blocking":True,"source":"default","satisfied":not blockers and not ceiling_blocked,
                       "message":f"{item['label']}{label}" + (f"被{names}占用。" if blockers else "不足，距离天花板太近。" if ceiling_blocked else "通过。"),
                       "metrics":{"clearanceBottomMeters":low,"clearanceTopMeters":high},
                       "blockers":[other["id"] for other in blockers]})
    return checks


def _ray_hits_box(start, end, item):
    """Segment vs rotated whole-item box; ignore seats/endpoints separately."""
    forward, tangent = _axes(item)
    def local(point):
        x, z = point[0]-item["x"], point[2]-item["z"]
        return (x*tangent[0]+z*tangent[1], point[1]-elevation(item), x*forward[0]+z*forward[1])
    a, b = local(start), local(end)
    enter, leave = EPS, 1-EPS
    for origin, target, lo, hi in zip(a,b,(-item["width"]/2,0.,-item["depth"]/2),(item["width"]/2,item["height"],item["depth"]/2)):
        change = target-origin
        if abs(change) < 1e-9:
            if origin <= lo+EPS or origin >= hi-EPS:
                return False
            continue
        first, last = sorted(((lo-origin)/change,(hi-origin)/change))
        enter, leave = max(enter,first), min(leave,last)
        if leave-enter <= EPS:
            return False
    return True


def television_checks(tv, scene):
    from .functional_constraints import functional_profile
    by_id = {item["id"]:item for item in scene["items"]}
    requested = {pref["itemId"] for pref in scene.get("preferences",[])
                 if pref["kind"] == "face_item" and pref.get("targetId") == tv["id"]}
    seats = [by_id[key] for key in sorted(requested) if key in by_id and by_id[key]["category"] in {"sofa","armchair","chair","stool"}]
    if not requested:
        seats = [item for item in scene["items"] if item["category"] in {"sofa","armchair"}]
    if not seats:
        return [{"kind":"tv_viewpoint","itemId":tv["id"],"itemIds":[tv["id"]],"required":False,"blocking":False,
                 "source":"default","satisfied":False,"message":f"{tv['label']}未设置观看座位，暂未检查观看视线；已检查屏幕前净空。","metrics":{}}]
    forward, tangent = _axes(tv)
    checks = []
    for seat in seats:
        profile = functional_profile(seat)
        ratio = (seat.get("furnitureSnapshot") or {}).get("parameters",{}).get("seatHeightRatio")
        seat_height = profile.get("seatHeight",seat["height"]*ratio if ratio is not None else .45)
        eye = (seat["x"],elevation(seat)+seat_height+.65,seat["z"])
        in_front = (eye[0]-tv["x"])*forward[0]+(eye[2]-tv["z"])*forward[1] > tv["depth"]/2+EPS
        blockers = set(); blocked = 0
        samples = []
        for across in (-.42,-.21,0.,.21,.42):
            for up in (.1,.5,.9):
                samples.append((tv["x"]+tangent[0]*tv["width"]*across+forward[0]*tv["depth"]/2,
                                elevation(tv)+tv["height"]*up,
                                tv["z"]+tangent[1]*tv["width"]*across+forward[1]*tv["depth"]/2))
        for point in samples:
            hit = [other["id"] for other in scene["items"] if other["id"] not in {tv["id"],seat["id"]}
                   and other["category"] != "rug" and _ray_hits_box(eye,point,other)]
            if hit:blocked += 1;blockers.update(hit)
        names = "、".join(by_id[key]["label"] for key in sorted(blockers))
        message = (f"从{seat['label']}观看{tv['label']}：" +
                   ("座位位于屏幕背面，请调整安装或观看位置。" if not in_front else
                    f"视线被{names}遮挡（{blocked}/{len(samples)}条采样视线）。" if blocked else "采样观看视线通过。"))
        checks.append({"kind":"tv_visibility","itemId":tv["id"],"itemIds":[tv["id"],seat["id"],*sorted(blockers)],
                       "required":True,"blocking":True,"source":"default","satisfied":in_front and not blocked,"message":message,
                       "metrics":{"blockedRays":blocked,"sampledRays":len(samples),"eyeHeightMeters":eye[1]},"blockers":sorted(blockers)})
    return checks


def evaluate_wall_appliances(scene):
    checks = []
    for item in scene["items"]:
        if item["category"] not in WALL_APPLIANCES:
            continue
        conflicts = window_conflicts(item,scene["room"])
        checks.append({"kind":"wall_window_overlap","itemId":item["id"],"itemIds":[item["id"]],"required":True,
                       "blocking":True,"source":"default","satisfied":not conflicts,
                       "message":f"{item['label']}与窗户"+("重叠，请移到窗框外。" if conflicts else "无重叠。"),
                       "metrics":{"overlappingWindows":len(conflicts)},"windows":conflicts})
        checks.extend(clearance_checks(item,scene["items"],scene["room"]))
        if item["category"] == "wall_tv":
            checks.extend(television_checks(item,scene))
    failed = [check for check in checks if check["required"] and not check["satisfied"]]
    warnings = [check for check in checks if not check["required"] and not check["satisfied"]]
    issues = [{"type":check["kind"],"severity":"error","itemIds":check["itemIds"],"message":check["message"]} for check in failed]
    issues += [{"type":check["kind"],"severity":"warning","itemIds":check["itemIds"],"message":check["message"]} for check in warnings]
    return {"satisfied":not failed,"passed":sum(check["satisfied"] for check in checks),"total":len(checks),
            "checks":checks,"unsatisfied":failed,"warnings":warnings,"issues":issues,
            "note":"视线按座位眼高与屏幕15条射线、家具整体外框近似；空调净空为工程默认值，未模拟真实气流或安装规范。"}


def placement_blocked(item, room, placed):
    """Cheap symmetric screen/AC use-zone checks while searching floor items."""
    if window_conflicts(item,room):
        return True
    items = [*placed,item]
    appliances = [item] if item["category"] in WALL_APPLIANCES else []
    appliances += [other for other in placed if other["category"] in WALL_APPLIANCES]
    return any(not check["satisfied"] for appliance in appliances for check in clearance_checks(appliance,items,room))

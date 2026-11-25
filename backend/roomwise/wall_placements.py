"""Bounded wall-only candidates for unlocked appliances, preserving elevation."""
from copy import deepcopy
import math
from shapely.geometry import Point

from .supports import elevation, wall_mount_errors
from .wall_appliance_constraints import window_conflicts


def appliance_placements(item, room, preference=None):
    from .window_constraints import matching_wall_segments

    if item.get("locked"):
        yield deepcopy(item)
        return
    if elevation(item) <= 0 or elevation(item)+item["height"] > room["height"]+1e-6:
        return
    seen=set()
    def valid(candidate):
        key=tuple(round(candidate[k],5) for k in ("x","z","rotation"))
        if key in seen or wall_mount_errors(candidate,room) or window_conflicts(candidate,room):
            return False
        seen.add(key)
        return True
    if not preference or not preference.get("wall"):
        candidate=deepcopy(item)
        if valid(candidate):yield candidate
    segments=matching_wall_segments(room,preference or {})
    segments.sort(key=lambda wall:wall["segment"].distance(Point(item['x'],item['z'])))
    for wall in segments:
        start,tangent,inward=wall["start"],wall["tangent"],wall["inward"]
        left,right=item["width"]/2+.03,wall["length"]-item["width"]/2-.03
        if left>right:continue
        projected=(item["x"]-start[0])*tangent[0]+(item["z"]-start[1])*tangent[1]
        values=[min(right,max(left,projected)),(left+right)/2,left,right]
        count=min(11,max(3,int((right-left)/.4)+2))
        values.extend(left+(right-left)*index/(count-1) for index in range(count))
        for window in room.get("windows",[]):
            if window["wall"]!=wall["wall"]:continue
            for along in (window["offset"]-item["width"]/2-.03,window["offset"]+window["width"]+item["width"]/2+.03):
                point=(along,room["depth"] if window["wall"]=="north" else 0.) if window["wall"] in ("north","south") else (room["width"] if window["wall"]=="east" else 0.,along)
                values.append(min(right,max(left,(point[0]-start[0])*tangent[0]+(point[1]-start[1])*tangent[1])))
        for along in values:
            normal=item["depth"]/2+.02
            candidate={**item,"x":start[0]+tangent[0]*along+inward[0]*normal,
                       "z":start[1]+tangent[1]*along+inward[1]*normal,
                       "rotation":math.degrees(math.atan2(inward[0],inward[1]))%360}
            if valid(candidate):yield candidate

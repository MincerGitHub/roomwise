"""Reproduce the six-piece screenshot scene using only free layout endpoints.

No language endpoint, API key, saved project or uploaded asset is accessed.
The head position check below is independent of the backend evaluator.
"""
from copy import deepcopy
import argparse
import json
import math
from pathlib import Path
from urllib.request import Request, urlopen

APP = Path(__file__).resolve().parents[1]


def fixture():
    return {"id": "bedside-regression", "name": "床头柜关系复现场景", "version": 0,
            "room": {"width": 5.2, "depth": 4.2, "height": 2.7, "polygon": None,
                     "door": {"wall": "south", "offset": .45, "width": .9, "clearance": .9},
                     "windows": [{"id": "window-1", "wall": "north", "offset": 2.3,
                                  "width": 1.5, "sillHeight": .9}]},
            "items": [
                dict(id="bed-1", label="旧双人床", category="double_bed", width=1.8, depth=2., height=.55,
                     x=3.8, z=2.4, rotation=0., locked=False, keep=True, source="brought"),
                dict(id="wardrobe-1", label="房内衣柜", category="wardrobe", width=1.8, depth=.6, height=2.1,
                     x=1.15, z=3.8, rotation=0., locked=True, keep=True, source="existing"),
                dict(id="desk-1", label="旧书桌", category="desk", width=1.2, depth=.6, height=.75,
                     x=3.7, z=.55, rotation=0., locked=False, keep=True, source="brought"),
                dict(id="chair-1", label="办公椅", category="chair", width=.5, depth=.5, height=.85,
                     x=3.7, z=1.1, rotation=180., locked=False, keep=True, source="brought"),
                dict(id="nightstand-1", label="床头柜", category="nightstand", width=.5, depth=.45, height=.5,
                     x=2.6, z=2.8, rotation=0., locked=False, keep=True, source="existing"),
                dict(id="bookshelf-1", label="书架", category="bookshelf", width=.8, depth=.3, height=1.8,
                     x=.55, z=1.5, rotation=90., locked=False, keep=True, source="brought"),
            ],
            "preferences": [
                {"kind": "near_window", "itemId": "desk-1", "targetId": "window-1", "required": True},
                {"kind": "face_window", "itemId": "chair-1", "targetId": "window-1", "required": True},
                {"kind": "near_wall", "itemId": "bed-1", "required": True},
                {"kind": "near_wall", "itemId": "bookshelf-1", "required": True},
            ]}


def independent_check(scene):
    items = {item["id"]: item for item in scene["items"]}
    bed, stand = items["bed-1"], items["nightstand-1"]
    angle = math.radians(bed["rotation"])
    dx, dz = stand["x"]-bed["x"], stand["z"]-bed["z"]
    local_x = math.cos(angle)*dx-math.sin(angle)*dz
    local_z = math.sin(angle)*dx+math.cos(angle)*dz
    expected_z = -bed["depth"]/2+stand["depth"]/2+.08
    near_head = abs(local_z-expected_z) <= .30
    beside_long_edge = abs(local_x) >= bed["width"]/2
    return {"localX": local_x, "localZ": local_z, "expectedHeadZ": expected_z,
            "atHeadSide": near_head and beside_long_edge,
            "side": "right" if local_x > 0 else "left"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8765")
    parser.add_argument("--phase", choices=["before", "after"], required=True)
    args = parser.parse_args()
    scene = fixture()
    request = Request(args.base_url+"/api/generate", data=json.dumps(
        {"scene": deepcopy(scene), "mode": "hybrid", "count": 3, "seed": 42}).encode(),
                      headers={"Content-Type": "application/json"})
    with urlopen(request, timeout=45) as response:
        result = json.load(response)
    checks = [independent_check(candidate["scene"]) for candidate in result["candidates"]]
    if args.phase == "after":
        assert checks, result["diagnostics"]
        assert all(check["atHeadSide"] for check in checks), checks
        assert all(candidate["validation"]["valid"] and candidate["requirements"]["satisfied"]
                   for candidate in result["candidates"])
    output = APP / "artifacts/interaction_checks" / f"bedside_{args.phase}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({"phase": args.phase, "input": scene, "generation": result,
        "independentChecks": checks, "languageApiCalls": 0,
        "note": "Engineering reconstruction of screenshot scenario, not the user's exported scene."},
        ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"phase": args.phase, "candidates": len(checks), "checks": checks,
                      "elapsedSeconds": result["diagnostics"].get("elapsedSeconds"),
                      "languageApiCalls": 0}, ensure_ascii=True))


if __name__ == "__main__":
    main()

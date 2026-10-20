"""Exercise the reported interaction against the running local application.

Read/compute only: no save, upload, or database write. The recorded scenes are
self-created examples, not evidence of general interior-design quality.
"""
from copy import deepcopy
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import sys
import urllib.request

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP / "backend"))
from roomwise.catalog import demo_scene, CATALOG
from roomwise.schemas import Scene

TEXT = "桌子靠窗，椅子面朝窗户方向"


def api(path, body):
    request = urllib.request.Request("http://127.0.0.1:8765/api" + path,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(request, timeout=40) as response:
        return json.load(response)


def independently_check(candidate):
    """Calculate the north-window gap and facing vector without helper flags."""
    scene = candidate["scene"]
    by_id = {item["id"]: item for item in scene["items"]}
    desk, chair = by_id["desk-1"], by_id["chair-1"]
    window = scene["room"]["windows"][0]
    assert window["wall"] == "north"
    angle = math.radians(desk["rotation"])
    corners = [(desk["x"] + math.cos(angle)*sx*desk["width"]/2 + math.sin(angle)*sz*desk["depth"]/2,
                desk["z"] - math.sin(angle)*sx*desk["width"]/2 + math.cos(angle)*sz*desk["depth"]/2)
               for sx in (-1, 1) for sz in (-1, 1)]
    gap = scene["room"]["depth"] - max(z for _, z in corners)
    overlap = min(max(x for x, _ in corners), window["offset"]+window["width"]) - max(min(x for x, _ in corners), window["offset"])
    dx, dz = window["offset"]+window["width"]/2-chair["x"], scene["room"]["depth"]-chair["z"]
    rotation = math.radians(chair["rotation"])
    dot = (math.sin(rotation)*dx+math.cos(rotation)*dz)/math.hypot(dx, dz)
    error = math.degrees(math.acos(max(-1, min(1, dot))))
    assert gap <= .6001 and overlap >= -.1501 and error <= 20.001
    # The chair must also face the work surface: not just a random angle that
    # happens to intersect the window direction.
    to_desk = (desk["x"]-chair["x"], desk["z"]-chair["z"])
    assert math.sin(rotation)*to_desk[0]+math.cos(rotation)*to_desk[1] > 0
    return {"windowGapMeters": round(gap, 4), "windowProjectionOverlapMeters": round(overlap, 4),
            "chairFacingErrorDegrees": round(error, 3)}


def case(name, scene):
    scene = Scene.model_validate(scene).model_dump()
    before = deepcopy(scene)
    command = api("/command", {"scene": scene, "text": TEXT, "selectedId": "bookshelf-window-case"})
    assert command["action"] == "generate", command
    required = [p for p in command["scene"]["preferences"] if p.get("required")]
    assert {p["kind"] for p in required} == {"near_window", "face_window"}
    assert command["scene"]["items"] == scene["items"]
    validation = api("/validate", {"scene": command["scene"]})
    generated = api("/generate", {"scene": command["scene"], "mode": "hybrid", "count": 3, "seed": 42})
    assert generated["candidates"], generated["diagnostics"]
    checks = []
    for candidate in generated["candidates"]:
        assert candidate["validation"]["valid"] and candidate["requirements"]["satisfied"]
        assert candidate["mode"] == "rules" and not candidate["provenance"]["layoutNetwork"]
        after = {item["id"]: item for item in candidate["scene"]["items"]}
        for item in scene["items"]:
            assert item["id"] in after
            for key in ("category", "width", "depth", "height", "keep", "source", "locked"):
                assert item[key] == after[item["id"]][key]
            if item["locked"]:
                assert item == after[item["id"]]
        checks.append(independently_check(candidate))
    assert scene == before
    return {"name": name, "input_scene": scene, "command": command,
            "original_validation": validation, "generated": generated, "independent_checks": checks}


def main():
    backend = demo_scene()
    shelf = next(item for item in CATALOG if item["category"] == "bookshelf")
    backend["items"].append(dict(shelf, id="bookshelf-window-case", x=.5, z=1.5,
                                 rotation=0, locked=False, keep=True, source="brought"))
    frontend = deepcopy(backend)
    by_id = {item["id"]: item for item in frontend["items"]}
    frontend["preferences"] = []
    by_id["bed-1"].update(x=3.8, z=2.4)
    by_id["wardrobe-1"].update(width=1.8, x=1.15, z=3.8)
    by_id["desk-1"].update(x=3.7, z=.55)
    by_id["chair-1"].update(width=.5, x=3.7, z=1.1)
    by_id["nightstand-1"].update(width=.5, depth=.45, x=2.6, z=2.8)
    report = {"checked_at_utc": datetime.now(timezone.utc).isoformat(), "text": TEXT,
              "scope": "Two self-created six-item bedrooms; not a general design-quality evaluation",
              "cases": [case("backend_demo_plus_bookshelf", backend), case("frontend_demo_plus_bookshelf", frontend)]}
    destination = APP / "artifacts/interaction_checks/window_request_after.json"
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"saved": str(destination), "cases": [{"name": row["name"],
        "candidates": len(row["generated"]["candidates"]), "checks": row["independent_checks"],
        "other_moved": [candidate.get("changes", {}).get("otherMovedItemIds") for candidate in row["generated"]["candidates"]]}
        for row in report["cases"]]}, ensure_ascii=True))


if __name__ == "__main__":
    main()

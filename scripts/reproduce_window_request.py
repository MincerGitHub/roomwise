"""Capture the exact reported request without modifying saved projects."""
import json
from pathlib import Path
import sys

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP / "backend"))
from roomwise.catalog import demo_scene, CATALOG
from roomwise.commands import apply_command

scene = demo_scene()
shelf = next(item for item in CATALOG if item["category"] == "bookshelf")
scene["items"].append(dict(shelf, id="bookshelf-window-case", x=.5, z=1.5,
                           rotation=0, locked=False, keep=True, source="brought"))
text = "桌子靠窗，椅子面朝窗户方向"
response = apply_command(scene, text, "bookshelf-window-case")
record = {"text": text, "input_scene": scene, "response": response}
destination = APP / "artifacts/interaction_checks/window_request_before.json"
destination.parent.mkdir(parents=True, exist_ok=True)
if destination.exists():
    raise SystemExit("Reproduction record already exists; keep the original evidence")
destination.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps({"action": response["action"], "has_scene": "scene" in response,
                  "message": response["message"]}, ensure_ascii=True))

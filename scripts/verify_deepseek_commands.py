"""At most three explicitly requested live API checks; never runs by default."""
from copy import deepcopy
from datetime import datetime, timezone
import argparse
import json
from pathlib import Path
import sys

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP / "backend"))
from roomwise.catalog import demo_scene, CATALOG
from roomwise.command_service import interpret_command
from roomwise.intent_planner import language_status

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--run", action="store_true", help="make three paid provider requests using the private local configuration")
args = parser.parse_args()
status = language_status()
if not args.run:
    print(json.dumps({"status":status,"planned_requests":3,"actual_requests":0,"note":"Add --run only when ready for three real provider calls."},ensure_ascii=True))
    raise SystemExit(0)
if not status["enabled"]:
    raise SystemExit("The language model has not been configured; no requests were made.")
destination = APP/"artifacts/interaction_checks/deepseek_live_commands.json"
if destination.exists():
    raise SystemExit("Evidence already exists; no paid requests were made.")
scene = demo_scene()
shelf = next(item for item in CATALOG if item["category"] == "bookshelf")
scene["items"].append(dict(shelf,id="bookshelf-check",x=.5,z=1.5,rotation=0,locked=False,keep=True,source="brought"))
examples = [
    ("把书架贴到墙边去，其他家具都别动", "near_wall", "bookshelf-check"),
    ("让书桌靠着窗户，办公椅面向窗外，衣柜保持原位", "face_window", "chair-1"),
    ("只调整书桌，把它朝右挪20厘米", "move", "desk-1"),
]
records = []
for text, expected_name, expected_id in examples:
    result = interpret_command(deepcopy(scene),text)
    operations = result.get("interpretation",{}).get("operations",[])
    matched = any(operation["name"]==expected_name and expected_id in operation["itemIds"] for operation in operations)
    records.append({"instruction":text,"expected_operation":expected_name,"expected_item":expected_id,
                    "expected_operation_present":matched,"response":result})
destination.parent.mkdir(parents=True,exist_ok=True)
report = {"checked_at_utc":datetime.now(timezone.utc).isoformat(),"provider":status["provider"],
          "model":status["model"],"requested_calls":3,"records":records,
          "note":"Three engineering examples only; not a claim of majority command understanding or layout quality."}
destination.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
print(json.dumps({"saved":str(destination),"requested_calls":3,"matching_examples":sum(record["expected_operation_present"] for record in records)},ensure_ascii=True))

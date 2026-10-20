"""Replay the three recorded operation plans locally; no network or private config.

This verifies executor fixes against old model output. It does not measure the
updated prompt's live understanding accuracy and never issues a fourth request.
"""
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from unittest.mock import patch

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP / "backend"))
from roomwise import intent_planner
from roomwise.catalog import CATALOG, demo_scene
from roomwise.command_service import interpret_command


def main():
    evidence = json.loads((APP / "artifacts/interaction_checks/deepseek_live_commands.json").read_text(encoding="utf-8"))
    scene = demo_scene()
    shelf = next(item for item in CATALOG if item["category"] == "bookshelf")
    scene["items"].append(dict(shelf, id="bookshelf-check", x=.5, z=1.5,
                               rotation=0, locked=False, keep=True, source="brought"))
    results = []
    configuration = ("chatcompletions", "recorded-plan-replay", "https://replay.invalid",
                     "not-a-real-key", "", "json_object", False)
    for record in evidence["records"]:
        plan = {"action": "apply", "operations": record["response"]["interpretation"]["operations"]}
        recorded_response = {"choices": [{"message": {"content": json.dumps(plan, ensure_ascii=False)}}]}
        with patch.object(intent_planner, "_configuration", return_value=configuration), \
             patch.object(intent_planner, "_post_json", return_value=recorded_response):
            result = interpret_command(deepcopy(scene), record["instruction"])
        results.append({"instruction": record["instruction"], "action": result["action"],
                        "message": result["message"], "response": result})
    assert [row["action"] for row in results] == ["generate", "clarify", "edit"]
    assert "scene" not in results[1]["response"]
    original_desk = next(item for item in scene["items"] if item["id"] == "desk-1")
    edited_desk = next(item for item in results[2]["response"]["scene"]["items"] if item["id"] == "desk-1")
    assert abs(edited_desk["x"] - original_desk["x"] - .2) < 1e-8
    report = {"checked_at_utc": datetime.now(timezone.utc).isoformat(), "network_calls": 0,
              "type": "recorded_operations_replay", "records": results,
              "limitation": "Executor regression only; not a fresh model response or accuracy evaluation."}
    path = APP / "artifacts/interaction_checks/deepseek_local_replay.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"network_calls": 0, "actions": [row["action"] for row in results],
                      "checks_passed": True, "saved": str(path)}, ensure_ascii=True))


if __name__ == "__main__":
    main()

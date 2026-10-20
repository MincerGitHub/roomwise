"""Validate self-authored cases or score supplied semantic plans, without model calls.

This checks the benchmark's independent canonical annotation, not room geometry,
visual quality, or a particular runtime API. A supplied prediction file is not
evidence that a real model was called. Keep model/provider logs separately.
"""
from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
import json
import math
from pathlib import Path


DEFAULT_DATA = Path(__file__).resolve().parents[2] / "data" / "interaction_benchmark_v1.jsonl"
STATUSES = {"supported", "clarify", "planned", "unsupported"}


def records(path):
    with Path(path).open(encoding="utf-8-sig") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def materialize(meta, case):
    scene = deepcopy(meta["fixtures"][case["fixture"]])
    changes = case.get("mutators", {})
    scene["room"].update(deepcopy(changes.get("set_room", {})))
    for item in scene["items"]:
        item.update(deepcopy(changes.get("set_items", {}).get(item["id"], {})))
    removed = set(changes.get("remove_items", []))
    scene["items"] = [i for i in scene["items"] if i["id"] not in removed]
    scene["items"].extend(deepcopy(changes.get("add_items", [])))
    return scene


def validate_cases(meta, cases):
    seen = set()
    for case in cases:
        assert case["id"] not in seen, f"duplicate case: {case['id']}"
        seen.add(case["id"])
        assert case["expected"]["status"] in STATUSES, case["id"]
        assert case["text"].strip(), case["id"]
        scene = materialize(meta, case)
        item_ids = {i["id"] for i in scene["items"]}
        assert len(item_ids) == len(scene["items"]), case["id"]
        window_ids = {w["id"] for w in scene["room"]["windows"]}
        assert case["selectedId"] is None or case["selectedId"] in item_ids, case["id"]
        for operation in case["expected"]["operations"]:
            assert set(operation.get("itemIds", [])) <= item_ids, case["id"]
            assert set(operation.get("targetItemIds", [])) <= item_ids, case["id"]
            assert "targetItemId" not in operation or operation["targetItemId"] in item_ids, case["id"]
            assert "windowId" not in operation or operation["windowId"] in window_ids, case["id"]
        for item in scene["items"]:
            for field in ("width", "depth", "height"):
                assert math.isfinite(item[field]) and item[field] > 0, (case["id"], field)


def normalized(value):
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, (int, float)):
        return round(float(value), 6)
    if isinstance(value, dict):
        return {key: normalized(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return sorted((normalized(v) for v in value), key=lambda v: json.dumps(v, sort_keys=True))
    return value


def score(case, prediction):
    expected = case["expected"]
    if prediction is None:
        return {"id": case["id"], "passed": False, "reason": "missing_prediction"}
    if prediction.get("status") != expected["status"]:
        return {"id": case["id"], "passed": False, "reason": "status_mismatch"}
    # Only canonical semantic fields belong in operations; explanation belongs
    # outside them. Extra actions fail instead of being silently ignored.
    got = prediction.get("operations", [])
    want = expected["operations"]
    def canonical(value):
        # JSON serialization keeps booleans distinct from numeric 0/1.
        return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    if expected.get("atomicOrder"):
        operations_match = canonical([normalized(x) for x in got]) == canonical([normalized(x) for x in want])
    else:
        operations_match = canonical(normalized(got)) == canonical(normalized(want))
    if not operations_match:
        return {"id": case["id"], "passed": False, "reason": "operations_mismatch"}
    if expected["status"] == "clarify":
        actual = prediction.get("clarify") or {}
        required = expected["clarify"]
        relevant = {key: actual.get(key) for key in required}
        if canonical(normalized(relevant)) != canonical(normalized(required)):
            return {"id": case["id"], "passed": False, "reason": "clarification_fields_mismatch"}
    return {"id": case["id"], "passed": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--split", choices=("all", "development", "acceptance"), default="development")
    parser.add_argument("--predictions", type=Path, help="JSONL: id, status, operations, optional clarify; no network calls")
    parser.add_argument("--materialize", type=Path, help="Optional JSONL output with each requested input scene")
    args = parser.parse_args()
    data = records(args.dataset)
    meta, cases = data[0], data[1:]
    assert meta["recordType"] == "metadata"
    validate_cases(meta, cases)
    selected = [c for c in cases if args.split == "all" or c["split"] == args.split]
    result = {
        "benchmarkVersion": meta["benchmarkVersion"], "fixtureValidation": "passed",
        "totalCases": len(cases), "selectedCases": len(selected), "split": args.split,
        "expectedStatuses": dict(Counter(c["expected"]["status"] for c in selected)),
        "measured": "fixture_integrity_only", "modelCalls": 0,
        "limitation": "Public self-authored cases; no geometry, visual quality or real-model accuracy measured.",
    }
    if args.materialize:
        args.materialize.parent.mkdir(parents=True, exist_ok=True)
        args.materialize.write_text("\n".join(json.dumps({"id": c["id"], "scene": materialize(meta, c), "text": c["text"], "selectedId": c["selectedId"], "seed": c["seed"]}, ensure_ascii=False) for c in selected) + "\n", encoding="utf-8")
    if args.predictions:
        supplied = records(args.predictions)
        assert len({p["id"] for p in supplied}) == len(supplied), "Duplicate prediction IDs"
        predictions = {p["id"]: p for p in supplied}
        scores = [score(c, predictions.get(c["id"])) for c in selected]
        passed = sum(s["passed"] for s in scores)
        result.update(measured="supplied_canonical_semantic_annotations", matchedCases=passed,
                      exactMatchRate=passed / len(selected) if selected else None,
                      unverifiedPredictionSource=str(args.predictions), failures=[s for s in scores if not s["passed"]])
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

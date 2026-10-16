"""Small, fixed-budget application checks on 12 self-made scenes.

This is separate from house-held-out denoising quality. Both modes use the SAME
scenes, seeds, count and configured search budget, with explicit model/repair
diagnostics. It is not a real-user study and does not prove global feasibility.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
import time

import numpy as np

APP=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(APP/"backend"))
from roomwise.catalog import demo_scene, CATALOG
from roomwise import generator
from roomwise.geometry import assert_invariants,validate_scene
from roomwise.learning import MODEL_PATH


def make_scenes():
    scenes=[]
    dimensions=[(5.2,4.2),(5.2,4.2),(4.6,3.8),(6.0,5.0),(5.4,4.5),(5.6,4.4),
                (4.8,4.0),(5.2,4.2),(5.2,4.2),(3.8,4.4),(5.2,4.2),(5.2,4.2)]
    rng=np.random.default_rng(7816)
    for index,(width,depth) in enumerate(dimensions):
        scene=demo_scene();scene["id"]=f"engineering-{index:02d}";scene["name"]=f"自制工程场景{index+1}"
        scene["room"]["width"]=width;scene["room"]["depth"]=depth
        scene["room"]["windows"][0]["offset"]=width/2-.75
        wardrobe=next(i for i in scene["items"] if i["category"]=="wardrobe")
        wardrobe["x"]=width-.85;wardrobe["z"]=.42
        for item in scene["items"]:
            if not item["locked"]:
                item["x"]=float(rng.uniform(.4,width-.4));item["z"]=float(rng.uniform(.4,depth-.4))
                item["rotation"]=float(rng.choice([0,90,180,270]))
        expected_failure=False
        condition="可移动旧家具与锁定房内衣柜"
        if index==4:
            bed=next(i for i in scene["items"] if i["category"]=="double_bed")
            bed.update(locked=True,x=1.0,z=depth-1.05,rotation=0)
            condition="固定床和衣柜，调整其余物品"
        if index==5:
            for category in ("bookshelf","rug"):
                item=deepcopy(next(i for i in CATALOG if i["category"]==category))
                item.update(id=category+"-extra",x=width/2,z=depth/2,rotation=0,locked=False,keep=True,source="new")
                scene["items"].append(item)
            condition="加入书架和允许重叠的地毯"
        if index==6:
            scene["items"]=[i for i in scene["items"] if i["category"]!="chair"]
            condition="四件家具的紧凑房间"
        if index==7:
            scene["preferences"].append({"kind":"min_move","itemId":"bed-1"})
            condition="同时设置靠窗与少移动软偏好"
        if index==8:
            scene["room"]["door"]={"wall":"east","offset":2.0,"width":.9,"clearance":.9}
            condition="入口换到东墙"
        if index==9:
            condition="更窄的房间"
        if index==10:
            next(i for i in scene["items"] if i["category"]=="double_bed").update(width=8,depth=8)
            expected_failure=True;condition="床占地大于整个房间，应明确失败"
        if index==11:
            wardrobe["x"]=width+1
            expected_failure=True;condition="锁定衣柜在房外，应明确失败"
        scenes.append({"scene":scene,"condition":condition,"expected_failure":expected_failure})
    return scenes


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--count",type=int,default=1)
    parser.add_argument("--seconds",type=float,default=5.0)
    parser.add_argument("--checks",type=int,default=8000)
    args=parser.parse_args()
    generator.SEARCH_SECONDS=args.seconds;generator.SEARCH_PLACEMENT_CHECKS=args.checks
    scenes=make_scenes();records=[];start=time.perf_counter()
    for entry in scenes:
        scene=entry["scene"]
        for mode in ("rules","hybrid"):
            began=time.perf_counter();result=generator.generate_layouts(deepcopy(scene),mode=mode,count=args.count,seed=712)
            elapsed=time.perf_counter()-began
            verified=True;invariant_failures=0;validation_failures=0
            for candidate in result["candidates"]:
                try:assert_invariants(scene,candidate["scene"])
                except (ValueError,AssertionError):invariant_failures+=1
                if not validate_scene(candidate["scene"])["valid"]:validation_failures+=1
            diagnostic=result["diagnostics"]
            record={"scene_id":scene["id"],"condition":entry["condition"],"expected_failure":entry["expected_failure"],
                    "mode":mode,"seed":712,"count_requested":args.count,"candidate_count":len(result["candidates"]),
                    "success":bool(result["candidates"]),"elapsed_seconds":round(elapsed,4),
                    "invariant_failures":invariant_failures,"validation_failures":validation_failures,
                    "candidate_methods":[c["mode"] for c in result["candidates"]],
                    "model_proposals":diagnostic.get("modelProposals",0),"raw_model_accepted":diagnostic.get("rawModelAccepted",0),
                    "repaired_model_accepted":diagnostic.get("repairedModelAccepted",0),
                    "search_budget_exhausted":diagnostic.get("searchBudgetExhausted",False),
                    "message":diagnostic["message"]}
            records.append(record)
            print(json.dumps(record,ensure_ascii=False),flush=True)
    summary={}
    for mode in ("rules","hybrid"):
        group=[r for r in records if r["mode"]==mode]
        ordinary=[r for r in group if not r["expected_failure"]]
        expected=[r for r in group if r["expected_failure"]]
        summary[mode]={"scenes":len(group),"ordinary_scenes":len(ordinary),"ordinary_successes":sum(r["success"] for r in ordinary),
                       "ordinary_success_rate":sum(r["success"] for r in ordinary)/len(ordinary),
                       "expected_failures_correctly_rejected":sum(not r["success"] for r in expected),
                       "expected_failure_scenes":len(expected),"mean_elapsed_seconds":float(np.mean([r["elapsed_seconds"] for r in group])),
                       "median_elapsed_seconds":float(np.median([r["elapsed_seconds"] for r in group])),
                       "invariant_failures":sum(r["invariant_failures"] for r in group),
                       "validation_failures":sum(r["validation_failures"] for r in group),
                       "model_proposals":sum(r["model_proposals"] for r in group),
                       "raw_model_accepted":sum(r["raw_model_accepted"] for r in group),
                       "repaired_model_accepted":sum(r["repaired_model_accepted"] for r in group),
                       "accepted_candidate_methods":{method:sum(r["candidate_methods"].count(method) for r in group)
                                                     for method in ("rules","hybrid","model","current")}}
    report={"evaluated_at":"2026-10-11","type":"12 self-made engineering examples, not real-household or held-out quality evaluation",
            "budget":{"seconds":args.seconds,"placement_checks":args.checks,"count":args.count,"seed":712},
            "model_checkpoint_sha256":hashlib.file_digest(MODEL_PATH.open("rb"),"sha256").hexdigest(),
            "summary":summary,"records":records,"elapsed_seconds":round(time.perf_counter()-start,2),
            "limitations":["Small deterministic examples do not estimate population success or user preference.",
                           "Wall-clock budget may depend on CPU load; both methods use the same configured caps.",
                           "Hybrid repair is explicitly geometric search; rule-only fallback is counted as rules.",
                           "A timeout or failure does not prove mathematical impossibility."]}
    directory=APP/"artifacts/experiments"
    (directory/"app_metrics.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    # Self-created scenes have no restricted upstream arrays and can accompany tests.
    (directory/"app_scenarios.json").write_text(json.dumps(scenes,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(summary),flush=True)


if __name__=="__main__":main()

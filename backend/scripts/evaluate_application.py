"""Small, fixed-budget application checks on 12 self-made scenes.

This is separate from house-held-out denoising quality. Both modes use the SAME
scenes, seeds, count and configured search budget, with explicit model/repair
diagnostics. It is not a real-user study and does not prove global feasibility.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import sys
import time

import numpy as np

APP=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(APP/"backend"))
from roomwise.catalog import demo_scene, CATALOG
from roomwise import generator, learning
from roomwise.geometry import assert_invariants,validate_scene


def file_sha256(path):
    digest=hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda:stream.read(1024*1024),b""):
            digest.update(block)
    return digest.hexdigest()


@contextmanager
def using_checkpoint(checkpoint,threads=1):
    """Temporarily load a research model on CPU; never replace live artifacts."""
    checkpoint=Path(checkpoint).resolve()
    metadata_path=checkpoint.with_suffix(".json")
    metadata=json.loads(metadata_path.read_text(encoding="utf-8"))
    digest=file_sha256(checkpoint)
    if digest!=metadata["checkpoint_sha256"]:
        raise ValueError("Application checkpoint does not match its recorded SHA256.")
    if learning.torch is None:
        raise RuntimeError("PyTorch is required to compare actual model-assisted layouts.")
    previous_paths=(learning.MODEL_PATH,learning.META_PATH)
    previous_threads=learning.torch.get_num_threads()
    learning._cached_model.cache_clear()
    try:
        learning.MODEL_PATH=checkpoint
        learning.META_PATH=metadata_path
        learning.torch.set_num_threads(threads)
        # Preload outside both methods' timed searches. Inference remains CPU,
        # matching the deployed application's current implementation.
        if learning._load_model() is None:
            raise RuntimeError("The requested application checkpoint could not be loaded.")
        yield metadata
    finally:
        learning._cached_model.cache_clear()
        learning.MODEL_PATH,learning.META_PATH=previous_paths
        learning.torch.set_num_threads(previous_threads)


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


def evaluate(args,checkpoint,metadata,directory):
    generator.SEARCH_SECONDS=args.seconds;generator.SEARCH_PLACEMENT_CHECKS=args.checks
    scenes=make_scenes();records=[];start=time.perf_counter()
    for entry in scenes:
        scene=entry["scene"]
        for mode in ("rules","hybrid"):
            began=time.perf_counter();result=generator.generate_layouts(deepcopy(scene),mode=mode,count=args.count,seed=args.seed)
            elapsed=time.perf_counter()-began
            invariant_failures=0;validation_failures=0
            for candidate in result["candidates"]:
                try:assert_invariants(scene,candidate["scene"])
                except (ValueError,AssertionError):invariant_failures+=1
                if not validate_scene(candidate["scene"])["valid"]:validation_failures+=1
            diagnostic=result["diagnostics"]
            record={"scene_id":scene["id"],"condition":entry["condition"],"expected_failure":entry["expected_failure"],
                    "mode":mode,"seed":args.seed,"count_requested":args.count,"candidate_count":len(result["candidates"]),
                    "success":bool(result["candidates"]),"elapsed_seconds":round(elapsed,4),
                    "invariant_failures":invariant_failures,"validation_failures":validation_failures,
                    "candidate_methods":[c["mode"] for c in result["candidates"]],
                    "candidate_provenance":[c.get("provenance",{}) for c in result["candidates"]],
                    "candidate_scores":[c.get("score") for c in result["candidates"]],
                    "model_proposals":diagnostic.get("modelProposals",0),"raw_model_accepted":diagnostic.get("rawModelAccepted",0),
                    "repaired_model_accepted":diagnostic.get("repairedModelAccepted",0),
                    "model_available":diagnostic.get("modelStatus",{}).get("available",False),
                    "model_error":diagnostic.get("modelError"),
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
    report={"evaluated_at":datetime.now(timezone.utc).isoformat(),
            "type":f"{len(scenes)} self-made engineering examples, not real-household or held-out quality evaluation",
            "budget":{"seconds":args.seconds,"placement_checks":args.checks,"count":args.count,"seed":args.seed},
            "scene_generation_seed":7816,
            "scenes_sha256":hashlib.sha256(json.dumps(scenes,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode("utf-8")).hexdigest(),
            "model_checkpoint":str(checkpoint),"model_checkpoint_sha256":file_sha256(checkpoint),
            "model_training":metadata,
            "environment":{"python":sys.version,"pytorch":str(learning.torch.__version__),
                           "numpy":np.__version__,"device":"cpu","threads":args.threads},
            "timing":"Model loading is excluded; both methods receive the same scene, seed, candidate count and configured search caps.",
            "summary":summary,"records":records,"elapsed_seconds":round(time.perf_counter()-start,2),
            "limitations":["Small deterministic examples do not estimate population success or user preference.",
                           "Wall-clock budget may depend on CPU load; both methods use the same configured caps.",
                           "Hybrid repair is explicitly geometric search; rule-only fallback is counted as rules.",
                           "A timeout or failure does not prove mathematical impossibility.",
                           "Candidate preference scores are hand-defined and do not measure real users' design quality.",
                           "Model-assisted candidates may require geometric repair; these checks do not establish superiority to rules."]}
    directory.mkdir(parents=True,exist_ok=True)
    (directory/"app_metrics.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    # Self-created scenes have no restricted upstream arrays and can accompany tests.
    (directory/"app_scenarios.json").write_text(json.dumps(scenes,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(summary),flush=True)
    return report


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count",type=int,default=1)
    parser.add_argument("--seconds",type=float,default=5.0)
    parser.add_argument("--checks",type=int,default=8000)
    parser.add_argument("--seed",type=int,default=712)
    parser.add_argument("--threads",type=int,default=1)
    parser.add_argument("--checkpoint",type=Path,
                        help="research checkpoint; requires --output-dir and never replaces the live model")
    parser.add_argument("--output-dir",type=Path,
                        help="isolated run root; writes experiments/app_metrics.json and app_scenarios.json")
    args=parser.parse_args(argv)
    if (args.count<1 or args.checks<1 or not math.isfinite(args.seconds)
            or args.seconds<=0 or not 1<=args.threads<=4):
        parser.error("count, checks and seconds must be positive; threads must be 1..4")
    if args.checkpoint and not args.output_dir:
        parser.error("An explicit research checkpoint requires --output-dir.")
    if args.output_dir:
        root=args.output_dir.resolve()
        production=(APP/"artifacts").resolve()
        if root==production or production in root.parents:
            parser.error("Research output-dir must be outside production artifacts.")
        directory=root/"experiments"
        if any((directory/name).exists() for name in ("app_metrics.json","app_scenarios.json")):
            parser.error("Application reports already exist in output-dir; use a new result directory.")
    else:
        directory=APP/"artifacts/experiments"
    checkpoint=(args.checkpoint or learning.MODEL_PATH).resolve()
    previous_limits=(generator.SEARCH_SECONDS,generator.SEARCH_PLACEMENT_CHECKS)
    try:
        with using_checkpoint(checkpoint,args.threads) as metadata:
            return evaluate(args,checkpoint,metadata,directory)
    finally:
        generator.SEARCH_SECONDS,generator.SEARCH_PLACEMENT_CHECKS=previous_limits


if __name__=="__main__":main()

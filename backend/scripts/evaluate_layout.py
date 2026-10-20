"""Held-out house tests, literal raw metrics and no promised model improvement.

The rule baseline in this report is explicitly a clamp + cardinal snap, not the
web application's multistart geometry optimiser. Door/circulation annotations
are unavailable in these source arrays and are not claimed as ML test metrics.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import sys
import time

import numpy as np

APP = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(APP / "backend"))
from roomwise.learning import MODEL_PATH, load_checkpoint, torch
from roomwise.learning import CATEGORIES
from train_layout import file_sha256, noisy_batch, predict, metrics


def box_corners(position, size, angle):
    x,z=np.asarray(size[:2])/2
    local=np.array([[-x,-z],[x,-z],[x,z],[-x,z]])
    c,s=np.cos(angle),np.sin(angle)
    return local@np.array([[c,-s],[s,c]])+position


def simple_rule(pos, angle, batch):
    pos,angle=pos.copy(),angle.copy()
    # Explicitly modest baseline: preserve object identity, sizes and locks.
    for b in range(len(pos)):
        for i in np.flatnonzero(batch["moving"][b]):
            angle[b,i]=round(angle[b,i]/(np.pi/2))*(np.pi/2)
            corner=box_corners([0,0],batch["sizes"][b,i],angle[b,i])
            extent=np.abs(corner).max(axis=0)
            lower=-batch["dims"][b]/2+extent
            upper=batch["dims"][b]/2-extent
            pos[b,i]=np.clip(pos[b,i],np.minimum(lower,upper),np.maximum(lower,upper))
    return pos,angle


def geometry_metrics(pos,angle,batch,polygons):
    from shapely.geometry import Polygon
    outside_items,overlap_pairs=0,0
    bad_rooms=0; checked_pairs=0; checked_items=0
    for b in range(len(pos)):
        floor=Polygon(polygons[b]).buffer(.002)
        boxes=[]
        for i in np.flatnonzero(batch["mask"][b]):
            box=Polygon(box_corners(pos[b,i],batch["sizes"][b,i],angle[b,i]))
            boxes.append(box)
            outside_items+=int(box.difference(floor).area>.01)
            checked_items+=1
        room_bad=False
        for i,left in enumerate(boxes):
            for right in boxes[i+1:]:
                checked_pairs+=1
                intersects=left.intersection(right).area>.01
                overlap_pairs+=int(intersects)
                room_bad|=intersects
        bad_rooms+=int(room_bad)
    return {"footprint_outside_items":outside_items,"footprint_outside_item_rate":outside_items/max(checked_items,1),
            "overlapping_footprint_pairs":overlap_pairs,"overlap_pair_rate":overlap_pairs/max(checked_pairs,1),
            "rooms_with_overlap":bad_rooms,"rooms_with_overlap_rate":bad_rooms/len(pos),
            "checked_items":checked_items,"checked_pairs":checked_pairs,
            "area_tolerance_m2":.01,
            "interpretation":"2D full bounding-box footprints; intersections may overestimate real mesh collisions or intentional contact"}


def plot_examples(data,indices,polygons,batch,outputs,destination):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Polygon
    names=["Noisy input","Clamp + snap","Trained model (3 steps)","Reference layout"]
    selected=min(3,len(indices))
    fig,axes=plt.subplots(selected,4,figsize=(16,4*selected),squeeze=False)
    from roomwise.learning import CATEGORIES
    palettes=plt.cm.tab20(np.linspace(0,1,19))
    for row in range(selected):
        configs=[(batch["noisy_pos"],batch["noisy_angle"]),outputs["rule"],outputs["model_3_steps"],(batch["pos"],batch["angle"])]
        for col,(pos,ang) in enumerate(configs):
            ax=axes[row,col]
            outline=np.array(polygons[row]); outline=np.concatenate([outline,outline[:1]])
            ax.plot(outline[:,0],outline[:,1],color="black",linewidth=2)
            for i in np.flatnonzero(batch["mask"][row]):
                category=int(batch["classes"][row,i]); corners=box_corners(pos[row,i],batch["sizes"][row,i],ang[row,i])
                ax.add_patch(Polygon(corners,facecolor=palettes[category],alpha=.6,edgecolor="black"))
                label=CATEGORIES[category].replace("_"," ")+ (" *" if batch["locked"][row,i] else "")
                ax.text(*pos[row,i],label,fontsize=7,ha="center",va="center")
            ax.set_title(names[col]);ax.set_aspect("equal");ax.invert_yaxis();ax.grid(alpha=.2)
            ax.set_xlabel("x (m)");ax.set_ylabel("z (m)")
    fig.suptitle("Held-out houses, simulated perturbation; * = locked furniture. Source: 3D-FRONT / LEGO-Net.",fontsize=12)
    fig.tight_layout();fig.savefig(destination,dpi=140);plt.close(fig)


def main(argv=None):
    parser=argparse.ArgumentParser()
    parser.add_argument("--data",type=Path,default=APP.parent/"data/Roomwise/bedrooms_prepared.npz")
    parser.add_argument("--threads",type=int,default=4)
    parser.add_argument("--batch-size",type=int,default=128)
    parser.add_argument("--device",choices=("cpu","cuda"),default="cpu")
    parser.add_argument("--checkpoint",type=Path,default=MODEL_PATH)
    parser.add_argument("--output-dir",type=Path,
                        help="isolated run root; writes experiments/ without replacing live metrics")
    parser.add_argument("--evaluate-split",choices=("validation","test"),default="test",
                        help="use validation for research model selection, reserve test for a final selected configuration")
    parser.add_argument("--no-figures",action="store_true",
                        help="skip source-derived plot caches and figures, and do not import matplotlib")
    args=parser.parse_args(argv)
    if torch is None:
        raise RuntimeError("Install PyTorch in the project's virtual environment first.")
    if args.threads<1 or args.batch_size<1:
        parser.error("threads and batch-size must be positive")
    if args.output_dir:
        output=args.output_dir.resolve()
        production=(APP/"artifacts").resolve()
        if output==production or production in output.parents:
            parser.error("Explicit research output-dir must be outside production artifacts; omit it only for the legacy evaluation workflow")
    torch.set_num_threads(args.threads)
    with np.load(args.data,allow_pickle=False) as source:
        data={k:source[k] for k in source.files}
    all_polygons=json.loads(args.data.with_suffix(".polygons.json").read_text(encoding="utf-8"))
    test=np.flatnonzero(data["split"]==(1 if args.evaluate_split=="validation" else 2))
    if len(test)==0:
        raise ValueError("Chosen evaluation split has no rooms.")
    polygons=[all_polygons[i] for i in test]
    model=load_checkpoint(args.checkpoint,args.device)
    model.eval(); start=time.perf_counter()
    experiment_dir=(args.output_dir or APP/"artifacts")/"experiments"
    experiment_dir.mkdir(parents=True,exist_ok=True)
    report={"evaluated_at":datetime.now(timezone.utc).isoformat(),
            "evaluated_rooms":len(test),"evaluated_houses":len(set(data["house"][test])),
            "evaluation_split":args.evaluate_split,"device":args.device,"threads":args.threads,
            "checkpoint":str(args.checkpoint),"checkpoint_sha256":file_sha256(args.checkpoint),
            "environment":{"python":sys.version,"pytorch":torch.__version__,"numpy":np.__version__,
                           "cuda_runtime":torch.version.cuda,
                           "gpu_name":torch.cuda.get_device_name() if args.device=="cuda" else None},
            "split":"house-level deterministic SHA256 split; test not used for model selection",
            "seed":96117,"task":"recover professionally designed layouts from simulated perturbations, not real moving-house observations",
            "important_limitations":["A reference is one reasonable layout, not a unique optimum.",
                                     "No door/window/route annotations in the chosen arrays; no circulation or accessibility claim.",
                                     "No new-furniture selection, mesh reconstruction, natural-language evaluation, or real household user study.",
                                     "Simple rule is clamp-to-room-bounds + cardinal-angle snap, not app's multistart geometry planner."],
            "levels":[]}
    report[f"{args.evaluate_split}_rooms"]=len(test)
    report[f"{args.evaluate_split}_houses"]=len(set(data["house"][test]))
    for level,(std,angle_std) in enumerate(((.2,15),(.45,30),(.8,50))):
        batch=noisy_batch(data,test,np.random.default_rng(96117+level),noise=(std,angle_std))
        outputs={"identity":(batch["noisy_pos"],batch["noisy_angle"]),"rule":simple_rule(batch["noisy_pos"],batch["noisy_angle"],batch)}
        for steps in (1,3):
            pieces=[]
            for offset in range(0,len(test),args.batch_size):
                sub={k:v[offset:offset+args.batch_size] for k,v in batch.items()}
                pieces.append(predict(model,sub,iterations=steps))
            outputs[f"model_{steps}_steps"]=(np.concatenate([p[0] for p in pieces]),np.concatenate([p[1] for p in pieces]))
        row={"position_noise_std_m":std,"angle_noise_std_deg":angle_std,"methods":{}}
        row["reference_footprint_geometry"] = geometry_metrics(batch["pos"],batch["angle"],batch,polygons)
        for method,(p,a) in outputs.items():
            m=metrics(p,a,batch);m.update(geometry_metrics(p,a,batch,polygons))
            m["category_position_errors"] = {}
            for class_index, category in enumerate(CATEGORIES):
                category_mask=batch["moving"] & (batch["classes"]==class_index)
                if category_mask.any():
                    errors=np.linalg.norm(p-batch["pos"],axis=-1)[category_mask]
                    m["category_position_errors"][category] = {
                        "movable_item_count":int(category_mask.sum()),
                        "position_mae_m":float(errors.mean())}
            locked=batch["locked"]
            m["locked_position_max_change_m"]=float(np.abs(p-batch["noisy_pos"])[locked].max()) if locked.any() else 0
            m["locked_angle_max_change_deg"]=float(np.degrees(np.abs(a-batch["noisy_angle"])[locked]).max()) if locked.any() else 0
            row["methods"][method]=m
        report["levels"].append(row)
        print(json.dumps(row),flush=True)
        if level==1 and not args.no_figures:
            # A plot-only cache outside the distributable app lets global Python
            # render figures if the minimal API venv has no matplotlib.
            cache_dir=experiment_dir if args.output_dir else args.data.parent
            cache_name="validation_plot" if args.evaluate_split=="validation" else "heldout_plot"
            np.savez_compressed(cache_dir/f"{cache_name}_cache.npz",
                                **{k:v[:3] for k,v in batch.items()},
                                rule_pos=outputs["rule"][0][:3], rule_angle=outputs["rule"][1][:3],
                                model_pos=outputs["model_3_steps"][0][:3],model_angle=outputs["model_3_steps"][1][:3])
            (cache_dir/f"{cache_name}_polygons.json").write_text(json.dumps(polygons[:3]),encoding="utf-8")
            try:
                plot_examples(data,test,polygons,batch,outputs,
                              experiment_dir/("validation_examples.png" if args.evaluate_split=="validation" else "heldout_examples.png"))
            except ImportError:
                report["figure_status"]="matplotlib unavailable"
    clean=noisy_batch(data,test,np.random.default_rng(1294),noise=(0,0))
    pieces=[]
    for offset in range(0,len(test),args.batch_size):
        sub={k:v[offset:offset+args.batch_size] for k,v in clean.items()}
        pieces.append(predict(model,sub,iterations=3))
    report["clean_layout_drift"]=metrics(np.concatenate([p[0] for p in pieces]),np.concatenate([p[1] for p in pieces]),clean)
    report["elapsed_seconds"]=round(time.perf_counter()-start,2)
    outfile=experiment_dir/("validation_metrics.json" if args.evaluate_split=="validation" else "heldout_metrics.json")
    outfile.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({"saved":str(outfile),"elapsed_seconds":report["elapsed_seconds"],"clean_layout_drift":report["clean_layout_drift"]}),flush=True)


if __name__=="__main__": main()

"""Train a compact set Transformer on house-disjoint 3D-FRONT bedrooms.

Run with the project's venv. No upstream executable code is imported. All
augmentation is generated AFTER the house split; validation noise is fixed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import random
import sys
import time

import numpy as np

APP = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(APP / "backend"))
from roomwise.learning import LayoutDenoiser, make_features, torch

POSITION_NOISE = [.1, .3, .6, 1.0]
ANGLE_NOISE_DEG = [8, 20, 40, 65]


def noisy_batch(data, indices, rng, noise=None, rotate=False):
    pos = data["pos"][indices].copy()
    angle = data["angle"][indices].copy()
    sizes = data["size"][indices].copy()
    boundary = data["boundary"][indices].copy()
    dims = data["dims"][indices].copy()
    classes = data["classes"][indices].copy()
    mask = classes >= 0
    if rotate:
        turns = rng.integers(0, 4, len(indices))
        for b,turn in enumerate(turns):
            a = turn*np.pi/2
            transform = np.array([[np.cos(a), -np.sin(a)], [np.sin(a), np.cos(a)]])
            # Row-vector Three.js rotation: x'=cos*x+sin*z, z'=-sin*x+cos*z.
            pos[b] = pos[b] @ transform
            boundary[b] = boundary[b] @ transform
            angle[b] += a
            if turn % 2:
                dims[b] = dims[b, ::-1]
    locked = (rng.random(mask.shape) < rng.uniform(.0, .45, (len(indices),1))) & mask
    # Ensure at least one free item in every non-empty scene.
    for b in range(len(indices)):
        if np.all(locked[b, mask[b]]):
            locked[b, np.flatnonzero(mask[b])[0]] = False
    if noise is None:
        level = rng.integers(0, 4, len(indices))
        std = np.asarray(POSITION_NOISE)[level]
        angle_std = np.radians(np.asarray(ANGLE_NOISE_DEG)[level])
        clean = rng.random(len(indices)) < .12
        std[clean] = 0
        angle_std[clean] = 0
    else:
        std = np.full(len(indices), noise[0])
        angle_std = np.full(len(indices), np.radians(noise[1]))
    moving = mask & ~locked
    noisy_pos = pos + rng.normal(size=pos.shape).astype(np.float32) * std[:,None,None] * moving[:,:,None]
    noisy_angle = angle + rng.normal(size=angle.shape).astype(np.float32)*angle_std[:,None]*moving
    features, padding = make_features(noisy_pos, noisy_angle, sizes, classes, locked, mask, boundary, dims)
    targets = np.concatenate([(pos-noisy_pos)/3,
                              (np.stack([np.cos(angle), np.sin(angle)], -1) -
                               np.stack([np.cos(noisy_angle), np.sin(noisy_angle)], -1))], axis=-1)
    return dict(features=features, padding=padding, target=targets.astype(np.float32), moving=moving,
                pos=pos, angle=angle, noisy_pos=noisy_pos, noisy_angle=noisy_angle,
                sizes=sizes, classes=classes, locked=locked, mask=mask, boundary=boundary, dims=dims)


def predict(model, batch, iterations=1):
    pos, angle = batch["noisy_pos"].copy(), batch["noisy_angle"].copy()
    with torch.inference_mode():
        for step in range(iterations):
            feat, padding = make_features(pos, angle, batch["sizes"], batch["classes"],
                                          batch["locked"], batch["mask"], batch["boundary"], batch["dims"])
            output = model(torch.from_numpy(feat), torch.from_numpy(padding)).numpy()[:, :pos.shape[1]]
            gain = 1.0 if iterations == 1 else (.8, .4, .2, .1, .1)[min(step,4)]
            delta = output[:,:,:2]*3
            if iterations != 1:
                delta = np.clip(delta, -.7, .7)
            pos += delta*gain*batch["moving"][:,:,None]
            orientation = np.stack([np.cos(angle), np.sin(angle)], -1)+output[:,:,2:]*gain
            target_angle = np.arctan2(orientation[:,:,1], orientation[:,:,0])
            angle_delta = (target_angle-angle+np.pi)%(2*np.pi)-np.pi
            if iterations != 1:
                angle_delta = np.clip(angle_delta, -np.pi/4, np.pi/4)
            angle += angle_delta*batch["moving"]
    return pos,angle


def metrics(pos, angle, batch):
    moving=batch["moving"]
    distance=np.linalg.norm(pos-batch["pos"],axis=-1)[moving]
    err=np.abs((angle-batch["angle"]+np.pi)%(2*np.pi)-np.pi)[moving]
    return {"position_mae_m":float(distance.mean()), "position_rmse_m":float(np.sqrt(np.mean(distance**2))),
            "angle_mae_deg":float(np.degrees(err).mean()), "evaluated_movable_items":int(moving.sum())}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, default=APP.parent/"data/Roomwise/bedrooms_prepared.npz")
    parser.add_argument("--epochs", type=int, default=60)
    parser.add_argument("--batch-size", type=int, default=128)
    parser.add_argument("--max-seconds", type=float, default=600)
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--seed", type=int, default=20261011)
    parser.add_argument("--resume", action="store_true", help="continue the existing best checkpoint; fresh optimiser, lr=0.0003")
    args=parser.parse_args()
    if torch is None:
        raise RuntimeError("Install CPU torch in project venv first.")
    torch.set_num_threads(args.threads)
    torch.set_num_interop_threads(1)
    torch.manual_seed(args.seed); np.random.seed(args.seed); random.seed(args.seed)
    rng=np.random.default_rng(args.seed)
    with np.load(args.data, allow_pickle=False) as arrays:
        data={k:arrays[k] for k in arrays.files}
    train=np.flatnonzero(data["split"]==0); val=np.flatnonzero(data["split"]==1)
    fixed_val=noisy_batch(data,val,np.random.default_rng(4321),noise=(.45,30))
    model=LayoutDenoiser()
    model_dir=APP/"artifacts/models"; experiment_dir=APP/"artifacts/experiments"
    model_dir.mkdir(parents=True,exist_ok=True); experiment_dir.mkdir(parents=True,exist_ok=True)
    baseline=metrics(fixed_val["noisy_pos"],fixed_val["noisy_angle"],fixed_val)
    previous=None; initial_epoch=0; previous_seconds=0; steps=0; best=float("inf")
    history=[]; best_epoch=0; best_metrics=baseline
    if args.resume:
        checkpoint=torch.load(model_dir/"layout_denoiser.pt",map_location="cpu",weights_only=True)
        model.load_state_dict(checkpoint["state_dict"])
        previous=json.loads((model_dir/"layout_denoiser.json").read_text(encoding="utf-8"))
        history=json.loads((experiment_dir/"training_history.json").read_text(encoding="utf-8"))
        initial_epoch=previous["epochs_run"]; previous_seconds=previous["duration_seconds"]; steps=previous["steps"]
        best_epoch=previous["best_epoch"]; best_metrics=previous["best_validation"]
        best=best_metrics["position_mae_m"]+best_metrics["angle_mae_deg"]/180
        # Different online perturbations in continuation; fixed validation unchanged.
        rng=np.random.default_rng(args.seed+initial_epoch)
    optimizer=torch.optim.AdamW(model.parameters(),lr=3e-4 if args.resume else 1.5e-3,weight_decay=1e-4)
    stale=0; start=time.perf_counter()
    print(json.dumps({"train_rooms":len(train),"val_rooms":len(val),"parameters":sum(p.numel() for p in model.parameters()),
                      "validation_identity":baseline}),flush=True)
    for epoch in range(initial_epoch+1,initial_epoch+args.epochs+1):
        model.train(); losses=[]
        indices=rng.permutation(train)
        for offset in range(0,len(indices),args.batch_size):
            batch=noisy_batch(data,indices[offset:offset+args.batch_size],rng,rotate=True)
            output=model(torch.from_numpy(batch["features"]),torch.from_numpy(batch["padding"]))[:,:12]
            moving=torch.from_numpy(batch["moving"]).float()
            target=torch.from_numpy(batch["target"])
            pos_loss=((output[:,:,:2]-target[:,:,:2])*3).pow(2).sum(-1)
            angle_loss=(output[:,:,2:]-target[:,:,2:]).pow(2).sum(-1)
            loss=((pos_loss+.4*angle_loss)*moving).sum()/moving.sum().clamp_min(1)
            optimizer.zero_grad(set_to_none=True); loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(),1.0); optimizer.step()
            losses.append(float(loss.detach())); steps+=1
        model.eval()
        # Validation is finite and batch-size independent; test never used here.
        pieces=[]
        for offset in range(0,len(val),args.batch_size):
            sub={k:v[offset:offset+args.batch_size] for k,v in fixed_val.items()}
            pieces.append(predict(model,sub))
        val_pos=np.concatenate([p[0] for p in pieces]); val_angle=np.concatenate([p[1] for p in pieces])
        evaluation=metrics(val_pos,val_angle,fixed_val)
        score=evaluation["position_mae_m"]+evaluation["angle_mae_deg"]/180
        row={"epoch":epoch,"train_loss":float(np.mean(losses)),"validation":evaluation,
             "seconds":round(previous_seconds+time.perf_counter()-start,2),"steps":steps}
        history.append(row)
        print(json.dumps(row),flush=True)
        if score < best:
            best=score; stale=0
            temporary=model_dir/"layout_denoiser.tmp"
            torch.save({"state_dict":model.state_dict(),"hidden":64,"layers":2,
                        "epoch":epoch,"seed":args.seed},temporary)
            temporary.replace(model_dir/"layout_denoiser.pt")
            best_epoch=epoch; best_metrics=evaluation
        else:
            stale+=1
        (experiment_dir/"training_history.json").write_text(json.dumps(history,indent=2),encoding="utf-8")
        if stale>=12 or time.perf_counter()-start>=args.max_seconds:
            break
        # CPU-friendly decay after the first 15 epochs.
        if epoch-initial_epoch in (15,30,45):
            for group in optimizer.param_groups: group["lr"]*=.65
    metadata={"trained":True,"trained_at":"2026-10-11","architecture":"set Transformer, hidden=64, layers=2, heads=4",
              "parameters":sum(p.numel() for p in model.parameters()),"train_rooms":len(train),"validation_rooms":len(val),
              "seed":args.seed,"epochs_run":len(history),"best_epoch":best_epoch,"steps":steps,
              "duration_seconds":round(previous_seconds+time.perf_counter()-start,2),"device":"cpu","threads":args.threads,
              "best_validation":best_metrics,"validation_identity":baseline,
              "noise_position_std_m":POSITION_NOISE,"noise_angle_std_deg":ANGLE_NOISE_DEG,
              "locks":"random probability 0..0.45; no noise applied to locked items; runtime forcibly preserves locks",
              "augmentation":"quarter-turn room rotations and online noise, after house split",
              "objective":"movable-item metre-squared coordinate loss + 0.4 trig orientation squared loss",
              "scope":"supervised denoising of existing bedroom coordinates, not from-scratch furniture selection or 3D reconstruction",
              "code_sha256": {"training":hashlib.file_digest(Path(__file__).open("rb"),"sha256").hexdigest(),
                               "model":hashlib.file_digest((APP/"backend/roomwise/learning.py").open("rb"),"sha256").hexdigest()},
              "checkpoint_sha256":hashlib.file_digest((model_dir/"layout_denoiser.pt").open("rb"),"sha256").hexdigest()}
    stages=previous.get("training_stages",[]) if previous else []
    if previous and not stages:
        stages=[{"epochs":previous["epochs_run"],"seconds":previous["duration_seconds"],"checkpoint_sha256":previous["checkpoint_sha256"],
                 "initial_lr":.0015,"resumed":False}]
    stages.append({"epochs":len(history)-initial_epoch,"seconds":round(time.perf_counter()-start,2),
                   "checkpoint_sha256":metadata["checkpoint_sha256"],"initial_lr":.0003 if args.resume else .0015,"resumed":args.resume,
                   "optimiser_reset":args.resume,"resume_from_best_epoch":previous["best_epoch"] if previous else None})
    metadata["training_stages"]=stages
    (model_dir/"layout_denoiser.json").write_text(json.dumps(metadata,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({"saved":str(model_dir/"layout_denoiser.pt"),"metadata":metadata},ensure_ascii=False),flush=True)


if __name__=="__main__": main()

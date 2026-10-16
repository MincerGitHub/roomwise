"""Read the author-provided LEGO-Net bedroom archive without pickle or extraction.

Only non-augmented bedroom rooms are used. A deterministic house-level split is
made BEFORE any noise augmentation. The local numeric cache stays outside app.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path
import zipfile

import numpy as np

APP = Path(__file__).resolve().parents[2]
PROJECT = APP.parent
CATEGORIES = ["armchair", "bookshelf", "cabinet", "chair", "children_cabinet",
              "coffee_table", "desk", "double_bed", "dressing_chair", "dressing_table",
              "kids_bed", "nightstand", "shelf", "single_bed", "sofa", "stool", "table",
              "tv_stand", "wardrobe"]
MAX_ITEMS = 12
BOUNDARY_POINTS = 12


def sample_boundary(polygon: np.ndarray, count: int = BOUNDARY_POINTS) -> np.ndarray:
    polygon = np.asarray(polygon, dtype=np.float32)
    if np.linalg.norm(polygon[0] - polygon[-1]) < 1e-5:
        polygon = polygon[:-1]
    edges = np.roll(polygon, -1, axis=0) - polygon
    lengths = np.linalg.norm(edges, axis=1)
    total = float(lengths.sum())
    if total < 0.01:
        raise ValueError("degenerate polygon")
    cumulative = np.concatenate([[0.0], np.cumsum(lengths)])
    distances = np.arange(count) * total / count
    result = []
    for d in distances:
        idx = min(int(np.searchsorted(cumulative, d, side="right") - 1), len(edges)-1)
        result.append(polygon[idx] + edges[idx] * ((d - cumulative[idx]) / max(lengths[idx], 1e-8)))
    return np.asarray(result, dtype=np.float32)


def house_split(house: str) -> int:
    # Hash, not source room split: several rooms may share one residential house.
    value = int(hashlib.sha256(("roomwise-house-2026:" + house).encode()).hexdigest()[:8], 16) / 2**32
    return 0 if value < .75 else (1 if value < .875 else 2)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=Path, default=PROJECT / "data/LEGO-Net/3DFRONT_65347.zip")
    parser.add_argument("--output", type=Path, default=PROJECT / "data/Roomwise/bedrooms_prepared.npz")
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    rows, rejected = [], []
    with zipfile.ZipFile(args.archive) as archive:
        members = sorted(m for m in archive.namelist()
                         if "/processed_bedroom/" in m and m.endswith("/boxes.npz")
                         and not m.startswith("__MACOSX"))
        for member in members:
            try:
                with np.load(io.BytesIO(archive.read(member)), allow_pickle=False) as a:
                    n = len(a["translations"])
                    if not 1 <= n <= MAX_ITEMS:
                        raise ValueError(f"object count {n}")
                    # Source translations and ordered floor corners are both centered,
                    # in metres. Source sizes are HALF bounding-box extents.
                    pos = np.asarray(a["translations"][:, [0, 2]], dtype=np.float32)
                    size = np.asarray(a["sizes"][:, [0, 2, 1]] * 2, dtype=np.float32)
                    angle = np.asarray(a["angles"], dtype=np.float32).reshape(n)
                    classes = np.argmax(a["class_labels"][:, :19], axis=1).astype(np.int64)
                    polygon = np.asarray(a["floor_plan_ordered_corners"], dtype=np.float32)
                    if len(polygon) < 3 or not all(np.isfinite(x).all() for x in (pos, size, angle, polygon)):
                        raise ValueError("invalid arrays")
                    if (size <= 0).any():
                        raise ValueError("non-positive size")
                    # Recenter by polygon bounding box so runtime [0,width] coordinates
                    # map consistently, including non-symmetric floor outlines.
                    lower, upper = polygon.min(axis=0), polygon.max(axis=0)
                    center = (lower + upper) / 2
                    dims = upper - lower
                    if (dims < 1).any() or (dims > 12).any():
                        raise ValueError(f"unreasonable room bounds {dims.tolist()}")
                    house = str(a["json_path"])
                    padded_pos, padded_size = np.zeros((MAX_ITEMS, 2), np.float32), np.zeros((MAX_ITEMS, 3), np.float32)
                    padded_angle, padded_classes = np.zeros(MAX_ITEMS, np.float32), np.full(MAX_ITEMS, -1, np.int64)
                    padded_pos[:n], padded_size[:n] = pos-center, size
                    padded_angle[:n], padded_classes[:n] = angle, classes
                    rows.append(dict(pos=padded_pos, size=padded_size, angle=padded_angle,
                                     classes=padded_classes, boundary=sample_boundary(polygon-center),
                                     dims=dims, n=n, house=house, room=member.split("/")[-2],
                                     split=house_split(house), polygon=(polygon-center).tolist()))
            except (ValueError, KeyError) as exc:
                rejected.append({"member": member, "reason": str(exc)})
    if not rows:
        raise RuntimeError("No valid bedroom records")
    fields = ("pos", "size", "angle", "classes", "boundary", "dims", "n", "house", "room", "split")
    np.savez_compressed(args.output, **{f: np.asarray([r[f] for r in rows]) for f in fields})
    houses = [set(r["house"] for r in rows if r["split"] == k) for k in range(3)]
    intersections = [len(houses[a] & houses[b]) for a,b in ((0,1),(0,2),(1,2))]
    manifest = {
        "source": "LEGO-Net author preprocessed 3D-FRONT bedrooms; non-augmented boxes.npz",
        "source_url": "https://ivl.cs.brown.edu/research/lego-net.html",
        "archive_sha256": hashlib.file_digest(args.archive.open("rb"), "sha256").hexdigest(),
        "archive_records": len(members), "accepted_rooms": len(rows), "rejected": rejected,
        "categories": CATEGORIES, "house_split_seed": "roomwise-house-2026",
        "splits": {name: {"rooms": sum(r["split"] == k for r in rows), "houses": len(houses[k])}
                   for k,name in enumerate(("train", "validation", "test"))},
        "category_counts": {
            name: {category: sum(int(np.sum(r["classes"] == c)) for r in rows if r["split"] == k)
                   for c,category in enumerate(CATEGORIES)}
            for k,name in enumerate(("train", "validation", "test"))},
        "house_intersections": intersections, "size_conversion": "width/depth/height = source sizes[x/z/y] * 2",
        "rotation": "source angles in radians -> Three.js positive-y yaw in degrees, NOT negated",
        "position": "source translations[x/z] minus floor-polygon bounding-box center; metres",
        "model_scope": "19 bedroom categories; coordinate/orientation denoising, no mesh reconstruction",
        "cache": str(args.output), "redistribution": "Local restricted dataset cache; do not redistribute raw arrays",
    }
    experiment_dir = APP / "artifacts/experiments"
    experiment_dir.mkdir(parents=True, exist_ok=True)
    (experiment_dir / "data_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    # Keep polygon outlines locally for geometric tests, not shipped in artifacts.
    args.output.with_suffix(".polygons.json").write_text(json.dumps([r["polygon"] for r in rows]), encoding="utf-8")
    print(json.dumps({"rooms": len(rows), "split": manifest["splits"], "house_intersections": intersections}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()

"""Small, locally trained bedroom-layout denoiser; immutable item attributes.

The network is permutation-equivariant over furniture tokens. Floor boundary
tokens provide room context. It predicts coordinate and orientation corrections;
geometry validation is a separate program responsibility.
"""
from __future__ import annotations

import copy
from functools import lru_cache
import json
import math
from pathlib import Path
from typing import Any

import numpy as np

APP = Path(__file__).resolve().parents[2]
MODEL_PATH = APP / "artifacts/models/layout_denoiser.pt"
META_PATH = APP / "artifacts/models/layout_denoiser.json"
CATEGORIES = ["armchair", "bookshelf", "cabinet", "chair", "children_cabinet", "coffee_table",
              "desk", "double_bed", "dressing_chair", "dressing_table", "kids_bed", "nightstand",
              "shelf", "single_bed", "sofa", "stool", "table", "tv_stand", "wardrobe"]
FEATURE_DIM = 32
BOUNDARY_POINTS = 12
MAX_RUNTIME_ITEMS = 32

try:
    import torch
    from torch import nn
except ImportError:
    torch = None
    nn = None


if nn is not None:
    class LayoutDenoiser(nn.Module):
        def __init__(self, hidden: int = 64, layers: int = 2) -> None:
            super().__init__()
            self.embedding = nn.Sequential(nn.Linear(FEATURE_DIM, hidden), nn.GELU(), nn.LayerNorm(hidden))
            layer = nn.TransformerEncoderLayer(hidden, 4, hidden*2, dropout=.05, activation="gelu",
                                               batch_first=True, norm_first=True)
            self.encoder = nn.TransformerEncoder(layer, layers, enable_nested_tensor=False)
            self.head = nn.Sequential(nn.Linear(hidden, hidden), nn.GELU(), nn.Linear(hidden, 4))
            nn.init.zeros_(self.head[-1].weight)
            nn.init.zeros_(self.head[-1].bias)

        def forward(self, features, padding_mask):
            encoded = self.encoder(self.embedding(features), src_key_padding_mask=padding_mask)
            return self.head(encoded)
else:
    class LayoutDenoiser:
        def __init__(self, *args, **kwargs):
            raise RuntimeError("CPU PyTorch is not installed; model mode is unavailable.")


def boundary_points(polygon: np.ndarray, count: int = BOUNDARY_POINTS) -> np.ndarray:
    if np.linalg.norm(polygon[0] - polygon[-1]) < 1e-5:
        polygon = polygon[:-1]
    vectors = np.roll(polygon, -1, axis=0) - polygon
    lengths = np.linalg.norm(vectors, axis=1)
    cumulative = np.concatenate([[0.0], np.cumsum(lengths)])
    total = cumulative[-1]
    result = []
    for distance in np.arange(count) * total / count:
        edge = min(np.searchsorted(cumulative, distance, side="right") - 1, len(vectors)-1)
        result.append(polygon[edge] + vectors[edge] * (distance-cumulative[edge]) / max(lengths[edge], 1e-8))
    return np.asarray(result, dtype=np.float32)


def make_features(pos, angle, sizes, classes, locked, mask, boundary, dims):
    """Vectorised numpy batch encoding. Coordinates and dimensions in metres."""
    batch, count = pos.shape[:2]
    features = np.zeros((batch, count+BOUNDARY_POINTS, FEATURE_DIM), dtype=np.float32)
    features[:, :count, :2] = pos / 3.0
    features[:, :count, 2] = np.cos(angle)
    features[:, :count, 3] = np.sin(angle)
    features[:, :count, 4:7] = sizes / 3.0
    for b in range(batch):
        valid_indices = np.flatnonzero(mask[b])
        features[b, valid_indices, 7+classes[b, valid_indices]] = 1
    features[:, :count, 26] = locked
    features[:, :count, 27] = 1 # furniture token
    features[:, count:, :2] = boundary / 3.0
    features[:, count:, 28] = 1 # boundary token
    features[:, :, 29:31] = dims[:, None, :] / 6.0
    features[:, :, 31] = mask.sum(axis=1)[:, None] / 12.0
    padding = np.concatenate([~mask.astype(bool), np.zeros((batch, BOUNDARY_POINTS), bool)], axis=1)
    return features, padding


def _load_model():
    if torch is None or not MODEL_PATH.exists():
        return None
    # A server started before training finishes must detect the new checkpoint.
    return _cached_model(MODEL_PATH.stat().st_mtime_ns)


def resolve_device(requested: str = "cpu"):
    """Choose a device explicitly; the web application's default stays CPU.

    Do not automatically claim CUDA support or silently fall back from an
    explicitly requested GPU. Merely importing this module does not initialise
    a CUDA context, which matters when a separate acquisition job owns the GPU.
    """
    if torch is None:
        raise RuntimeError("PyTorch is not installed.")
    if requested not in ("cpu", "cuda"):
        raise ValueError("Device must be cpu or cuda.")
    if requested == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA was explicitly requested, but PyTorch cannot use a GPU.")
    return torch.device(requested)


def load_checkpoint(checkpoint_path: Path, device: str = "cpu"):
    """Load an explicitly named research checkpoint, independently of the API cache."""
    selected = resolve_device(device)
    checkpoint = torch.load(checkpoint_path, map_location="cpu", weights_only=True)
    model = LayoutDenoiser(hidden=checkpoint.get("hidden", 64), layers=checkpoint.get("layers", 2))
    model.load_state_dict(checkpoint["state_dict"])
    model.to(selected)
    model.eval()
    return model


@lru_cache(maxsize=1)
def _cached_model(checkpoint_mtime: int):
    torch.set_num_threads(min(4, torch.get_num_threads()))
    return load_checkpoint(MODEL_PATH, "cpu")


def model_status() -> dict[str, Any]:
    model = _load_model()
    meta = json.loads(META_PATH.read_text(encoding="utf-8")) if META_PATH.exists() else {}
    return {"available": model is not None, "loaded": model is not None,
            "architecture": "2-layer 64-dimensional set Transformer",
            "checkpoint": MODEL_PATH.name if MODEL_PATH.exists() else None,
            "scope": "卧室家具位置与朝向去噪；不生成网格、不保证几何可行",
            "training": meta,
            "limitation": "主要训练类别是床、床头柜、衣柜；任意组合及大幅搬家重排仍需约束检查"}


def experiments_summary() -> dict[str, Any]:
    directory = APP / "artifacts/experiments"
    payload: dict[str, Any] = {"available": False, "model": model_status(), "summary": []}
    for key, filename in (("data", "data_manifest.json"), ("evaluation", "heldout_metrics.json")):
        path = directory / filename
        if path.exists():
            payload[key] = json.loads(path.read_text(encoding="utf-8"))
    if "evaluation" in payload:
        payload["available"] = True
        for level in payload["evaluation"]["levels"]:
            methods = level["methods"]
            base, model = methods["identity"], methods["model_3_steps"]
            reduction = 100*(base["position_mae_m"]-model["position_mae_m"])/max(base["position_mae_m"],1e-9)
            payload["summary"].append({"noise_m": level["position_noise_std_m"],
                                       "position_error_reduction_percent": round(reduction,2),
                                       "input_mae_m": base["position_mae_m"],
                                       "model_mae_m": model["position_mae_m"],
                                       "rule_mae_m": methods["rule"]["position_mae_m"]})
    else:
        payload["message"] = "独立测试尚未完成；当前不展示推测成绩。"
    return payload


def refine_scene(scene: dict, iterations: int = 3) -> dict:
    model = _load_model()
    if model is None:
        raise RuntimeError("布局模型尚未可用；请先运行训练脚本或选择规则模式。")
    result = copy.deepcopy(scene)
    items = result.get("items", [])
    indices = [i for i, item in enumerate(items) if item.get("category") in CATEGORIES]
    if not indices:
        return result
    if len(indices) > MAX_RUNTIME_ITEMS:
        raise ValueError("模型模式最多支持32件可识别家具。")
    room = result["room"]
    width, depth = float(room["width"]), float(room["depth"])
    center = np.array([width/2, depth/2], np.float32)
    polygon = room.get("polygon")
    if polygon:
        polygon = np.asarray([[v["x"], v["z"]] if isinstance(v, dict) else v for v in polygon], np.float32)
    else:
        polygon = np.array([[0, 0], [width, 0], [width, depth], [0, depth]], np.float32)
    boundary = boundary_points(polygon-center)[None]
    selected = [items[i] for i in indices]
    pos = np.array([[i["x"], i["z"]] for i in selected], np.float32)[None]-center
    angle = np.radians(np.array([i.get("rotation", 0) for i in selected], np.float32))[None]
    sizes = np.array([[i["width"], i["depth"], i["height"]] for i in selected], np.float32)[None]
    classes = np.array([[CATEGORIES.index(i["category"]) for i in selected]], np.int64)
    locked = np.array([[bool(i.get("locked", False)) for i in selected]])
    mask = np.ones((1, len(selected)), bool)
    dims = np.array([[width, depth]], np.float32)
    original_pos, original_angle = pos.copy(), angle.copy()
    # Conservative iterations: a denoising network has no proof of convergence.
    with torch.inference_mode():
        for step in range(max(1, min(iterations, 5))):
            feat, padding = make_features(pos, angle, sizes, classes, locked, mask, boundary, dims)
            output = model(torch.from_numpy(feat), torch.from_numpy(padding)).numpy()[:, :len(selected)]
            gain = (.8, .4, .2, .1, .1)[step]
            displacement = np.clip(output[:, :, :2]*3, -.7, .7) * gain
            orientation = np.stack([np.cos(angle), np.sin(angle)], axis=-1) + output[:, :, 2:]*gain
            predicted_angle = np.arctan2(orientation[:, :, 1], orientation[:, :, 0])
            angular_delta = (predicted_angle-angle+np.pi) % (2*np.pi)-np.pi
            pos += displacement * (~locked)[..., None]
            angle += np.clip(angular_delta, -np.pi/4, np.pi/4) * (~locked)
            pos[locked], angle[locked] = original_pos[locked], original_angle[locked]
    for index, p, a in zip(indices, pos[0]+center, angle[0]):
        if not items[index].get("locked", False):
            items[index]["x"] = round(float(p[0]), 5)
            items[index]["z"] = round(float(p[1]), 5)
            items[index]["rotation"] = round(float(np.degrees(a) % 360), 3)
    return result

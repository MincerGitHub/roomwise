"""Bounded local video-assisted furniture intake.

The detector produces provisional candidates, not an inventory or 3D scan.
Short-lived IoU tracks reduce adjacent-frame duplicates only. No physical size
or room coordinate is inferred. Every candidate requires human confirmation.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import dataclass
import math
from pathlib import Path
import re
import threading
import time
from typing import Any
import uuid


APP_ROOT = Path(__file__).resolve().parents[2]
UPLOADS_ROOT = APP_ROOT / "runtime" / "uploads"
DETECTOR_ROOT = APP_ROOT / "artifacts" / "detectors"
MODEL_PATH = DETECTOR_ROOT / "yolox_tiny.onnx"
MAX_BYTES = 100 * 1024 * 1024
MAX_SECONDS = 120.0
MAX_VIDEO_FRAMES = 7200
MAX_KEYFRAMES = 32
MAX_FRAME_PIXELS = 3840 * 2160
MAX_ACTIVE_JOBS = 4
MAX_RETAINED_JOBS = 24
EXTENSIONS = {".mp4", ".mov", ".avi", ".webm", ".mkv", ".m4v"}
LIMITATIONS = [
    "候选物品须人工确认类别、数量、真实尺寸、房内位置和保留状态。",
    "仅识别COCO中的椅子、沙发、床和餐桌；柜子、窗帘等需手动补录。",
    "仅使用短时二维框关联；镜头离开后再拍同一家具可能产生重复，必须人工合并。",
    "视频不提供绝对尺度、精确房间坐标或可独立拖动的完整三维网格。",
    "通用预训练检测器并未在本项目真实搬家视频上验证准确率。",
]
COCO_FURNITURE = {
    56: ("chair", "椅子"),
    57: ("sofa", "沙发"),
    59: ("double_bed", "床（单/双人类型待确认）"),
    60: ("table", "餐桌（用途待确认）"),
}
_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="roomwise-video")
_jobs: dict[str, dict[str, Any]] = {}
_roots: dict[str, Path] = {}
_jobs_lock = threading.RLock()
_detector_lock = threading.Lock()
_detector: Any = None
_detector_signature: Any = None
_detector_error: str | None = None


def _cv_dependencies():
    try:
        import cv2
        import numpy as np
    except ImportError as exc:
        raise ValueError("视频抽帧依赖未安装，请运行项目安装步骤。") from exc
    return cv2, np


def _iou(a: list[float], b: list[float]) -> float:
    left, top = max(a[0], b[0]), max(a[1], b[1])
    right, bottom = min(a[2], b[2]), min(a[3], b[3])
    intersection = max(0.0, right - left) * max(0.0, bottom - top)
    area_a = max(0.0, a[2] - a[0]) * max(0.0, a[3] - a[1])
    area_b = max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])
    union = area_a + area_b - intersection
    return intersection / union if union > 0 else 0.0


class YoloXTinyDetector:
    """Official YOLOX ONNX decoding, with only four furniture classes exposed.

    Preprocessing: unchanged BGR values, top-left 114 padding, CHW float32.
    Source: YOLOX demo/ONNXRuntime and yolox/utils/demo_utils.py (Apache-2.0).
    """

    def __init__(self, path: Path):
        import onnxruntime as ort

        options = ort.SessionOptions()
        options.intra_op_num_threads = 2
        options.inter_op_num_threads = 1
        self.session = ort.InferenceSession(str(path), sess_options=options, providers=["CPUExecutionProvider"])
        input_info = self.session.get_inputs()[0]
        shape = input_info.shape
        if len(shape) != 4 or shape[1] != 3 or not isinstance(shape[2], int) or not isinstance(shape[3], int):
            raise ValueError("检测模型输入结构不受支持。")
        self.input_name = input_info.name
        self.height, self.width = int(shape[2]), int(shape[3])
        if self.height != 416 or self.width != 416:
            raise ValueError("检测模型尺寸与YOLOX-Tiny配置不一致。")
        _, np = _cv_dependencies()
        grid_parts, stride_parts = [], []
        for stride in (8, 16, 32):
            gx, gy = np.meshgrid(np.arange(self.width // stride), np.arange(self.height // stride))
            grid = np.stack((gx, gy), axis=2).reshape(-1, 2)
            grid_parts.append(grid)
            stride_parts.append(np.full((len(grid), 1), stride))
        self.grid = np.concatenate(grid_parts).astype(np.float32)
        self.strides = np.concatenate(stride_parts).astype(np.float32)

    def detect(self, frame, threshold: float = 0.40) -> list[dict[str, Any]]:
        cv2, np = _cv_dependencies()
        image_height, image_width = frame.shape[:2]
        ratio = min(self.height / image_height, self.width / image_width)
        resized = cv2.resize(frame, (max(1, int(image_width * ratio)), max(1, int(image_height * ratio))))
        padded = np.full((self.height, self.width, 3), 114, dtype=np.uint8)
        padded[:resized.shape[0], :resized.shape[1]] = resized
        tensor = np.ascontiguousarray(padded.transpose(2, 0, 1)[None], dtype=np.float32)
        output = self.session.run(None, {self.input_name: tensor})[0]
        if output.ndim != 3 or output.shape != (1, len(self.grid), 85):
            raise ValueError("检测模型输出结构不受支持。")
        pred = output[0].copy()
        if not np.isfinite(pred).all():
            raise ValueError("检测模型返回无效数值。")
        pred[:, :2] = (pred[:, :2] + self.grid) * self.strides
        pred[:, 2:4] = np.exp(np.clip(pred[:, 2:4], -20, 20)) * self.strides
        scores = pred[:, 4:5] * pred[:, 5:]
        classes = scores.argmax(axis=1)
        best_scores = scores[np.arange(len(pred)), classes]
        mask = (best_scores >= threshold) & np.isin(classes, list(COCO_FURNITURE))
        detections = []
        for index in np.flatnonzero(mask):
            cx, cy, width, height = pred[index, :4] / ratio
            bbox = [
                float(np.clip((cx - width / 2) / image_width, 0, 1)),
                float(np.clip((cy - height / 2) / image_height, 0, 1)),
                float(np.clip((cx + width / 2) / image_width, 0, 1)),
                float(np.clip((cy + height / 2) / image_height, 0, 1)),
            ]
            if bbox[2] <= bbox[0] or bbox[3] <= bbox[1]:
                continue
            category, label = COCO_FURNITURE[int(classes[index])]
            source_class = {56: "chair", 57: "couch", 59: "bed", 60: "dining table"}[int(classes[index])]
            detections.append({"bbox": bbox, "confidence": float(best_scores[index]), "category": category, "label": label, "detectedClass": source_class})
        # Greedy, class-aware NMS. Deliberately do not convert unknown classes.
        detections.sort(key=lambda d: d["confidence"], reverse=True)
        result = []
        for detection in detections:
            if not any(detection["category"] == existing["category"] and _iou(detection["bbox"], existing["bbox"]) > 0.45 for existing in result):
                result.append(detection)
            if len(result) >= 20:
                break
        return result


def _get_detector():
    global _detector, _detector_signature, _detector_error
    signature = (MODEL_PATH.exists(), MODEL_PATH.stat().st_mtime_ns if MODEL_PATH.exists() else None)
    with _detector_lock:
        if signature == _detector_signature:
            return _detector
        _detector_signature = signature
        _detector = None
        _detector_error = None
        if not signature[0]:
            _detector_error = "未下载检测权重：仅提供关键帧，支持手工录入。"
            return None
        try:
            _detector = YoloXTinyDetector(MODEL_PATH)
        except ImportError:
            _detector_error = "检测依赖未安装：仅提供关键帧，支持手工录入。"
        except Exception:
            _detector_error = "检测模型未能加载：仅提供关键帧，支持手工录入。"
        return _detector


def video_status() -> dict[str, Any]:
    detector = _get_detector()
    return {
        "available": detector is not None,
        "detectorUnavailable": detector is None,
        "name": "YOLOX-Tiny (COCO pretrained)" if detector is not None else "none",
        "source": "https://github.com/Megvii-BaseDetection/YOLOX",
        "repositoryLicense": "Apache-2.0",
        "categoryCoverage": ["chair", "sofa", "bed", "dining_table"],
        "trainedByTeam": False,
        "message": _detector_error or "检测候选需要人工确认。",
        "limits": {"maxBytes": MAX_BYTES, "maxSeconds": MAX_SECONDS, "maxFrames": MAX_KEYFRAMES},
        "limitations": list(LIMITATIONS),
    }


@dataclass
class _Track:
    id: str
    category: str
    bbox: list[float]
    last_timestamp: float
    candidate: dict[str, Any]
    observations: int = 1


class ShortTracker:
    """Adjacent-view deduplication, NOT camera-independent identity tracking."""

    def __init__(self, max_gap: float = 4.5, min_iou: float = 0.30):
        self.max_gap = max_gap
        self.min_iou = min_iou
        self.tracks: list[_Track] = []

    def update(self, detections: list[dict[str, Any]], timestamp: float, frame_url: str) -> None:
        used: set[str] = set()
        for detection in sorted(detections, key=lambda d: d["confidence"], reverse=True):
            matches = [track for track in self.tracks if track.id not in used and track.category == detection["category"] and 0 <= timestamp - track.last_timestamp <= self.max_gap]
            track = max(matches, key=lambda t: _iou(t.bbox, detection["bbox"]), default=None)
            if track is None or _iou(track.bbox, detection["bbox"]) < self.min_iou:
                track_id = f"candidate-{len(self.tracks) + 1}"
                candidate = {
                    "trackId": track_id,
                    **deepcopy(detection),
                    "frameUrl": frame_url,
                    "timestamp": timestamp,
                    "bboxFormat": "normalized_xyxy",
                    "requiresConfirmation": True,
                    "dimensions": None,
                    "roomPosition": None,
                    "observations": 1,
                }
                track = _Track(track_id, detection["category"], detection["bbox"], timestamp, candidate)
                self.tracks.append(track)
            else:
                track.observations += 1
                track.bbox = list(detection["bbox"])
                track.last_timestamp = timestamp
                if detection["confidence"] > track.candidate["confidence"]:
                    track.candidate.update(deepcopy(detection), frameUrl=frame_url, timestamp=timestamp)
                track.candidate["observations"] = track.observations
            used.add(track.id)

    def candidates(self) -> list[dict[str, Any]]:
        return [deepcopy(track.candidate) for track in self.tracks]


def _update_job(job_id: str, **fields: Any) -> None:
    with _jobs_lock:
        _jobs[job_id].update(fields)


def _safe_video_path(path: Path, uploads_root: Path) -> Path:
    path = Path(path).resolve(strict=True)
    root = uploads_root.resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError("视频文件必须位于项目上传目录。")
    if path.suffix.lower() not in EXTENSIONS:
        raise ValueError("不支持此视频格式，请使用MP4、MOV、AVI或WebM。")
    if path.stat().st_size > MAX_BYTES:
        raise ValueError("视频不能超过100MB。")
    if path.stat().st_size == 0:
        raise ValueError("视频文件为空。")
    return path


def start_analysis(path: Path | str, uploads_root: Path | str | None = None, job_id: str | None = None) -> str:
    root = Path(uploads_root).resolve() if uploads_root is not None else UPLOADS_ROOT.resolve()
    path = _safe_video_path(Path(path), root)
    job_id = job_id or uuid.uuid4().hex
    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", job_id):
        raise ValueError("无效任务编号。")
    with _jobs_lock:
        if job_id in _jobs:
            raise ValueError("任务编号已存在。")
        active = sum(job["status"] in {"queued", "processing"} for job in _jobs.values())
        if active >= MAX_ACTIVE_JOBS:
            raise ValueError("视频分析队列已满，请稍后重试。")
        while len(_jobs) >= MAX_RETAINED_JOBS:
            completed = next((key for key, job in _jobs.items() if job["status"] in {"complete", "failed"}), None)
            if completed is None:
                break
            _jobs.pop(completed)
            _roots.pop(completed, None)
        _jobs[job_id] = {
            "jobId": job_id,
            "status": "queued",
            "progress": 0,
            "frames": [],
            "candidates": [],
            "detector": {"available": False, "name": "pending"},
            "limitations": list(LIMITATIONS),
            "requiresConfirmation": True,
            "createdAt": time.time(),
        }
        _roots[job_id] = root
    _executor.submit(_analyze, path, root, job_id)
    return job_id


def submit_video(path: Path | str, job_id: str | None = None) -> str:
    return start_analysis(path, job_id=job_id)


def get_job(job_id: str) -> dict[str, Any] | None:
    with _jobs_lock:
        return deepcopy(_jobs.get(job_id))


def get_frame_path(job_id: str, filename: str) -> Path | None:
    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", job_id) or not re.fullmatch(r"frame-[0-9]{3}\.jpg", filename):
        return None
    with _jobs_lock:
        root = _roots.get(job_id)
    if root is None:
        return None
    frame_root = (root / "video_frames" / job_id).resolve()
    path = (frame_root / filename).resolve()
    return path if path.is_relative_to(frame_root) and path.is_file() else None


def _analyze(path: Path, root: Path, job_id: str) -> None:
    capture = None
    try:
        cv2, np = _cv_dependencies()
        _update_job(job_id, status="processing", progress=0.02)
        capture = cv2.VideoCapture(str(path))
        if not capture.isOpened():
            raise ValueError("无法解码视频，请转换为常见H.264 MP4格式后重试。")
        fps = float(capture.get(cv2.CAP_PROP_FPS))
        frame_count = float(capture.get(cv2.CAP_PROP_FRAME_COUNT))
        width = float(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = float(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
        if not all(math.isfinite(value) and value > 0 for value in (fps, frame_count, width, height)):
            raise ValueError("无法确认视频帧数或时长，请转换为MP4后重试。")
        duration = frame_count / fps
        if duration > MAX_SECONDS + 0.01 or frame_count > MAX_VIDEO_FRAMES:
            raise ValueError("视频不能超过120秒或7200帧，请截取较短片段。")
        if width * height > MAX_FRAME_PIXELS:
            raise ValueError("视频分辨率过高，请转为1080p或较低分辨率。")
        _update_job(job_id, video={"duration": round(duration, 3), "fps": fps, "width": int(width), "height": int(height), "frameCount": int(frame_count)})
        folder = root / "video_frames" / job_id
        folder.mkdir(parents=True, exist_ok=True)
        sample_count = min(MAX_KEYFRAMES, max(1, math.ceil(duration / 1.0)))
        centers = np.linspace(0, max(0, frame_count - 1), sample_count).astype(int)
        selected = []
        previous_thumbnail = None
        for sample_index, center in enumerate(centers):
            best = None
            # At most three decode operations per temporal sample, choose sharpest.
            offsets = sorted({int(max(0, min(frame_count - 1, center + offset))) for offset in (-fps * 0.12, 0, fps * 0.12)})
            for index in offsets:
                capture.set(cv2.CAP_PROP_POS_FRAMES, index)
                success, frame = capture.read()
                if not success or frame is None:
                    continue
                if max(frame.shape[:2]) > 1280:
                    resize_ratio = 1280 / max(frame.shape[:2])
                    frame = cv2.resize(frame, (max(1, int(frame.shape[1] * resize_ratio)), max(1, int(frame.shape[0] * resize_ratio))))
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                sharpness = float(cv2.Laplacian(gray, cv2.CV_32F).var())
                if best is None or sharpness > best[0]:
                    best = (sharpness, frame, index / fps, gray)
            if best is not None:
                sharpness, frame, timestamp, gray = best
                thumbnail = cv2.resize(gray, (64, 48)).astype(np.float32)
                # Drop only near-identical adjacent views. No claim of object dedup here.
                difference = float(np.abs(thumbnail - previous_thumbnail).mean()) if previous_thumbnail is not None else math.inf
                if previous_thumbnail is None or difference >= 2.0:
                    selected.append((sharpness, frame, timestamp))
                    previous_thumbnail = thumbnail
            _update_job(job_id, progress=round(0.05 + 0.30 * (sample_index + 1) / sample_count, 3))
        if not selected:
            raise ValueError("未提取到可解码的画面，请换一个视频重试。")
        detector = _get_detector()
        status = video_status()
        _update_job(job_id, detector=status, detectorUnavailable=detector is None)
        tracker = ShortTracker(max_gap=max(4.5, duration / max(1, sample_count - 1) * 1.5))
        frames = []
        detector_failure = False
        for index, (sharpness, frame, timestamp) in enumerate(selected):
            filename = f"frame-{index:03d}.jpg"
            success, encoded = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 88])
            if not success:
                continue
            (folder / filename).write_bytes(encoded.tobytes())
            url = f"/uploads/video_frames/{job_id}/{filename}"
            info = {"id": f"frame-{index}", "url": url, "timestamp": round(timestamp, 3), "sharpness": round(sharpness, 3), "width": int(frame.shape[1]), "height": int(frame.shape[0])}
            frames.append(info)
            if detector is not None:
                try:
                    detections = detector.detect(frame)
                    tracker.update(detections, timestamp, url)
                except Exception:
                    detector_failure = True
                    detector = None
                    status = {**status, "available": False, "detectorUnavailable": True, "message": "检测运行失败，已保留关键帧，可继续手工录入。"}
            _update_job(job_id, progress=round(0.35 + 0.63 * (index + 1) / len(selected), 3), frames=deepcopy(frames), candidates=tracker.candidates(), detector=status)
        _update_job(job_id, status="complete", progress=1, frames=frames, candidates=tracker.candidates(), detector=status, detectorUnavailable=detector is None, detectorPartial=detector_failure, completedAt=time.time())
    except ValueError as exc:
        _update_job(job_id, status="failed", progress=1, error=str(exc), completedAt=time.time())
    except Exception:
        _update_job(job_id, status="failed", progress=1, error="视频处理失败，请检查编码或使用较短的视频。", completedAt=time.time())
    finally:
        if capture is not None:
            capture.release()

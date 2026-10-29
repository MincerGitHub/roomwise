from __future__ import annotations

import json
import os
from pathlib import Path
import struct
import subprocess
import sys
from collections import deque
from queue import Empty, Queue
from threading import Lock, Thread


INSTANTMESH_ROOT = Path(__file__).resolve().parents[3] / "InstantMesh"
_worker = None
_worker_lock = Lock()


class ReconstructionError(Exception):
    pass


def reconstruction_python():
    active = Path(sys.executable).resolve()
    sibling = active.parent.parent / "instantmesh" / active.name
    return Path(os.getenv("ROOMWISE_INSTANTMESH_PYTHON", str(sibling))).resolve()


def reconstruction_status():
    root = Path(os.getenv("ROOMWISE_INSTANTMESH_ROOT", str(INSTANTMESH_ROOT))).resolve()
    python = reconstruction_python()
    ready = (root / "roomwise_worker.py").is_file() and (root / "configs/instant-mesh-base.yaml").is_file() and python.is_file()
    running = _worker is not None and _worker.root == root and _worker.python == python and _worker.process is not None and _worker.process.poll() is None
    if ready and not running:
        try:
            probe = subprocess.run([str(python), "-c", "import importlib.util; assert all(importlib.util.find_spec(name) for name in ('torch','diffusers','rembg','trimesh','onnxruntime'))"], capture_output=True, timeout=30, check=False)
            ready = probe.returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            ready = False
    return {"enabled": ready, "message": "InstantMesh 本地依赖已就绪；重建时需要 CUDA，首次使用需下载权重。" if ready else "InstantMesh 不可用；请检查依赖及 ROOMWISE_INSTANTMESH_PYTHON。"}


class InstantMeshWorker:
    def __init__(self, root, python):
        self.root = root
        self.python = python
        self.process = None
        self.responses = Queue()
        self.stderr_tail = deque(maxlen=20)

    def start(self):
        if self.process and self.process.poll() is None:
            return
        environment = os.environ.copy()
        environment.setdefault("HF_HOME", str(self.root / "ckpts" / "huggingface"))
        environment.setdefault("U2NET_HOME", str(self.root / "ckpts" / "u2net"))
        environment["PYTHONIOENCODING"] = "utf-8"
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        process = subprocess.Popen(
            [str(self.python), "roomwise_worker.py"], cwd=self.root, env=environment,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace", bufsize=1, creationflags=flags,
        )
        responses = Queue()
        self.process = process
        self.responses = responses
        self.stderr_tail.clear()
        Thread(target=self._read_stdout, args=(process, responses), daemon=True).start()
        Thread(target=self._read_stderr, args=(process,), daemon=True).start()
        try:
            response = responses.get(timeout=1800)
        except Empty as exc:
            self.stop()
            raise ReconstructionError("InstantMesh 常驻进程启动超时，请检查 GPU 和模型权重。") from exc
        if not response.get("ready"):
            self.stop()
            raise ReconstructionError("InstantMesh 常驻进程启动失败，请检查 GPU 和模型权重。")

    def _read_stdout(self, process, responses):
        try:
            for line in process.stdout:
                try:
                    responses.put(json.loads(line))
                except json.JSONDecodeError:
                    continue
        finally:
            responses.put({"ok": False, "error": "InstantMesh 常驻进程已退出。"})

    def _read_stderr(self, process):
        for line in process.stderr:
            self.stderr_tail.append(line.rstrip())

    def request(self, photos, output):
        self.start()
        if not self.process or not self.process.stdin:
            raise ReconstructionError("InstantMesh 常驻进程不可用。")
        try:
            self.process.stdin.write(json.dumps({"photos": [str(Path(photo).resolve()) for photo in photos], "output": str(Path(output).resolve())}, ensure_ascii=False) + "\n")
            self.process.stdin.flush()
            response = self.responses.get(timeout=1800)
        except (BrokenPipeError, OSError, Empty) as exc:
            self.stop()
            raise ReconstructionError("InstantMesh 常驻进程中断或超时，请重试。") from exc
        if not response.get("ok"):
            self.stop()
            diagnostic = str(response.get("error", "")) + "\n" + "\n".join(self.stderr_tail)
            if "out of memory" in diagnostic.lower():
                raise ReconstructionError("GPU 显存不足，关闭其他 GPU 程序后重试。")
            if "connection" in diagnostic.lower() or "timed out" in diagnostic.lower():
                raise ReconstructionError("模型权重下载失败；检查网络或设置 HF_ENDPOINT 后重试。")
            raise ReconstructionError("InstantMesh 重建失败，请检查依赖、CUDA 显存和模型权重。")
        return response

    def stop(self):
        process, self.process = self.process, None
        if not process:
            return
        try:
            if process.poll() is None and process.stdin:
                process.stdin.write(json.dumps({"shutdown": True}) + "\n")
                process.stdin.flush()
                process.wait(timeout=10)
        except (BrokenPipeError, OSError, subprocess.TimeoutExpired):
            if process.poll() is None:
                process.kill()
                process.wait(timeout=10)


def close_reconstruction_worker():
    global _worker
    with _worker_lock:
        if _worker is not None:
            _worker.stop()
            _worker = None


def validate_generated_glb(path: Path):
    if not path.is_file() or path.stat().st_size < 256 or path.stat().st_size > 50 * 1024 * 1024:
        raise ReconstructionError("Generated GLB is missing or exceeds 50 MB.")
    with path.open("rb") as handle:
        header = handle.read(20)
        magic, version, length = struct.unpack_from("<4sII", header)
        chunk_size, chunk_type = struct.unpack_from("<II", header, 12)
        if magic != b"glTF" or version != 2 or length != path.stat().st_size or chunk_type != 0x4E4F534A:
            raise ReconstructionError("Generated GLB has an invalid header.")
        scene = json.loads(handle.read(chunk_size))
        primitives = [primitive for mesh in scene.get("meshes", []) for primitive in mesh.get("primitives", [])]
        accessors = scene.get("accessors", [])
        if not primitives or not accessors or not scene.get("buffers"):
            raise ReconstructionError("Generated GLB has no mesh.")
        if not any(accessors[primitive["attributes"]["POSITION"]]["count"] >= 4 for primitive in primitives):
            raise ReconstructionError("Generated GLB has no usable geometry.")
        handle.seek(20 + chunk_size)
        binary_chunk = handle.read(8)
        if len(binary_chunk) != 8 or struct.unpack("<II", binary_chunk)[1] != 0x004E4942:
            raise ReconstructionError("Generated GLB has no vertex data.")


def reconstruct(photos: list[Path], output: Path):
    if len(photos) != 3 or any(not photo.is_file() for photo in photos):
        raise ReconstructionError("请上传同一件家具的正面、右侧、顶面三张照片。")
    status = reconstruction_status()
    if not status["enabled"]:
        raise ReconstructionError(status["message"])
    root = Path(os.getenv("ROOMWISE_INSTANTMESH_ROOT", str(INSTANTMESH_ROOT))).resolve()
    python = reconstruction_python()
    global _worker
    with _worker_lock:
        if _worker is None or _worker.root != root or _worker.python != python:
            if _worker is not None:
                _worker.stop()
            _worker = InstantMeshWorker(root, python)
        try:
            _worker.request(photos, output)
        except ReconstructionError:
            output.unlink(missing_ok=True)
            raise
    try:
        validate_generated_glb(output)
    except (OSError, ValueError, struct.error, json.JSONDecodeError):
        output.unlink(missing_ok=True)
        raise ReconstructionError("InstantMesh produced an invalid model.") from None
    return f"/uploads/assets/{output.name}"

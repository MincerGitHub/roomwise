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


def model_cache(root: Path):
    """Reuse a populated user cache before creating another multi-GB copy."""
    project_cache = root / 'ckpts' / 'huggingface'
    user_cache = Path.home() / '.cache' / 'huggingface'
    for candidate in (project_cache, user_cache):
        if any((candidate / 'hub' / 'models--TencentARC--InstantMesh' / 'snapshots').glob('*/instant_mesh_base.ckpt')):
            return candidate
    return project_cache


def reconstruction_python():
    configured = os.getenv("ROOMWISE_INSTANTMESH_PYTHON")
    if configured:
        return Path(configured).expanduser().resolve()
    active = Path(sys.executable).resolve()
    user_name = Path.home().name
    conda_roots = [
        Path.home() / "anaconda3",
        Path(active.anchor) / "Users" / user_name / "anaconda3",
        Path(active.anchor) / "Users" / user_name / "miniconda3",
    ]
    conda_exe = os.getenv("CONDA_EXE")
    if conda_exe:
        conda_roots.append(Path(conda_exe).resolve().parent.parent)
    candidates = [
        active.parent.parent / "instantmesh" / active.name,
        Path(os.getenv("CONDA_PREFIX", "")) / active.name if os.getenv("CONDA_PREFIX") else Path(),
        *(root / "envs" / "instantmesh" / active.name for root in conda_roots),
    ]
    for candidate in candidates:
        if candidate.name and candidate.is_file():
            return candidate.resolve()
    return candidates[0].resolve()


def reconstruction_status():
    root = Path(os.getenv("ROOMWISE_INSTANTMESH_ROOT", str(INSTANTMESH_ROOT))).resolve()
    python = reconstruction_python()
    worker_script = root / "roomwise_worker.py"
    worker_running = (_worker is not None and _worker.root == root and _worker.python == python
                      and _worker.process is not None and _worker.process.poll() is None)
    adapter_cli = (root / "run.py").is_file() and (root / "device.py").is_file()
    ready = (adapter_cli or worker_script.is_file()) and (root / "configs/instant-mesh-base.yaml").is_file() and python.is_file()
    if ready and not worker_running:
        try:
            modules = "('torch','diffusers','rembg','trimesh','onnxruntime')"
            if adapter_cli and not worker_script.is_file():
                probe_code = (
                    "import importlib.util,sys; "
                    f"sys.path.insert(0, {str(root)!r}); "
                    f"assert all(importlib.util.find_spec(name) for name in {modules}); "
                    "from device import resolve_device; "
                    "from src.models.lrm_mesh import InstantMesh; "
                    "print(resolve_device())"
                )
            else:
                probe_code = f"import importlib.util; assert all(importlib.util.find_spec(name) for name in {modules})"
            probe = subprocess.run([str(python), "-c", probe_code], cwd=root,
                                   capture_output=True, text=True, timeout=60, check=False)
            ready = probe.returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            ready = False
    return {
        "enabled": ready,
        "python": str(python),
        "root": str(root),
        "message": (
            "InstantMesh 本地推理已就绪（CUDA/DirectML/CPU）；首次使用会下载模型权重。"
            if ready else
            "InstantMesh 不可用；请检查独立 Python 环境、依赖及 ROOMWISE_INSTANTMESH_PYTHON。"
        ),
    }


class InstantMeshWorker:
    """Optional persistent worker used when InstantMesh supplies its worker script."""

    def __init__(self, root: Path, python: Path):
        self.root = root
        self.python = python
        self.process = None
        self.responses = Queue()
        self.stderr_tail = deque(maxlen=20)

    def start(self):
        if self.process and self.process.poll() is None:
            return
        environment = os.environ.copy()
        environment.setdefault("INSTANTMESH_DEVICE", "auto")
        environment.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
        environment.setdefault("HF_HOME", str(model_cache(self.root)))
        environment.setdefault("U2NET_HOME", str(self.root / "ckpts" / "u2net"))
        cache = Path(environment["HF_HOME"]) / "hub"
        cached_models = (
            ("TencentARC--InstantMesh", "diffusion_pytorch_model.bin"),
            ("TencentARC--InstantMesh", "instant_mesh_base.ckpt"),
            ("sudo-ai--zero123plus-v1.2", "model_index.json"),
            ("facebook--dino-vitb16", "pytorch_model.bin"),
        )
        if (Path(environment["U2NET_HOME"]) / "u2net.onnx").is_file() and all(
            any(path.is_file() and path.stat().st_size > 0 for path in
                (cache / f"models--{repo}" / "snapshots").glob(f"*/{filename}"))
            for repo, filename in cached_models
        ):
            environment.setdefault("HF_HUB_OFFLINE", "1")
        environment["PYTHONIOENCODING"] = "utf-8"
        process = subprocess.Popen(
            [str(self.python), "roomwise_worker.py"], cwd=self.root, env=environment,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace", bufsize=1,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
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
            raise ReconstructionError("InstantMesh 常驻进程启动超时，请检查显卡和模型权重。") from exc
        if not response.get("ready"):
            self.stop()
            raise ReconstructionError("InstantMesh 常驻进程启动失败：" + "；".join(list(self.stderr_tail)[-3:])[-500:])

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
            request = {"photos": [str(Path(photo).resolve()) for photo in photos],
                       "output": str(Path(output).resolve())}
            self.process.stdin.write(json.dumps(request, ensure_ascii=False) + "\n")
            self.process.stdin.flush()
            response = self.responses.get(timeout=1800)
        except (BrokenPipeError, OSError, Empty) as exc:
            self.stop()
            raise ReconstructionError("InstantMesh 常驻进程中断或超时，请重试。") from exc
        if not response.get("ok"):
            self.stop()
            diagnostic = str(response.get("error", "")) + "\n" + "\n".join(self.stderr_tail)
            if "out of memory" in diagnostic.lower():
                raise ReconstructionError("GPU/共享显存不足，关闭其他图形程序后重试。")
            if ("connection" in diagnostic.lower() or "timed out" in diagnostic.lower()) and "huggingface" in diagnostic.lower():
                raise ReconstructionError("模型权重下载失败；检查网络或设置 HF_ENDPOINT 后重试。")
            raise ReconstructionError("InstantMesh 重建失败：" + str(response.get("error") or "请检查进程日志。")[:300])
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
    if len(photos) not in {1, 3} or any(not photo.is_file() for photo in photos):
        raise ReconstructionError("请上传单张家具图片，或同一件家具的正面、右侧、顶面三张照片。")
    status = reconstruction_status()
    if not status["enabled"]:
        raise ReconstructionError(status["message"])
    root = Path(os.getenv("ROOMWISE_INSTANTMESH_ROOT", str(INSTANTMESH_ROOT))).resolve()
    python = reconstruction_python()
    worker_script = root / "roomwise_worker.py"
    if worker_script.is_file() and len(photos) == 3:
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

    # Current Intel Arc installs use the tested DirectML adapter in run.py;
    # fall back to that one-shot path until a compatible worker script exists.
    command = [str(python), "run.py", "configs/instant-mesh-base.yaml", str(photos[0]),
               "--glb_output", str(output), "--output_path", str(output.parent.parent.parent / "instantmesh-work" / output.stem)]
    if len(photos) == 3:
        command.extend(["--side_image", str(photos[1]), "--top_image", str(photos[2])])
    environment = os.environ.copy()
    environment.setdefault("INSTANTMESH_DEVICE", "auto")
    # The default Hugging Face endpoint is intermittently unreachable on this
    # Windows network; callers can override it with HF_ENDPOINT when needed.
    environment.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
    environment.setdefault("HF_HOME", str(model_cache(root)))
    environment.setdefault("U2NET_HOME", str(root / "ckpts" / "u2net"))
    try:
        result = subprocess.run(command, cwd=root, env=environment, capture_output=True, text=True, timeout=1800, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        output.unlink(missing_ok=True)
        raise ReconstructionError("InstantMesh 启动失败或超时，请检查显卡后端和独立 Python 环境。") from exc
    if result.returncode:
        output.unlink(missing_ok=True)
        diagnostic = ((result.stderr or "") + (result.stdout or ""))[-4000:].lower()
        if "out of memory" in diagnostic:
            raise ReconstructionError("GPU/共享显存不足，关闭其他图形程序后重试。")
        if "connection" in diagnostic or "timed out" in diagnostic:
            raise ReconstructionError("模型权重下载失败；检查网络或设置 HF_ENDPOINT 后重试。")
        detail = ((result.stderr or "") + (result.stdout or "")).strip().splitlines()
        suffix = detail[-1][-240:] if detail else ""
        raise ReconstructionError(f"InstantMesh 重建失败，请检查依赖、显存和模型权重。{suffix}")
    try:
        validate_generated_glb(output)
    except (OSError, ValueError, struct.error, json.JSONDecodeError):
        output.unlink(missing_ok=True)
        raise ReconstructionError("InstantMesh produced an invalid model.") from None
    return f"/uploads/assets/{output.name}"

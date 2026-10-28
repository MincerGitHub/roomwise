from __future__ import annotations

import json
import os
from pathlib import Path
import struct
import subprocess
import sys


INSTANTMESH_ROOT = Path(__file__).resolve().parents[3] / "InstantMesh"


class ReconstructionError(Exception):
    pass


def reconstruction_python():
    active = Path(sys.executable).resolve()
    sibling = active.parent.parent / "instantmesh" / active.name
    return Path(os.getenv("ROOMWISE_INSTANTMESH_PYTHON", str(sibling))).resolve()


def reconstruction_status():
    root = Path(os.getenv("ROOMWISE_INSTANTMESH_ROOT", str(INSTANTMESH_ROOT))).resolve()
    python = reconstruction_python()
    ready = (root / "run.py").is_file() and (root / "configs/instant-mesh-base.yaml").is_file() and python.is_file()
    if ready:
        try:
            probe = subprocess.run([str(python), "-c", "import importlib.util; assert all(importlib.util.find_spec(name) for name in ('torch','diffusers','rembg','trimesh','onnxruntime'))"], capture_output=True, timeout=30, check=False)
            ready = probe.returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            ready = False
    return {"enabled": ready, "message": "InstantMesh 本地依赖已就绪；重建时需要 CUDA，首次使用需下载权重。" if ready else "InstantMesh 不可用；请检查依赖及 ROOMWISE_INSTANTMESH_PYTHON。"}


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
    command = [str(python), "run.py", "configs/instant-mesh-base.yaml", str(photos[0]),
               "--side_image", str(photos[1]), "--top_image", str(photos[2]),
               "--glb_output", str(output), "--output_path", str(output.parent.parent.parent / "instantmesh-work" / output.stem)]
    environment = os.environ.copy()
    environment.setdefault("HF_HOME", str(root / "ckpts" / "huggingface"))
    environment.setdefault("U2NET_HOME", str(root / "ckpts" / "u2net"))
    try:
        result = subprocess.run(command, cwd=root, env=environment, capture_output=True, text=True, timeout=1800, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        output.unlink(missing_ok=True)
        raise ReconstructionError("InstantMesh 启动失败或超时，请检查 GPU 和独立 Python 环境。") from exc
    if result.returncode:
        output.unlink(missing_ok=True)
        diagnostic = ((result.stderr or "") + (result.stdout or ""))[-4000:].lower()
        if "out of memory" in diagnostic:
            raise ReconstructionError("GPU 显存不足，关闭其他 GPU 程序后重试。")
        if "connection" in diagnostic or "timed out" in diagnostic:
            raise ReconstructionError("模型权重下载失败；检查网络或设置 HF_ENDPOINT 后重试。")
        raise ReconstructionError("InstantMesh 重建失败，请检查依赖、CUDA 显存和模型权重。")
    try:
        validate_generated_glb(output)
    except (OSError, ValueError, struct.error, json.JSONDecodeError):
        output.unlink(missing_ok=True)
        raise ReconstructionError("InstantMesh produced an invalid model.") from None
    return f"/uploads/assets/{output.name}"

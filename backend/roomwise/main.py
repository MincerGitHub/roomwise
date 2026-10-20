from __future__ import annotations

import importlib
import json
from pathlib import Path
import struct
import uuid

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from . import __version__
from .catalog import catalog, demo_scene, suggest_items
from .command_service import interpret_command
from .intent_planner import language_status
from .generator import generate_layouts, learning_status
from .geometry import validate_scene
from .schemas import CommandRequest, GenerateRequest, SceneRequest, SuggestRequest
from .storage import SceneStore, VersionConflict


APP_ROOT = Path(__file__).resolve().parents[2]
RUNTIME = APP_ROOT / "runtime"
UPLOADS = RUNTIME / "uploads"
UPLOADS.mkdir(parents=True, exist_ok=True)
store = SceneStore(RUNTIME / "roomwise.sqlite3")

app = FastAPI(title="Roomwise 搬家家具布局助手", version=__version__)
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173", "http://127.0.0.1:8765", "http://localhost:8765"], allow_credentials=False, allow_methods=["GET", "POST"], allow_headers=["*"])
app.mount("/uploads", StaticFiles(directory=str(UPLOADS)), name="uploads")


@app.middleware("http")
async def api_prefix(request, call_next):
    """Same API works behind Vite and bundled production frontend.

    Legacy root endpoints remain usable for scripts. Strip only exact /api/
    prefix and leave /uploads and static files unchanged.
    """
    path = request.scope.get("path", "")
    if path.startswith("/api/"):
        request.scope["path"] = path[4:]
        request.scope["raw_path"] = request.scope["path"].encode("utf-8")
    return await call_next(request)


def _video_module():
    try:
        return importlib.import_module("roomwise.video")
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"视频模块不可用：{type(exc).__name__}") from exc


@app.get("/health")
def health():
    model = learning_status()
    try:
        video = _video_module().video_status()
    except HTTPException:
        video = {"available": False, "name": None, "limitations": ["视频模块不可用"]}
    language = language_status()
    return {"status": "ok", "version": __version__, "modelLoaded": bool(model.get("loaded", model.get("available", model.get("modelLoaded", False)))), "model": model, "videoDetector": video, "commandParser": "language_model_with_validated_executor" if language.get("enabled") else "offline_restricted_chinese", "language": language, "units": "metres"}


@app.get("/catalog")
def get_catalog():
    return catalog()


@app.get("/demo")
def get_demo():
    return demo_scene()


@app.post("/validate")
def validate(request: SceneRequest):
    from .window_constraints import evaluate_layout_requirements
    from .bedside_constraints import evaluate_bedside_groups

    scene = request.scene.model_dump()
    return {**validate_scene(scene), "requirements": evaluate_layout_requirements(scene),
            "functionalRelations": evaluate_bedside_groups(scene)}


@app.post("/generate")
def generate(request: GenerateRequest):
    return generate_layouts(request.scene.model_dump(), request.mode, request.count, request.seed)


@app.post("/command")
def command(request: CommandRequest):
    return interpret_command(request.scene.model_dump(), request.text, request.selectedId)


@app.post("/suggest")
def suggest(request: SuggestRequest):
    return suggest_items(request.scene.model_dump(), request.need)


@app.post("/scenes/save")
def save_scene(request: SceneRequest):
    try:
        return store.save(request.scene.model_dump())
    except VersionConflict as exc:
        raise HTTPException(status_code=409, detail={"message": str(exc), "currentVersion": exc.current_version}) from exc


@app.get("/scenes")
def list_scenes():
    return {"scenes": store.list()}


@app.get("/scenes/{scene_id}")
def load_scene(scene_id: str):
    scene = store.get(scene_id)
    if scene is None:
        raise HTTPException(status_code=404, detail="场景不存在")
    return scene


async def _save_upload(upload: UploadFile, destination: Path, limit: int):
    size = 0
    try:
        with destination.open("wb") as handle:
            while chunk := await upload.read(1024 * 1024):
                size += len(chunk)
                if size > limit:
                    raise HTTPException(status_code=413, detail=f"文件超过{limit // (1024 * 1024)}MB限制")
                handle.write(chunk)
        if not size:
            raise HTTPException(status_code=400, detail="文件为空")
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    finally:
        await upload.close()
    return size


@app.post("/assets")
async def upload_asset(file: UploadFile = File(...)):
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in {".glb", ".gltf", ".jpg", ".jpeg", ".png", ".webp"}:
        raise HTTPException(status_code=415, detail="仅接受 GLB、内嵌资源GLTF、JPG、PNG、WebP")
    directory = UPLOADS / "assets"
    directory.mkdir(exist_ok=True)
    destination = directory / f"{uuid.uuid4().hex}{suffix}"
    await _save_upload(file, destination, 50 * 1024 * 1024)
    try:
        if suffix == ".glb":
            binary = destination.read_bytes()
            if len(binary) < 20:
                raise ValueError("GLB文件头不完整")
            magic, version, length = struct.unpack_from("<4sII", binary, 0)
            if magic != b"glTF" or version != 2 or length != len(binary):
                raise ValueError("不是有效的GLB2.0文件")
            json_length, chunk_type = struct.unpack_from("<II", binary, 12)
            if chunk_type != 0x4E4F534A or json_length > len(binary) - 20:
                raise ValueError("GLB缺少有效JSON块")
            data = json.loads(binary[20:20 + json_length].decode("utf-8"))
            for entry in data.get("buffers", []) + data.get("images", []):
                uri = entry.get("uri")
                if uri and not uri.startswith("data:"):
                    raise ValueError("GLB须包含所有资源，不接受外部路径")
        elif suffix == ".gltf":
            data = json.loads(destination.read_text(encoding="utf-8"))
            if str(data.get("asset", {}).get("version", "")) != "2.0":
                raise ValueError("仅接受glTF2.0")
            for entry in data.get("buffers", []) + data.get("images", []):
                uri = entry.get("uri")
                if uri and not uri.startswith("data:"):
                    raise ValueError("GLTF须内嵌资源，请改用单文件GLB")
        else:
            from PIL import Image
            with Image.open(destination) as image:
                if image.width * image.height > 40_000_000:
                    raise ValueError("图片尺寸过大")
                image.verify()
    except Exception as exc:
        destination.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=f"资产校验失败：{str(exc)[:120]}") from exc
    return {"url": f"/uploads/assets/{destination.name}", "name": Path(file.filename or destination.name).name, "type": "model" if suffix in (".glb", ".gltf") else "image"}


@app.post("/video/analyze")
async def analyze_video(file: UploadFile = File(...)):
    module = _video_module()
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in {".mp4", ".mov", ".avi", ".webm", ".mkv"}:
        raise HTTPException(status_code=415, detail="仅接受MP4、MOV、AVI、WEBM或MKV视频")
    directory = UPLOADS / "videos"
    directory.mkdir(exist_ok=True)
    destination = directory / f"{uuid.uuid4().hex}{suffix}"
    await _save_upload(file, destination, 100 * 1024 * 1024)
    try:
        job_id = module.submit_video(destination)
    except Exception as exc:
        destination.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=f"视频任务创建失败：{str(exc)[:120]}") from exc
    return {"jobId": job_id}


@app.get("/video/jobs/{job_id}")
def video_job(job_id: str):
    result = _video_module().get_job(job_id)
    if result is None:
        raise HTTPException(status_code=404, detail="视频任务不存在")
    return result


@app.get("/experiments")
def experiments():
    try:
        module = importlib.import_module("roomwise.learning")
        if hasattr(module, "experiments_summary"):
            return module.experiments_summary()
    except Exception:
        pass
    candidates = [APP_ROOT / "artifacts" / "experiments_summary.json", APP_ROOT / "artifacts" / "metrics.json"]
    for path in candidates:
        if path.is_file():
            try:
                return {"available": True, "source": str(path.relative_to(APP_ROOT)), "results": json.loads(path.read_text(encoding="utf-8"))}
            except (ValueError, OSError):
                continue
    return {"available": False, "results": None, "message": "尚无已完成实验结果；不以设计目标替代实测数据。"}


# Production frontend may be served by this local process; API route order stays first.
FRONTEND_DIST = APP_ROOT / "frontend" / "dist"
if FRONTEND_DIST.is_dir():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIST), html=True), name="frontend")

from __future__ import annotations

from pathlib import Path
import json
import threading
import uuid
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from starlette.concurrency import run_in_threadpool

from .furniture import FurnitureError, FurnitureService, prepare_photos
from .furniture_schemas import ImportFurnitureModel, PublishFurniture, SaveFurnitureDraft
from .furniture_vision import vision_status
from .furniture_reconstruction import reconstruction_status
from .storage import runtime_directory


def require_local_origin(request: Request):
    origin = request.headers.get("origin")
    if origin:
        try:
            parsed = urlsplit(origin)
        except ValueError:
            raise HTTPException(403, "来源地址无效") from None
        if parsed.scheme not in {"http", "https"} or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise HTTPException(403, "仅允许本机访问")


router = APIRouter(prefix="/furniture", tags=["furniture"], dependencies=[Depends(require_local_origin)])
_service = None
_lock = threading.Lock()


def service():
    global _service
    with _lock:
        if _service is None:
            runtime = runtime_directory()
            _service = FurnitureService(runtime / "roomwise.sqlite3", runtime / "uploads")
    return _service


def close_service():
    global _service
    with _lock:
        if _service is not None:
            _service.close()
            _service = None


def invoke(operation, *arguments):
    try:
        return operation(*arguments)
    except FurnitureError as exc:
        raise HTTPException(exc.status, detail=str(exc)) from None


@router.get("/status")
def status():
    return {**vision_status(), "reconstruction": reconstruction_status()}


@router.post("/analyze")
async def analyze(files: list[UploadFile] = File(...), viewTypes: str = Form("")):
    directory = None
    try:
        if not 1 <= len(files) <= 8:
            raise HTTPException(400, "每件家具需要1—8张图片")
        if any(Path(file.filename or "").suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp"} for file in files):
            raise HTTPException(415, "仅接受 JPEG、PNG、WebP")
        try:
            views = json.loads(viewTypes) if viewTypes else []
        except json.JSONDecodeError:
            raise HTTPException(400, "图片角度无效") from None
        allowed_views = {"front", "left", "right", "back", "top", "bottom", "left_front", "right_front"}
        if views and (len(views) != len(files) or any(view not in allowed_views for view in views) or views[0] != "front" or "front" in views[1:] or len(set(views)) != len(views)):
            raise HTTPException(400, "图片角度无效")
        views = views or ["front"] + ["left", "right", "back", "top", "bottom", "left_front", "right_front"][:len(files) - 1]
        target = service()
        identifier = uuid.uuid4().hex
        directory = target.uploads / "furniture" / identifier
        directory.mkdir()
        for index, file in enumerate(files):
            size = 0
            with (directory / f"input_{index}").open("wb") as handle:
                while chunk := await file.read(1024 * 1024):
                    size += len(chunk)
                    if size > 10 * 1024 * 1024:
                        raise HTTPException(413, "每张图片不得超过 10 MB")
                    handle.write(chunk)
            if not size:
                raise HTTPException(400, "图片不能为空")
        photo_urls = await run_in_threadpool(prepare_photos, directory, len(files))
        return invoke(target.create, identifier, photo_urls, views)
    except (HTTPException, FurnitureError) as exc:
        if directory and directory.is_dir():
            for path in directory.iterdir():
                if path.is_file():
                    path.unlink(missing_ok=True)
            directory.rmdir()
        if isinstance(exc, FurnitureError):
            raise HTTPException(exc.status, str(exc)) from None
        raise
    finally:
        for file in files:
            await file.close()


@router.get("")
def listing():
    return service().listing()


@router.post("/import-model")
def import_model(request: ImportFurnitureModel):
    return invoke(service().import_model, request.assetUrl, request.label, request.sourceNote)


@router.get("/jobs/{job_id}")
def job(job_id: str):
    return invoke(service().job, job_id)


@router.get("/reconstruction-jobs/{job_id}")
def reconstruction_job(job_id: str):
    return invoke(service().reconstruction_job, job_id)


@router.get("/drafts/{draft_id}")
def draft(draft_id: str):
    return invoke(service().draft, draft_id)


@router.delete("/drafts/{draft_id}")
def delete_draft(draft_id: str, expectedVersion: int = Query(..., ge=1)):
    return invoke(service().delete_draft, draft_id, expectedVersion)


@router.post("/drafts/{draft_id}/save")
def save(draft_id: str, request: SaveFurnitureDraft):
    return invoke(service().save, draft_id, request)


@router.post("/drafts/{draft_id}/retry")
def retry(draft_id: str):
    return invoke(service().retry, draft_id)


@router.post("/drafts/{draft_id}/reconstruct")
def reconstruct(draft_id: str):
    return invoke(service().start_reconstruction, draft_id)


@router.post("/drafts/{draft_id}/publish")
def publish(draft_id: str, request: PublishFurniture):
    return invoke(service().publish, draft_id, request)


@router.get("/{asset_id}")
def asset(asset_id: str):
    return invoke(service().asset, asset_id)


@router.post("/{asset_id}/edit")
def edit(asset_id: str):
    return invoke(service().edit_asset, asset_id)


@router.delete("/{asset_id}")
def delete_asset(asset_id: str, expectedVersion: int = Query(..., ge=1)):
    return invoke(service().delete_asset, asset_id, expectedVersion)



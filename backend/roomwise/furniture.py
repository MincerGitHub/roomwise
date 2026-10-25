from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import uuid
import warnings

from PIL import Image, ImageOps, UnidentifiedImageError

from .furniture_schemas import FurnitureProperties, PublishFurniture, SaveFurnitureDraft
from .furniture_vision import VisionError, recognize_furniture
from .schemas import FurnitureSnapshot


def now():
    return datetime.now(timezone.utc).isoformat()


class FurnitureError(Exception):
    def __init__(self, status: int, message: str):
        self.status = status
        super().__init__(message)


def prepare_photos(directory: Path, count: int):
    photos = []
    try:
        for index in range(count):
            source = directory / f"input_{index}"
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(source) as image:
                    if image.format not in {"JPEG", "PNG", "WEBP"}:
                        raise ValueError("仅接受 JPEG、PNG、WebP 图片")
                    if image.width * image.height > 40_000_000:
                        raise ValueError("图片超过 4000 万像素")
                    image.load()
                    oriented = ImageOps.exif_transpose(image)
                    normalized = Image.new("RGB", oriented.size, "white")
                    rgba = oriented.convert("RGBA")
                    normalized.paste(rgba, mask=rgba.getchannel("A"))
                    normalized.save(directory / f"photo_{index}.jpg", "JPEG", quality=92)
                    normalized.thumbnail((2048, 2048))
                    normalized.save(directory / f"vision_{index}.jpg", "JPEG", quality=90)
            source.unlink(missing_ok=True)
            photos.append(f"/uploads/furniture/{directory.name}/photo_{index}.jpg")
        return photos
    except (ValueError, OSError, UnidentifiedImageError, Image.DecompressionBombWarning, Image.DecompressionBombError):
        for path in directory.iterdir():
            if path.is_file():
                path.unlink(missing_ok=True)
        directory.rmdir()
        raise FurnitureError(400, "图片无效、格式不支持或超过 4000 万像素；请换图后重试。") from None


class FurnitureService:
    def __init__(self, database: Path, uploads: Path, *, analyzer=recognize_furniture, auto_run=True):
        self.database = Path(database)
        self.uploads = Path(uploads)
        self.database.parent.mkdir(parents=True, exist_ok=True)
        (self.uploads / "furniture").mkdir(parents=True, exist_ok=True)
        self.analyzer = analyzer
        self.auto_run = auto_run
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="furniture-vision")
        with self.connect() as connection:
            connection.execute("CREATE TABLE IF NOT EXISTS furniture_drafts (id TEXT PRIMARY KEY, body TEXT NOT NULL)")
            connection.execute("CREATE TABLE IF NOT EXISTS furniture_jobs (id TEXT PRIMARY KEY, body TEXT NOT NULL)")
            connection.execute("CREATE TABLE IF NOT EXISTS furniture_assets (id TEXT PRIMARY KEY, body TEXT NOT NULL)")
            connection.execute("CREATE TABLE IF NOT EXISTS furniture_publications (request_id TEXT PRIMARY KEY, draft_id TEXT NOT NULL, body TEXT NOT NULL)")
            for row in connection.execute("SELECT id,body FROM furniture_jobs").fetchall():
                job = json.loads(row["body"])
                if job["status"] in {"queued", "processing"}:
                    job.update(status="failed", errorCode="interrupted", error="上次识别被中断；草稿已保留，需手动重试。", updatedAt=now())
                    self.put(connection, "furniture_jobs", job)

    def close(self):
        self.executor.shutdown(wait=True, cancel_futures=True)

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.database, timeout=10)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def get(self, connection, table, identifier):
        row = connection.execute(f"SELECT body FROM {table} WHERE id=?", (identifier,)).fetchone()
        if row is None:
            raise FurnitureError(404, "家具或草稿不存在")
        return json.loads(row["body"])

    def put(self, connection, table, body):
        connection.execute(f"INSERT INTO {table}(id,body) VALUES (?,?) ON CONFLICT(id) DO UPDATE SET body=excluded.body", (body["id"], json.dumps(body, ensure_ascii=False)))

    def draft(self, identifier):
        with self.connect() as connection:
            draft = self.active_draft(connection, identifier)
            parent_id = draft.get("editingAssetId") or draft.get("publishedAssetId")
            if parent_id:
                self.active_asset(connection, parent_id)
            return draft

    def active_draft(self, connection, identifier):
        draft = self.get(connection, "furniture_drafts", identifier)
        if draft.get("deletedAt"):
            raise FurnitureError(404, "草稿已删除")
        return draft

    def delete_draft(self, identifier, expected_version):
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            draft = self.get(connection, "furniture_drafts", identifier)
            if draft["version"] != expected_version:
                raise FurnitureError(409, "草稿版本已变化，请重新打开草稿后再删除。")
            if draft.get("publishedAssetId"):
                raise FurnitureError(409, "草稿已发布，请在已确认家具中操作。")
            if not draft.get("deletedAt"):
                timestamp = now()
                draft.update(deletedAt=timestamp, updatedAt=timestamp)
                self.put(connection, "furniture_drafts", draft)
                if draft.get("jobId"):
                    job = self.get(connection, "furniture_jobs", draft["jobId"])
                    job.update(status="failed", errorCode="draft_deleted", error="草稿已删除。", updatedAt=timestamp)
                    self.put(connection, "furniture_jobs", job)
        return {"id": identifier, "deleted": True}

    def job(self, identifier):
        with self.connect() as connection:
            return self.get(connection, "furniture_jobs", identifier)

    def asset(self, identifier):
        with self.connect() as connection:
            return self.active_asset(connection, identifier)

    def active_asset(self, connection, identifier):
        asset = self.get(connection, "furniture_assets", identifier)
        if asset.get("deletedAt"):
            raise FurnitureError(404, "家具已从家具库删除")
        return asset

    def delete_asset(self, identifier, expected_version):
        """Remove an asset from the library without breaking saved instances.

        Asset snapshots and files may still be referenced by saved rooms or
        earlier versions. Keep those immutable resources and a deletion marker
        while disabling further edits, publication replay and library access.
        """
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            asset = self.get(connection, "furniture_assets", identifier)
            if asset["version"] != expected_version:
                raise FurnitureError(409, "家具版本已变化，请刷新家具库后再删除。")
            if not asset.get("deletedAt"):
                asset.update(deletedAt=now(), updatedAt=now())
                self.put(connection, "furniture_assets", asset)
        return {"id": identifier, "deleted": True}

    def listing(self):
        with self.connect() as connection:
            assets = [json.loads(row["body"]) for row in connection.execute("SELECT body FROM furniture_assets")]
            drafts = [json.loads(row["body"]) for row in connection.execute("SELECT body FROM furniture_drafts")]
        deleted_ids = {body["id"] for body in assets if body.get("deletedAt")}
        return {"assets": sorted([body for body in assets if not body.get("deletedAt")], key=lambda body: body["updatedAt"], reverse=True),
                "drafts": sorted([body for body in drafts if not body.get("publishedAssetId") and not body.get("deletedAt")
                                  and body.get("editingAssetId") not in deleted_ids],
                                 key=lambda body: body["updatedAt"], reverse=True)}

    def create(self, identifier: str, photo_urls: list[str]):
        draft = {"id": identifier, "version": 1, "photoUrls": photo_urls, "properties": FurnitureProperties().model_dump(), "recognition": None, "jobId": None, "updatedAt": now()}
        with self.connect() as connection:
            self.put(connection, "furniture_drafts", draft)
        return self.retry(identifier)

    def retry(self, identifier):
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            draft = self.active_draft(connection, identifier)
            if draft.get("publishedAssetId") or draft.get("editingAssetId"):
                raise FurnitureError(409, "已发布家具的修订不再次调用识别；请使用图片新建草稿。")
            if draft.get("jobId"):
                previous = self.get(connection, "furniture_jobs", draft["jobId"])
                if previous["status"] in {"queued", "processing"}:
                    raise FurnitureError(409, "识别正在进行，请勿重复提交")
            job = {"id": uuid.uuid4().hex, "draftId": identifier, "status": "queued", "updatedAt": now(), "error": None, "errorCode": None}
            draft.update(jobId=job["id"], updatedAt=now())
            self.put(connection, "furniture_jobs", job)
            self.put(connection, "furniture_drafts", draft)
        if self.auto_run:
            self.executor.submit(self.process, job["id"])
        return {"draftId": identifier, "jobId": job["id"]}

    def process(self, identifier):
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            job = self.get(connection, "furniture_jobs", identifier)
            if job["status"] != "queued":
                return
            job.update(status="processing", updatedAt=now())
            self.put(connection, "furniture_jobs", job)
            draft = self.get(connection, "furniture_drafts", job["draftId"])
        try:
            directory_id = Path(draft["photoUrls"][0]).parent.name
            paths = [self.uploads / "furniture" / directory_id / f"vision_{index}.jpg" for index in range(len(draft["photoUrls"]))]
            result, metrics = self.analyzer(paths)
            from .furniture_schemas import FurnitureRecognition

            result = FurnitureRecognition.model_validate(result).model_dump()
            job.update(status="complete", metrics=metrics, result=result)
            draft["recognition"] = result
            draft["properties"] = result["properties"]
        except VisionError as exc:
            job.update(status="failed", errorCode=exc.code, error=str(exc))
        except Exception:
            job.update(status="failed", errorCode="processing_error", error="识别处理失败；原图和草稿已保留，可补图或手工填写。")
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            current = self.get(connection, "furniture_drafts", draft["id"])
            if current.get("deletedAt") or current["jobId"] != identifier:
                return
            job["updatedAt"] = now()
            draft.update(version=current["version"] + 1, updatedAt=now())
            self.put(connection, "furniture_jobs", job)
            self.put(connection, "furniture_drafts", draft)

    def editable(self, connection, draft, expected_version):
        if draft.get("deletedAt"):
            raise FurnitureError(404, "草稿已删除")
        if draft.get("editingAssetId"):
            self.active_asset(connection, draft["editingAssetId"])
        if draft["version"] != expected_version or draft.get("publishedAssetId"):
            raise FurnitureError(409, "草稿版本已变化或已发布，请重新打开。")
        if draft.get("jobId") and self.get(connection, "furniture_jobs", draft["jobId"])["status"] in {"queued", "processing"}:
            raise FurnitureError(409, "请等待识别完成后再修改草稿")

    def save(self, identifier, request: SaveFurnitureDraft):
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            draft = self.get(connection, "furniture_drafts", identifier)
            self.editable(connection, draft, request.expectedVersion)
            properties = request.properties.model_dump()
            for name in ("width", "depth", "height"):
                if properties[name] != draft["properties"][name]:
                    properties["dimensionSources"][name] = "user" if properties[name] is not None else "unknown"
                elif properties["dimensionSources"][name] != draft["properties"]["dimensionSources"][name]:
                    raise FurnitureError(400, "尺寸来源不可直接改写；修改尺寸后由系统记录为用户填写。")
            draft.update(properties=properties, version=draft["version"] + 1, updatedAt=now())
            self.put(connection, "furniture_drafts", draft)
        return draft

    def edit_asset(self, identifier):
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            asset = self.active_asset(connection, identifier)
            draft = {
                "id": uuid.uuid4().hex, "version": 1, "photoUrls": asset["photoUrls"], "properties": asset["properties"],
                "recognition": None, "jobId": None, "editingAssetId": asset["id"], "baseAssetVersion": asset["version"], "updatedAt": now(),
            }
            self.put(connection, "furniture_drafts", draft)
        return draft

    def publish(self, identifier, request: PublishFurniture):
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            previous = connection.execute("SELECT draft_id,body FROM furniture_publications WHERE request_id=?", (request.requestId,)).fetchone()
            if previous:
                if previous["draft_id"] != identifier:
                    raise FurnitureError(409, "发布请求标识已用于其他草稿")
                publication = json.loads(previous["body"])
                self.active_asset(connection, publication["id"])
                return publication
            draft = self.get(connection, "furniture_drafts", identifier)
            self.editable(connection, draft, request.expectedVersion)
            result = draft.get("recognition") or {}
            multi_view_unknown = bool(result) and len(draft["photoUrls"]) > 1 and result.get("sameObject") is not True
            if multi_view_unknown or result.get("sameObject") is False or any(result.get(key) for key in ("multipleObjects", "viewConflict", "needsCrop")):
                raise FurnitureError(400, "图片目标不明确或视图冲突，请裁剪目标、拆图或补拍后新建识别，不能直接发布。")
            properties = FurnitureProperties.model_validate(draft["properties"]).model_dump()
            if any(properties[key] is None for key in ("category", "label", "width", "depth", "height", "frontDirection")):
                raise FurnitureError(400, "请补全名称、类别、宽深高和正面方向，再确认发布。")
            if not properties["label"].strip():
                raise FurnitureError(400, "家具名称不能为空")
            expected_direction = "negative_z" if "bed" in properties["category"] else "positive_z"
            if properties["frontDirection"] != expected_direction:
                raise FurnitureError(400, "床头须为局部 -z，其余家具正面须为局部 +z，请核对方向。")
            if not (self.uploads / "assets" / Path(request.assetUrl).name).is_file():
                raise FurnitureError(400, "请先通过资产接口上传已导出的 GLB")
            identifier_asset = draft.get("editingAssetId") or uuid.uuid4().hex
            version = 1
            if draft.get("editingAssetId"):
                current_asset = self.active_asset(connection, identifier_asset)
                if current_asset["version"] != draft["baseAssetVersion"]:
                    raise FurnitureError(409, "家具已被其他修订更新，请重新打开当前版本。")
                version = current_asset["version"] + 1
            snapshot = FurnitureSnapshot.model_validate({
                **{key: properties[key] for key in ("label", "category", "width", "depth", "height", "parameters", "dimensionSources", "frontDirection", "subtype", "styleTags")},
                "version": version, "photoUrls": draft["photoUrls"], "dimensionsConfirmed": True,
            }).model_dump()
            asset = {"id": identifier_asset, "version": version, "properties": properties, "photoUrls": draft["photoUrls"], "assetUrl": request.assetUrl, "snapshot": snapshot, "updatedAt": now()}
            draft.update(publishedAssetId=identifier_asset, version=draft["version"] + 1, updatedAt=now())
            self.put(connection, "furniture_assets", asset)
            self.put(connection, "furniture_drafts", draft)
            connection.execute("INSERT INTO furniture_publications VALUES (?,?,?)", (request.requestId, identifier, json.dumps(asset, ensure_ascii=False)))
        return deepcopy(asset)

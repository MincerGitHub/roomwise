from __future__ import annotations

import json
import os
from pathlib import Path
import struct
import time

import httpx


HUNYUAN_BASE_URL = "https://tokenhub.tencentmaas.com"
HUNYUAN_MODEL = "hy-3d-3.0"
HUNYUAN_FACE_COUNT = 10000
HUNYUAN_TIMEOUT = httpx.Timeout(1800, connect=20)
COS_BUCKET = "roomwise-1359876761"
COS_REGION = "ap-guangzhou"
COS_EXPIRED = 1800
HUNYUAN_VIEWS = {"left", "right", "back", "top", "bottom", "left_front", "right_front"}
APP_ROOT = Path(__file__).resolve().parents[2]


class ReconstructionError(Exception):
    pass


def _config():
    values = {}
    path = Path(os.getenv("ROOMWISE_HUNYUAN_ENV_FILE", str(APP_ROOT / ".env.hunyuan")))
    if path.is_file() and path.stat().st_size <= 64_000:
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            name, value = line.split("=", 1)
            name, value = name.strip(), value.strip().strip("'\"")
            if name in {"ROOMWISE_TOKENHUB_API_KEY", "TOKENHUB_API_KEY", "ROOMWISE_TOKENHUB_BASE_URL", "ROOMWISE_COS_PUBLIC_BASE_URL", "ROOMWISE_COS_SECRET_ID", "COS_SECRET_ID", "ROOMWISE_COS_SECRET_KEY", "COS_SECRET_KEY", "ROOMWISE_COS_BUCKET", "COS_BUCKET", "ROOMWISE_COS_REGION", "COS_REGION", "ROOMWISE_COS_SESSION_TOKEN", "COS_SESSION_TOKEN"}:
                values[name] = value
    def setting(*names, default=""):
        for name in names:
            if os.getenv(name) is not None:
                return os.getenv(name, "").strip()
            if name in values:
                return values[name].strip()
        return default
    key = setting("ROOMWISE_TOKENHUB_API_KEY", "TOKENHUB_API_KEY")
    base = setting("ROOMWISE_TOKENHUB_BASE_URL", default=HUNYUAN_BASE_URL).rstrip("/")
    cos = setting("ROOMWISE_COS_PUBLIC_BASE_URL", default="https://roomwise-1359876761.cos.ap-guangzhou.myqcloud.com").rstrip("/")
    secret_id = setting("ROOMWISE_COS_SECRET_ID", "COS_SECRET_ID")
    secret_key = setting("ROOMWISE_COS_SECRET_KEY", "COS_SECRET_KEY")
    bucket = setting("ROOMWISE_COS_BUCKET", "COS_BUCKET", default=COS_BUCKET)
    region = setting("ROOMWISE_COS_REGION", "COS_REGION", default=COS_REGION)
    token = setting("ROOMWISE_COS_SESSION_TOKEN", "COS_SESSION_TOKEN")
    return key, base, cos, secret_id, secret_key, bucket, region, token


def reconstruction_status():
    key, base, cos, secret_id, secret_key, bucket, region, token = _config()
    hunyuan_ready = bool(key)
    try:
        import qcloud_cos  # noqa: F401
        cos_sdk_ready = True
    except ImportError:
        cos_sdk_ready = False
    cos_ready = bool(secret_id and secret_key and bucket and region and cos_sdk_ready)
    enabled = hunyuan_ready and cos_ready
    missing = []
    if not hunyuan_ready: missing.append("ROOMWISE_TOKENHUB_API_KEY")
    if not cos_ready:
        missing.extend(["ROOMWISE_COS_SECRET_ID", "ROOMWISE_COS_SECRET_KEY"])
        if not cos_sdk_ready: missing.append("cos-python-sdk-v5")
    return {
        "enabled": enabled,
        "provider": "tencent-tokenhub",
        "model": HUNYUAN_MODEL,
        "baseUrl": base,
        "cosBaseUrl": cos,
        "cosBucket": bucket,
        "cosRegion": region,
        "message": (
            "TokenHub和COS已就绪"
            if enabled else
            "未配置：" + "、".join(missing)
        ),
    }


def validate_generated_glb(path: Path):
    if not path.is_file() or path.stat().st_size < 256 or path.stat().st_size > 50 * 1024 * 1024:
        raise ReconstructionError("混元返回的 GLB 文件不存在或超过 50 MB。")
    with path.open("rb") as handle:
        header = handle.read(20)
        if len(header) < 20:
            raise ReconstructionError("混元返回的 GLB 文件不完整。")
        magic, version, length = struct.unpack_from("<4sII", header)
        chunk_size, chunk_type = struct.unpack_from("<II", header, 12)
        if magic != b"glTF" or version != 2 or length != path.stat().st_size or chunk_type != 0x4E4F534A:
            raise ReconstructionError("混元返回的 GLB 文件头无效。")
        scene = json.loads(handle.read(chunk_size))
        primitives = [p for mesh in scene.get("meshes", []) for p in mesh.get("primitives", [])]
        accessors = scene.get("accessors", [])
        if not primitives or not accessors or not scene.get("buffers"):
            raise ReconstructionError("混元返回的 GLB 没有可用网格。")
        if not any(accessors[p["attributes"]["POSITION"]]["count"] >= 4 for p in primitives):
            raise ReconstructionError("混元返回的 GLB 没有可用顶点。")
        handle.seek(20 + chunk_size)
        binary_chunk = handle.read(8)
        if len(binary_chunk) != 8 or struct.unpack("<II", binary_chunk)[1] != 0x004E4942:
            raise ReconstructionError("混元返回的 GLB 没有顶点数据。")


def _cos_client():
    _, _, _, secret_id, secret_key, _, region, token = _config()
    if not secret_id or not secret_key:
        raise ReconstructionError("未配置COS密钥")
    try:
        from qcloud_cos import CosConfig, CosS3Client
    except ImportError as exc:
        raise ReconstructionError("缺少COS SDK") from exc
    return CosS3Client(CosConfig(Region=region, SecretId=secret_id, SecretKey=secret_key, Token=token or None, Scheme="https"))


def _upload_photos(photos: list[Path], job_id: str) -> list[str]:
    client = _cos_client()
    _, _, _, _, _, bucket, _, _ = _config()
    urls = []
    for index, path in enumerate(photos):
        key = f"roomwise/furniture/{job_id}/photo_{index}.jpg"
        try:
            with path.open("rb") as handle:
                client.put_object(Bucket=bucket, Key=key, Body=handle, ContentType="image/jpeg")
            urls.append(client.get_presigned_download_url(Bucket=bucket, Key=key, Expired=COS_EXPIRED))
        except Exception as exc:
            raise ReconstructionError(f"COS上传失败：{str(exc)[:240]}") from exc
    return urls


def _response_body(response):
    try:
        body = response.json()
    except (ValueError, json.JSONDecodeError) as exc:
        raise ReconstructionError("TokenHub返回无效") from exc
    if response.status_code >= 400:
        detail = None
        if isinstance(body, dict):
            error = body.get("error") or body.get("Error")
            if isinstance(error, dict):
                detail = error.get("message") or error.get("Message") or error.get("code") or error.get("Code")
            detail = detail or body.get("message") or body.get("Message") or body.get("detail") or body.get("Msg") or body.get("Desc")
        raise ReconstructionError(f"TokenHub 接口请求失败：{detail or response.status_code}")
    if not isinstance(body, dict):
        raise ReconstructionError("TokenHub返回无效")
    return body


def _auth_headers():
    return {"Authorization": "Bearer " + _config()[0], "Content-Type": "application/json"}


def _submit(client, endpoint, image_urls, view_types):
    payload = {
        "model": HUNYUAN_MODEL,
        "image_url": image_urls[0],
        "generate_type": "Normal",
        "enable_pbr": True,
        "face_count": HUNYUAN_FACE_COUNT,
    }
    if len(image_urls) > 1:
        payload["multi_view_images"] = [
            {"view_type": view, "view_image_url": image_url}
            for image_url, view in zip(image_urls[1:], view_types[1:])
        ]
    response = client.post(endpoint + "/v1/api/3d/submit", headers=_auth_headers(), json=payload)
    result = _response_body(response)
    job_id = result.get("id")
    if not job_id:
        raise ReconstructionError("TokenHub未返回任务ID")
    return str(job_id)


def _query(client, endpoint, job_id):
    response = client.post(endpoint + "/v1/api/3d/query", headers=_auth_headers(), json={"model": HUNYUAN_MODEL, "id": job_id})
    return _response_body(response)


def _result_url(result):
    files = result.get("data") or []
    if isinstance(files, dict):
        files = [files]
    for item in files:
        if not isinstance(item, dict):
            continue
        url = item.get("url")
        if url and str(item.get("type", "")).lower() == "glb":
            return url
    return None

def reconstruct(photos: list[Path], output: Path, view_types: list[str] | None = None):
    if not 1 <= len(photos) <= 8 or any(not photo.is_file() for photo in photos):
        raise ReconstructionError("请上传1—8张图片")
    key, endpoint, _, secret_id, secret_key, _, _, _ = _config()
    if not key or not secret_id or not secret_key:
        raise ReconstructionError(reconstruction_status()["message"])
    views = list(view_types or (["front"] + ["left", "right", "back", "top", "bottom", "left_front", "right_front"][:len(photos) - 1]))
    if len(views) != len(photos):
        raise ReconstructionError("图片和角度数量不一致")
    if len(photos) > 1 and (any(view not in HUNYUAN_VIEWS for view in views[1:]) or len(set(views[1:])) != len(views[1:])):
        raise ReconstructionError("角度不能重复")
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        cos_urls = _upload_photos(photos, str(output.stem))
        with httpx.Client(timeout=HUNYUAN_TIMEOUT, follow_redirects=False, trust_env=False) as client:
            job_id = _submit(client, endpoint, cos_urls, views)
            deadline = time.monotonic() + 1800
            while time.monotonic() < deadline:
                result = _query(client, endpoint, job_id)
                status = str(result.get("status") or "").lower()
                if status == "failed":
                    raise ReconstructionError(str(result.get("error") or result.get("message") or "TokenHub 模型生成失败。"))
                if status == "completed" or _result_url(result):
                    url = _result_url(result)
                    if not url:
                        raise ReconstructionError("任务完成但无模型")
                    downloaded = client.get(url)
                    if downloaded.status_code >= 400:
                        raise ReconstructionError("模型下载失败")
                    output.write_bytes(downloaded.content)
                    validate_generated_glb(output)
                    return f"/uploads/assets/{output.name}"
                time.sleep(4)
            raise ReconstructionError("模型生成超时，请重试")
    except ReconstructionError:
        output.unlink(missing_ok=True)
        raise
    except httpx.TimeoutException:
        output.unlink(missing_ok=True)
        raise ReconstructionError("TokenHub超时，请重试") from None
    except httpx.HTTPError:
        output.unlink(missing_ok=True)
        raise ReconstructionError("无法连接TokenHub") from None
    except (OSError, ValueError, KeyError, struct.error, json.JSONDecodeError):
        output.unlink(missing_ok=True)
        raise ReconstructionError("模型文件无效，请重试") from None


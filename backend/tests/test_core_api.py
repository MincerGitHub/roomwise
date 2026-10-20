import uuid
import time

import pytest
from fastapi.testclient import TestClient
from fastapi.staticfiles import StaticFiles

from roomwise.catalog import demo_scene
from roomwise.main import app
from roomwise.storage import SceneStore


client = TestClient(app)


@pytest.fixture(autouse=True)
def isolated_store(tmp_path, monkeypatch):
    monkeypatch.setattr("roomwise.main.store", SceneStore(tmp_path / "api-scenes.sqlite3"))
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    monkeypatch.setattr("roomwise.main.UPLOADS", uploads)
    monkeypatch.setattr("roomwise.video.UPLOADS_ROOT", uploads)
    mount = next(route for route in app.routes if route.name == "uploads")
    monkeypatch.setattr(mount, "app", StaticFiles(directory=str(uploads)))


def test_public_routes_schema_and_command_work():
    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["commandParser"] == "offline_restricted_chinese"
    assert len(client.get("/catalog").json()["items"]) == 20
    scene = client.get("/demo").json()
    assert client.post("/validate", json={"scene": scene}).status_code == 200
    edited = client.post("/command", json={"scene": scene, "text": "旧书桌向右移动20厘米"})
    assert edited.status_code == 200
    assert edited.json()["action"] == "edit"
    moved = next(i for i in edited.json()["scene"]["items"] if i["id"] == "desk-1")
    assert abs(moved["x"] - 1.4) < 1e-6
    scene["items"][0]["width"] = -1
    assert client.post("/validate", json={"scene": scene}).status_code == 422


def test_api_prefix_and_static_upload_paths_do_not_conflict():
    assert client.get("/api/health").status_code == 200
    scene = client.get("/api/demo").json()
    generated = client.post("/api/generate", json={"scene": scene, "mode": "rules", "count": 1, "seed": 42})
    assert generated.status_code == 200
    candidates = generated.json()["candidates"]
    assert candidates
    assert all(candidate["validation"]["valid"] for candidate in candidates)
    assert all("quality" in candidate and "components" in candidate["quality"] for candidate in candidates)
    assert [candidate["score"] for candidate in candidates] == sorted(
        [candidate["score"] for candidate in candidates], reverse=True)
    assert client.get("/uploads/missing-test.png").status_code == 404
    assert client.get("/api/catalog").json()["items"] == client.get("/catalog").json()["items"]


def test_api_import_rejects_extra_fields_and_unsafe_asset_url():
    scene = demo_scene()
    scene["items"][0]["assetUrl"] = "../../private.glb"
    invalid = client.post("/api/scenes/save", json={"scene": scene})
    assert invalid.status_code == 422
    assert any("assetUrl" in part["loc"] for part in invalid.json()["detail"])
    scene["items"][0]["assetUrl"] = "/uploads/%2e%2e/private.glb"
    assert client.post("/api/validate", json={"scene": scene}).status_code == 422
    scene["items"][0]["assetUrl"] = None
    scene["unexpected"] = "value"
    assert client.post("/api/validate", json={"scene": scene}).status_code == 422


def test_api_optimistic_save_and_load():
    scene = demo_scene()
    scene["id"] = "test-" + uuid.uuid4().hex
    response = client.post("/scenes/save", json={"scene": scene})
    assert response.status_code == 200
    assert response.json()["version"] == 1
    assert client.post("/scenes/save", json={"scene": scene}).status_code == 409
    restored = client.get(f"/scenes/{scene['id']}")
    assert restored.json()["version"] == 1
    assert client.post("/scenes/save", json={"scene": restored.json()}).json()["version"] == 2


def test_reference_image_survives_save_load_and_rejects_data_uri():
    scene = demo_scene()
    scene["id"] = "reference-" + uuid.uuid4().hex
    scene["room"]["referenceImageUrl"] = "/uploads/assets/floor-reference.png"
    assert client.post("/api/scenes/save", json={"scene": scene}).status_code == 200
    restored = client.get(f"/api/scenes/{scene['id']}").json()
    assert restored["room"]["referenceImageUrl"] == scene["room"]["referenceImageUrl"]
    scene["room"]["referenceImageUrl"] = "data:image/png;base64,abc"
    assert client.post("/api/validate", json={"scene": scene}).status_code == 422
    scene["room"]["referenceImageUrl"] = "/uploads/%2e%2e/floor.png"
    assert client.post("/api/validate", json={"scene": scene}).status_code == 422


def test_upload_rejects_executable_invalid_image_external_gltf():
    assert client.post("/assets", files={"file": ("hack.exe", b"abc", "application/octet-stream")}).status_code == 415
    assert client.post("/assets", files={"file": ("pic.png", b"not an image", "image/png")}).status_code == 400
    assert client.post("/assets", files={"file": ("bad.glb", b"glTF", "model/gltf-binary")}).status_code == 400
    malicious = b'{"asset":{"version":"2.0"},"buffers":[{"uri":"../../secret.bin"}]}'
    assert client.post("/assets", files={"file": ("object.gltf", malicious, "model/gltf+json")}).status_code == 400
    assert client.post("/video/analyze", files={"file": ("x.exe", b"x", "application/octet-stream")}).status_code == 415


def test_command_negation_conflict_and_coordinates_are_safe():
    scene = demo_scene()
    assert client.post("/command", json={"scene": scene, "text": "旧书桌不要旋转90度"}).json()["action"] == "clarify"
    assert client.post("/command", json={"scene": scene, "text": "旧书桌不要锁定"}).json()["action"] == "clarify"
    assert client.post("/command", json={"scene": scene, "text": "旧书桌不靠窗"}).json()["action"] == "clarify"
    assert client.post("/command", json={"scene": scene, "text": "旧书桌锁定并旋转90度"}).json()["action"] == "clarify"
    valid = client.post("/command", json={"scene": scene, "text": "旧书桌移动到x=1,z=3"}).json()
    assert valid["action"] == "edit"
    bad = client.post("/command", json={"scene": scene, "text": "旧书桌移动到x=999,z=3"}).json()
    assert bad["action"] == "clarify"
    assert "scene" not in bad


def test_video_upload_job_and_served_frames_end_to_end(tmp_path, monkeypatch):
    import cv2
    import numpy as np
    import roomwise.video as video_module

    # Exercise real decoding/thread/frame serving while isolating inference.
    monkeypatch.setattr(video_module, "_get_detector", lambda: None)
    path = tmp_path / "generated-room.avi"
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 10, (320, 240))
    assert writer.isOpened()
    for frame_number in range(24):
        frame = np.full((240, 320, 3), 210, dtype=np.uint8)
        cv2.rectangle(frame, (25 + frame_number, 30), (130 + frame_number, 180), (50, 100, 140), 4)
        cv2.putText(frame, "ROOMWISE TEST", (12, 220), cv2.FONT_HERSHEY_SIMPLEX, .6, (0, 0, 0), 1)
        writer.write(frame)
    writer.release()
    response = client.post("/api/video/analyze", files={"file": (path.name, path.read_bytes(), "video/x-msvideo")})
    assert response.status_code == 200
    job_id = response.json()["jobId"]
    deadline = time.monotonic() + 15
    job = {}
    while time.monotonic() < deadline:
        job = client.get(f"/api/video/jobs/{job_id}").json()
        if job["status"] in ("complete", "failed"):
            break
        time.sleep(.05)
    assert job["status"] == "complete", job
    assert job["frames"]
    assert job["candidates"] == []
    assert client.get(job["frames"][0]["url"]).status_code == 200
    assert client.get("/api/video/jobs/not-a-real-job").status_code == 404

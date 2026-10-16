"""Actual media upload, asynchronous job polling and static-frame API checks.

The generated clip verifies integration only; it is not a recognition dataset.
No fake object candidate is injected into any API response.
"""
from io import BytesIO
from pathlib import Path
import time

import pytest
from fastapi.testclient import TestClient

from roomwise.main import app
from roomwise import video


def clip_bytes(tmp_path: Path) -> bytes:
    cv2 = pytest.importorskip("cv2")
    np = pytest.importorskip("numpy")
    destination = tmp_path / "api-test.avi"
    writer = cv2.VideoWriter(str(destination), cv2.VideoWriter_fourcc(*"MJPG"), 8, (160, 120))
    if not writer.isOpened():
        pytest.skip("MJPG test codec unavailable")
    for index in range(16):
        frame = np.full((120, 160, 3), (index * 10, 30, 70), dtype=np.uint8)
        cv2.putText(frame, f"{index}", (30, 65), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
        writer.write(frame)
    writer.release()
    return destination.read_bytes()


def poll(client: TestClient, job_id: str) -> dict:
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        response = client.get(f"/api/video/jobs/{job_id}")
        assert response.status_code == 200
        job = response.json()
        assert 0 <= job["progress"] <= 1
        if job["status"] in {"complete", "failed"}:
            return job
        time.sleep(0.03)
    pytest.fail("video API job did not finish within test timeout")


def test_api_upload_poll_and_jpeg_frame_with_real_detector(tmp_path):
    from PIL import Image

    with TestClient(app) as client:
        response = client.post("/api/video/analyze", files={"file": ("room.avi", clip_bytes(tmp_path), "video/x-msvideo")})
        assert response.status_code == 200, response.text
        job = poll(client, response.json()["jobId"])
        assert job["status"] == "complete", job.get("error")
        assert job["progress"] == 1
        assert job["frames"]
        assert job["requiresConfirmation"]
        if video.MODEL_PATH.exists():
            assert job["detector"]["available"]
            assert job["detector"]["trainedByTeam"] is False
        for candidate in job["candidates"]:
            assert candidate["category"] in {"chair", "sofa", "double_bed", "table"}
            assert candidate["requiresConfirmation"]
            assert candidate["dimensions"] is None
            assert candidate["roomPosition"] is None
        frame_response = client.get(job["frames"][0]["url"])
        assert frame_response.status_code == 200
        assert frame_response.headers["content-type"].startswith("image/jpeg")
        with Image.open(BytesIO(frame_response.content)) as image:
            assert image.size == (160, 120)
            image.verify()


def test_api_no_detector_returns_frames_and_no_candidates(tmp_path, monkeypatch):
    monkeypatch.setattr(video, "_get_detector", lambda: None)
    with TestClient(app) as client:
        response = client.post("/api/video/analyze", files={"file": ("room.avi", clip_bytes(tmp_path), "video/x-msvideo")})
        assert response.status_code == 200
        job = poll(client, response.json()["jobId"])
        assert job["status"] == "complete"
        assert job["detectorUnavailable"]
        assert not job["detector"]["available"]
        assert job["candidates"] == []
        assert client.get(job["frames"][0]["url"]).status_code == 200


def test_api_rejects_invalid_extension_empty_file_and_unknown_job():
    with TestClient(app) as client:
        assert client.post("/api/video/analyze", files={"file": ("payload.exe", b"content", "application/octet-stream")}).status_code == 415
        assert client.post("/api/video/analyze", files={"file": ("empty.mp4", b"", "video/mp4")}).status_code == 400
        assert client.get("/api/video/jobs/no-such-job").status_code == 404


def test_api_undecodable_media_ends_in_failed_job():
    with TestClient(app) as client:
        response = client.post("/api/video/analyze", files={"file": ("damaged.mp4", b"not encoded video", "video/mp4")})
        assert response.status_code == 200
        job = poll(client, response.json()["jobId"])
        assert job["status"] == "failed"
        assert job["candidates"] == []
        assert job["frames"] == []
        assert job["error"]

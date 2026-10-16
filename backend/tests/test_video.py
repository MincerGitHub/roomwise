"""Engineering video tests, not furniture recognition accuracy measurements."""
from pathlib import Path
import time

import pytest

from roomwise import video


def detection(category="chair", bbox=None, confidence=0.8):
    return {"category": category, "label": category, "bbox": bbox or [0.1, 0.1, 0.4, 0.6], "confidence": confidence}


def make_video(path: Path, seconds: int = 2, fps: int = 8) -> Path:
    cv2 = pytest.importorskip("cv2")
    np = pytest.importorskip("numpy")
    path.parent.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), fps, (160, 120))
    if not writer.isOpened():
        pytest.skip("MJPG test-video encoder unavailable")
    for index in range(seconds * fps):
        image = np.zeros((120, 160, 3), dtype=np.uint8)
        image[:] = (index * 15 % 255, 30, 60)
        cv2.rectangle(image, (10 + index % 30, 20), (80 + index % 30, 100), (255, 255, 255), 2)
        cv2.putText(image, str(index), (30, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
        writer.write(image)
    writer.release()
    return path


def wait_complete(job_id: str, timeout: float = 15):
    start = time.monotonic()
    while time.monotonic() - start < timeout:
        result = video.get_job(job_id)
        if result["status"] in {"complete", "failed"}:
            return result
        time.sleep(0.02)
    pytest.fail("video processing did not complete")


def test_short_track_reuses_adjacent_detection_without_inventing_dimensions():
    tracker = video.ShortTracker()
    tracker.update([detection()], 0, "/first.jpg")
    tracker.update([detection(confidence=0.9)], 1, "/second.jpg")
    candidates = tracker.candidates()
    assert len(candidates) == 1
    assert candidates[0]["observations"] == 2
    assert candidates[0]["frameUrl"] == "/second.jpg"
    assert candidates[0]["dimensions"] is None
    assert candidates[0]["roomPosition"] is None
    assert candidates[0]["requiresConfirmation"] is True


def test_track_does_not_claim_identity_after_camera_leaves():
    tracker = video.ShortTracker(max_gap=2)
    tracker.update([detection()], 0, "/first.jpg")
    tracker.update([detection()], 10, "/returned.jpg")
    assert len(tracker.candidates()) == 2


def test_two_same_category_objects_remain_distinct_and_classes_do_not_merge():
    tracker = video.ShortTracker()
    detections = [detection(), detection(bbox=[0.6, 0.1, 0.9, 0.6]), detection(category="sofa")]
    tracker.update(detections, 0, "/first.jpg")
    tracker.update(detections, 1, "/second.jpg")
    assert len(tracker.candidates()) == 3
    assert all(candidate["observations"] == 2 for candidate in tracker.candidates())


def test_upload_path_and_filename_are_bounded(tmp_path):
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    outside = tmp_path / "outside.mp4"
    outside.write_bytes(b"not a video")
    with pytest.raises(ValueError, match="上传目录"):
        video.start_analysis(outside, uploads)
    invalid = uploads / "bad.exe"
    invalid.write_bytes(b"not a video")
    with pytest.raises(ValueError, match="格式"):
        video.start_analysis(invalid, uploads)
    assert video.get_frame_path("../../../", "frame-000.jpg") is None
    assert video.get_frame_path("ok", "../../outside.mp4") is None


def test_generated_video_extracts_real_frames_and_never_fake_detections(tmp_path, monkeypatch):
    uploads = tmp_path / "uploads"
    source = make_video(uploads / "videos" / "generated.avi")
    monkeypatch.setattr(video, "_get_detector", lambda: None)
    job_id = video.start_analysis(source, uploads)
    result = wait_complete(job_id)
    assert result["status"] == "complete", result.get("error")
    assert result["detectorUnavailable"] is True
    assert result["detector"]["available"] is False
    assert result["candidates"] == []
    assert 1 <= len(result["frames"]) <= video.MAX_KEYFRAMES
    assert result["progress"] == 1
    assert result["requiresConfirmation"] is True
    for frame in result["frames"]:
        filename = frame["url"].rsplit("/", 1)[1]
        assert video.get_frame_path(job_id, filename).is_file()
        assert frame["sharpness"] >= 0
        assert 0 <= frame["timestamp"] <= result["video"]["duration"]
    # This deliberately tests codecs, bounds and fallback; it says nothing about
    # real furniture recognition accuracy.


def test_undecodable_upload_fails_honestly(tmp_path):
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    invalid = uploads / "bad.mp4"
    invalid.write_bytes(b"not a video")
    result = wait_complete(video.start_analysis(invalid, uploads))
    assert result["status"] == "failed"
    assert result["candidates"] == []
    assert "error" in result


def test_long_video_rejected_before_extracting_frames(tmp_path):
    uploads = tmp_path / "uploads"
    source = make_video(uploads / "too_long.avi", seconds=121, fps=1)
    result = wait_complete(video.start_analysis(source, uploads))
    assert result["status"] == "failed"
    assert "120秒" in result["error"]
    assert result["frames"] == []


def test_official_model_real_inference_shapes_if_downloaded():
    np = pytest.importorskip("numpy")
    pytest.importorskip("onnxruntime")
    if not video.MODEL_PATH.exists():
        pytest.skip("optional official detector not downloaded")
    detector = video.YoloXTinyDetector(video.MODEL_PATH)
    output = detector.detect(np.zeros((120, 160, 3), dtype=np.uint8))
    assert isinstance(output, list)
    for candidate in output:
        assert candidate["category"] in {"chair", "sofa", "double_bed", "table"}
        assert len(candidate["bbox"]) == 4
        assert all(0 <= value <= 1 for value in candidate["bbox"])
        assert 0.4 <= candidate["confidence"] <= 1
    # A single blank frame is a runtime smoke test, not an accuracy benchmark.

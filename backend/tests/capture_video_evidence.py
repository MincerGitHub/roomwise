"""Save a reproducible real API video job; no accuracy claims or fake detections."""
import json
from pathlib import Path
import time

import cv2
import numpy as np
from fastapi.testclient import TestClient

from roomwise.main import app
from roomwise.video import APP_ROOT


def main():
    root = APP_ROOT / "artifacts" / "detectors" / "integration_evidence"
    root.mkdir(parents=True, exist_ok=True)
    source = root / "generated_engineering_clip.avi"
    writer = cv2.VideoWriter(str(source), cv2.VideoWriter_fourcc(*"MJPG"), 10, (640, 360))
    if not writer.isOpened():
        raise RuntimeError("MJPG codec unavailable")
    for index in range(30):
        frame = np.full((360, 640, 3), (20, 30, 45), dtype=np.uint8)
        cv2.putText(frame, "ROOMWISE VIDEO INTAKE", (30, 90), cv2.FONT_HERSHEY_SIMPLEX, 1, (240, 230, 200), 2)
        cv2.putText(frame, f"Engineering clip / frame {index:02d}", (30, 155), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (120, 200, 240), 2)
        cv2.rectangle(frame, (50 + index * 3, 200), (200 + index * 3, 310), (70, 150, 200), 3)
        cv2.putText(frame, "Not a furniture accuracy benchmark", (30, 340), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (200, 200, 200), 1)
        writer.write(frame)
    writer.release()
    with TestClient(app) as client:
        response = client.post("/api/video/analyze", files={"file": (source.name, source.read_bytes(), "video/x-msvideo")})
        response.raise_for_status()
        job_id = response.json()["jobId"]
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            response = client.get(f"/api/video/jobs/{job_id}")
            response.raise_for_status()
            job = response.json()
            if job["status"] in {"complete", "failed"}:
                break
            time.sleep(0.03)
        else:
            raise RuntimeError("Video processing timed out")
        (root / "completed_job.json").write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")
        for index, frame in enumerate(job["frames"]):
            response = client.get(frame["url"])
            response.raise_for_status()
            (root / f"frame-{index:03d}.jpg").write_bytes(response.content)
        (root / "README.md").write_text(
            "# Actual video API integration evidence\n\n"
            "The source AVI was created locally by capture_video_evidence.py. It contains "
            "text and geometric shapes, with no third-party photo or furniture model. "
            "The real upload, job polling, frame extraction, actual YOLOX-Tiny inference "
            "and static frame download were executed. No mock candidate was injected.\n\n"
            "This is an integration check, not furniture recognition accuracy evidence. "
            "Source, frames and raw completed-job JSON are retained. API frame URLs "
            "depend on this job's runtime upload files. Restarting the server clears "
            "the in-memory job index. Progress uses a 0..1 fraction.\n",
            encoding="utf-8",
        )
        print(json.dumps({"jobId": job_id, "status": job["status"], "frames": len(job["frames"]), "candidates": len(job["candidates"]), "detector": job["detector"], "evidence": str(root)}, ensure_ascii=False))


if __name__ == "__main__":
    main()

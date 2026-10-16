# Actual video API integration evidence

The source AVI was created locally by capture_video_evidence.py. It contains text and geometric shapes, with no third-party photo or furniture model. The real upload, job polling, frame extraction, actual YOLOX-Tiny inference and static frame download were executed. No mock candidate was injected.

This is an integration check, not furniture recognition accuracy evidence. Source, frames and raw completed-job JSON are retained. API frame URLs depend on this job's runtime upload files. Restarting the server clears the in-memory job index. Progress uses a 0..1 fraction.

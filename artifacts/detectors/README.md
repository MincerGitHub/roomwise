# Video intake detector

`yolox_tiny.onnx` is the official **pretrained YOLOX-Tiny** model. It is not a
Roomwise-trained model and does not contribute to the claim of independently
training the furniture layout model. It was successfully loaded and run on CPU
with ONNX Runtime. Source URLs, actual SHA-256, byte size and tensor shapes are
recorded in `manifest.json`. The upstream Apache-2.0 license text is retained in
`YOLOX_LICENSE.txt`; the official release does not include a separate model
license document.

Download or restore it with:

```powershell
conda activate roomwise
Set-Location D:\code\pythonProjects\roomwise\app
python backend/scripts/download_video_model.py
```

The module only exposes these COCO classes:

| COCO class | Scene default | User confirmation |
|---|---|---|
| chair | chair | Chair type, quantity, dimensions |
| couch | sofa | Dimensions, position |
| bed | double_bed | Single/double/kids type and dimensions |
| dining table | table | Table/desk purpose and dimensions |

Cabinets, wardrobes, curtains and all other categories need manual intake.
`confidence` is the detector score, not a calibrated probability of correctness.
Bounding boxes are normalized `xyxy` within the saved image; they are not floor
plan coordinates. No dimensions, depth or precise world position are inferred.

The module chooses the sharpest of up to three nearby frames in each temporal
window, retains up to 32 distinct views, and associates detections only across
short adjacent intervals using category and 2D IoU. Camera movement, occlusion
and returning to an earlier view can still duplicate candidates. The user must
merge/delete/confirm candidates before adding them to the room.

Limits: 100 MB, 120 seconds, 7200 total source frames, metadata resolution at most
3840 × 2160, one background worker and at most four active jobs. Inputs are decoded
as media only and must live below the local upload root. If the detector is
missing or cannot run, keyframes remain available and the job honestly reports
`detectorUnavailable`; it never invents detections.

`backend/tests/test_video.py` tests actual codec extraction, ONNX invocation,
fallback, adjacent tracking and input bounds. Generated test videos are
**engineering smoke tests, not furniture recognition accuracy measurements**.
There is currently no project-specific real video accuracy benchmark.

References:

- Official ONNX release and deployment documentation:
  <https://github.com/Megvii-BaseDetection/YOLOX/blob/main/demo/ONNXRuntime/README.md>
- Upstream preprocessing:
  <https://github.com/Megvii-BaseDetection/YOLOX/blob/main/yolox/data/data_augment.py>
- Upstream raw-output decoding:
  <https://github.com/Megvii-BaseDetection/YOLOX/blob/main/yolox/utils/demo_utils.py>
- License:
  <https://github.com/Megvii-BaseDetection/YOLOX/blob/main/LICENSE>

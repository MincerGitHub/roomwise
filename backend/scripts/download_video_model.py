"""Download the official YOLOX-Tiny ONNX model, recording source and checksum.

Run with the application's Python environment. No project dependencies are
installed here. The upstream repository publishes the model URL and Apache-2.0
LICENSE; this script retains both rather than downloading an unknown mirror.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import time
import urllib.request


APP_ROOT = Path(__file__).resolve().parents[2]
MODEL_URL = "https://github.com/Megvii-BaseDetection/YOLOX/releases/download/0.1.1rc0/yolox_tiny.onnx"
LICENSE_URL = "https://raw.githubusercontent.com/Megvii-BaseDetection/YOLOX/main/LICENSE"
DOCUMENTATION = "https://github.com/Megvii-BaseDetection/YOLOX/blob/main/demo/ONNXRuntime/README.md"
SOURCES = [
    "https://github.com/Megvii-BaseDetection/YOLOX/blob/main/yolox/data/data_augment.py",
    "https://github.com/Megvii-BaseDetection/YOLOX/blob/main/yolox/utils/demo_utils.py",
]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def download(url: str, path: Path, max_bytes: int) -> None:
    temporary = path.with_suffix(path.suffix + ".partial")
    request = urllib.request.Request(url, headers={"User-Agent": "Roomwise-research/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=60) as response, temporary.open("wb") as handle:
            total = 0
            while block := response.read(1024 * 1024):
                total += len(block)
                if total > max_bytes:
                    raise ValueError("Downloaded file exceeds expected size limit")
                handle.write(block)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def download_with_retries(url: str, path: Path, max_bytes: int) -> None:
    for attempt in range(3):
        try:
            download(url, path, max_bytes)
            return
        except Exception:
            if attempt == 2:
                raise
            time.sleep(1 + attempt)


def download_license(path: Path) -> str:
    try:
        download_with_retries(LICENSE_URL, path, 100 * 1024)
        return LICENSE_URL
    except Exception:
        # GitHub's official API is useful where raw.githubusercontent is blocked.
        url = "https://api.github.com/repos/Megvii-BaseDetection/YOLOX/contents/LICENSE"
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "Roomwise-research/1.0"})
            with urllib.request.urlopen(request, timeout=30) as response:
                data = json.load(response)
            content = base64.b64decode(data["content"], validate=False)
        except Exception:
            # Public HTML contains the same file in its JSON payload, without
            # requiring an authenticated GitHub API token.
            url = "https://github.com/Megvii-BaseDetection/YOLOX/blob/main/LICENSE"
            request = urllib.request.Request(url, headers={"User-Agent": "Roomwise-research/1.0"})
            with urllib.request.urlopen(request, timeout=30) as response:
                html = response.read(2 * 1024 * 1024).decode("utf-8")
            match = re.search(r'"rawLines":(\[.*?\]),"', html)
            if not match:
                raise ValueError("Could not locate upstream license file in GitHub page")
            lines = json.loads(match.group(1))
            content = ("\n".join(lines) + "\n").encode("utf-8")
        if b"Apache License" not in content:
            raise ValueError("Unexpected upstream license content")
        path.write_bytes(content)
        return url


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=APP_ROOT / "artifacts" / "detectors")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    root = args.output.resolve()
    root.mkdir(parents=True, exist_ok=True)
    model = root / "yolox_tiny.onnx"
    license_path = root / "YOLOX_LICENSE.txt"
    if args.force or not model.exists():
        print("Downloading official YOLOX-Tiny ONNX...", flush=True)
        download_with_retries(MODEL_URL, model, 40 * 1024 * 1024)
    license_source = LICENSE_URL
    if args.force or not license_path.exists():
        license_source = download_license(license_path)
    if model.stat().st_size < 1024 * 1024:
        raise ValueError("Downloaded model is unexpectedly small")
    manifest = {
        "name": "YOLOX-Tiny",
        "file": model.name,
        "source": MODEL_URL,
        "repository": "https://github.com/Megvii-BaseDetection/YOLOX",
        "documentation": DOCUMENTATION,
        "preprocessingReferences": SOURCES,
        "repositoryLicense": "Apache-2.0",
        "licenseFile": license_path.name,
        "licenseSource": license_source,
        "licenseNote": "Official model linked from Apache-2.0 repository; retain upstream notices. No separate model license document is supplied in this release.",
        "downloadedAtUtc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "sha256": sha256_file(model),
        "bytes": model.stat().st_size,
        "inputSize": [416, 416],
        "dataset": "COCO pretrained, not trained by the Roomwise team",
        "categoryCoverage": ["chair", "couch", "bed", "dining table"],
        "runtime": "ONNX Runtime CPU",
        "validation": "not_checked",
    }
    try:
        import onnxruntime as ort
        options = ort.SessionOptions()
        options.intra_op_num_threads = 2
        session = ort.InferenceSession(str(model), sess_options=options, providers=["CPUExecutionProvider"])
        manifest["inputTensor"] = [{"name": inp.name, "shape": inp.shape} for inp in session.get_inputs()]
        manifest["outputTensor"] = [{"name": out.name, "shape": out.shape} for out in session.get_outputs()]
        manifest["validation"] = "onnxruntime_session_loaded"
    except ImportError:
        manifest["validation"] = "onnxruntime_not_installed_yet"
    (root / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"model": str(model), "sha256": manifest["sha256"], "bytes": manifest["bytes"], "validation": manifest["validation"]}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()

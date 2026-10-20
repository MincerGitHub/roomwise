"""Build a private, offline Linux experiment bundle from an explicit allowlist.

The numeric dataset cache and locally trained reference weight are restricted
research inputs. This archive is for the user's own experiment server, not the
public source release. No network request or server process is started here.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import zipfile


APP = Path(__file__).resolve().parents[1]
PROJECT = APP.parent
PREFIX = "roomwise-experiments/"
SHAPELY_WHEEL = "shapely-2.0.7-cp310-cp310-manylinux_2_17_x86_64.manylinux2014_x86_64.whl"

# Only known experiment sources are allowed. Do not recursively collect app,
# runtime directories, SSH material, training environments or collection logs.
APP_FILES = (
    "backend/roomwise/__init__.py",
    "backend/roomwise/learning.py",
    "backend/roomwise/geometry.py",
    "backend/roomwise/catalog.py",
    "backend/roomwise/generator.py",
    "backend/roomwise/layout_templates.py",
    "backend/roomwise/bedside_constraints.py",
    "backend/roomwise/window_constraints.py",
    "backend/scripts/train_layout.py",
    "backend/scripts/evaluate_layout.py",
    "backend/scripts/evaluate_application.py",
    "backend/scripts/run_idle_experiments.py",
    "backend/scripts/prepare_new_server.py",
    "backend/tests/test_new_server_setup.py",
    "backend/tests/test_idle_experiments.py",
    "backend/tests/test_application_checkpoint.py",
    "docs/服务器空闲算力实验.md",
    "docs/新服务器推进指南.md",
    "docs/服务器实际运行记录_20261016.md",
    "docs/TRAINING.md",
    "CONTRACT.md",
    "LICENSE",
    "THIRD_PARTY.md",
)

CHECK_ENVIRONMENT = '''"""Manually check the dedicated experiment environment with a small CPU forward."""
import json
import os
from pathlib import Path
import sys

sys.dont_write_bytecode = True
os.environ["CUDA_VISIBLE_DEVICES"] = ""
for key in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ[key] = "1"
if sys.version_info < (3, 10):
    raise SystemExit("Python >= 3.10 is required. Do not upgrade the collection environment during collection.")
sys.path.insert(0, str(Path(__file__).resolve().parent / "app/backend"))
try:
    import numpy as np
    import torch
    import shapely
    from roomwise.learning import load_checkpoint
except ImportError as exc:
    raise SystemExit("Missing experiment dependency: " + str(exc) + ". Do not pip-install into the collection environment.")
torch.set_num_threads(1)
torch.set_num_interop_threads(1)
array = np.zeros((1, 24, 32), dtype=np.float32)
features = torch.from_numpy(array)
padding = torch.zeros((1, 24), dtype=torch.bool)
model = load_checkpoint(Path(__file__).resolve().parent / "baseline/models/layout_denoiser.pt", "cpu").eval()
with torch.inference_mode():
    result = model(features, padding)
if result.shape != (1, 24, 4) or result.device.type != "cpu" or not torch.isfinite(result).all():
    raise SystemExit("CPU model smoke check failed.")
print(json.dumps({"python": sys.version.split()[0], "numpy": np.__version__, "torch": torch.__version__,
                  "shapely": shapely.__version__, "device": "cpu", "threads": torch.get_num_threads(),
                  "cuda_disabled": os.environ["CUDA_VISIBLE_DEVICES"] == "", "check": "passed"}, ensure_ascii=False))
'''

PROBE_ENVIRONMENT = '''"""Read installed package metadata only; never import torch/numpy/shapely."""
import importlib.metadata as metadata
import json
import sys

sys.dont_write_bytecode = True
versions = {}
for name in ("numpy", "torch", "shapely"):
    try:
        versions[name] = metadata.version(name)
    except metadata.PackageNotFoundError:
        versions[name] = None
print(json.dumps({"python": sys.version.split()[0], "executable": sys.executable,
                  "packages": versions, "dependency_modules_imported": False,
                  "gpu_initialized": False, "installation_performed": False}))
'''

VERIFY_PACKAGE = '''"""Verify experiment inputs against the bundle manifest using only stdlib."""
import hashlib
import json
from pathlib import Path

root = Path(__file__).resolve().parent
manifest = json.loads((root / "package_manifest.json").read_text(encoding="utf-8"))
for record in manifest["files"]:
    target = (root / record["path"]).resolve()
    if root.resolve() not in target.parents or not target.is_file():
        raise SystemExit("Missing or invalid bundle path: " + record["path"])
    if target.stat().st_size != record["bytes"] or hashlib.sha256(target.read_bytes()).hexdigest() != record["sha256"]:
        raise SystemExit("Bundle integrity check failed: " + record["path"])
print(json.dumps({"verified_files": len(manifest["files"]), "private_transfer_only": manifest["private_transfer_only"]}))
'''

ENVIRONMENT_NOTES = """# Existing packages are checked before starting any experiment.
# Use prepare_new_server.py with Python 3.10-3.12 to create an independent environment.
# This is a compatibility guide, not a pip requirements lock for existing experiments.
# No torch wheel, CUDA package or pip cache is included in the bundle.
# One explicit CPython 3.10 manylinux x86_64 Shapely 2.0.7 wheel is included
# for OFFLINE installation into the separate experiment environment only.
# Wait until other timing-sensitive experiments finish before installing or running.
# Supported versions must pass check_environment.py on the actual Linux host.
numpy==1.26.4
torch==2.4.1
shapely==2.0.7
# matplotlib is optional; numeric evaluation does not require figures.
"""


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=APP / "release/Roomwise_server_experiments.zip")
    args = parser.parse_args()
    entries: dict[str, bytes] = {}

    def add(source: Path, destination: str) -> None:
        if not source.is_file():
            raise FileNotFoundError(f"Required experiment input is missing: {source}")
        if source.is_symlink():
            raise ValueError(f"Refusing a symlink in the transfer allowlist: {source}")
        if destination in entries or destination.startswith("/") or ".." in Path(destination).parts:
            raise ValueError(f"Invalid or repeated archive path: {destination}")
        entries[destination] = source.read_bytes()

    for relative in APP_FILES:
        add(APP / relative, f"app/{relative}")
    add(APP / "release/vendor/wheels" / SHAPELY_WHEEL, f"vendor/wheels/{SHAPELY_WHEEL}")
    for name in ("bedrooms_prepared.npz", "bedrooms_prepared.polygons.json"):
        add(PROJECT / "data/Roomwise" / name, f"data/Roomwise/{name}")
    for name in ("layout_denoiser.pt", "layout_denoiser.json"):
        add(APP / "artifacts/models" / name, f"baseline/models/{name}")
    for name in ("heldout_metrics.json", "app_metrics.json", "training_history.json"):
        add(APP / "artifacts/experiments" / name, f"baseline/experiments/{name}")

    # The original manifest contains the local absolute cache filename. Retain
    # scientific provenance but make the transferred metadata relative.
    source_manifest = json.loads((APP / "artifacts/experiments/data_manifest.json").read_text(encoding="utf-8"))
    source_manifest["cache"] = "data/Roomwise/bedrooms_prepared.npz"
    source_manifest["redistribution"] = "Private research transfer to the user's experiment server only; not a public dataset or open-source release."
    entries["data/Roomwise/data_manifest.json"] = json.dumps(source_manifest, ensure_ascii=False, indent=2).encode("utf-8")
    entries["check_environment.py"] = CHECK_ENVIRONMENT.encode("utf-8")
    entries["probe_environment.py"] = PROBE_ENVIRONMENT.encode("utf-8")
    entries["verify_package.py"] = VERIFY_PACKAGE.encode("utf-8")
    entries["requirements-experiment-notes.txt"] = ENVIRONMENT_NOTES.encode("utf-8")
    entries["PRIVATE_RESEARCH_INPUTS.txt"] = (
        "PRIVATE RESEARCH TRANSFER ONLY\n"
        "The 3D-FRONT/LEGO-Net numerical cache and locally trained reference weight are research inputs.\n"
        "Their inclusion does not grant redistribution rights or place them under the project's MIT licence.\n"
        "Upload only to your own authorised experiment server. Do not publish this ZIP, arrays, source-derived figures or weights.\n"
        "Source: https://ivl.cs.brown.edu/research/lego-net.html\n"
        "Dataset: https://tianchi.aliyun.com/specials/promotion/alibaba-3d-scene-dataset\n"
        "No server connection, dependency installation or remote job is performed by the packaging script.\n"
    ).encode("utf-8")
    manifest = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "private_transfer_only": True,
        "purpose": "Manual layout experiments on a dedicated server with an independent environment. No automatic queue or website deployment.",
        "files": [
            {"path": path, "bytes": len(value), "sha256": digest(value)}
            for path, value in sorted(entries.items())
        ],
        "excludes": ["frontend", "raw 513 MB dataset ZIP", "uploaded media", "collection logs", "SSH keys",
                     "virtualenv", "node_modules", "general wheel caches", "SQLite", "video detector weights", "API keys",
                     "automatic queues", "completion schedulers", "background launchers", "cron"],
        "linux_validation": "Bundle integrity and local smoke checks only; actual Linux environment and GPU execution require validation on the target host.",
    }
    entries["package_manifest.json"] = json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path, value in sorted(entries.items()):
            archive.writestr(PREFIX + path, value)
    with zipfile.ZipFile(temporary) as archive:
        if archive.testzip() is not None:
            raise RuntimeError("Archive integrity check failed")
    temporary.replace(args.output)
    release_manifest = {
        "file": args.output.name, "bytes": args.output.stat().st_size,
        "sha256": digest(args.output.read_bytes()), "files": len(entries),
        "private_transfer_only": True, "server_job_started": False,
    }
    manifest_path = args.output.with_suffix(".manifest.json")
    manifest_path.write_text(json.dumps(release_manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(release_manifest, ensure_ascii=False))


if __name__ == "__main__":
    main()

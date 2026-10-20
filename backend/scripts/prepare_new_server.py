"""Plan, or explicitly create, an independent Linux experiment environment.

The default only prints JSON. --create installs packages into a NEW virtual
environment and runs a small dependency check. It never trains, starts a web
service, schedules a task, or modifies an existing Python environment.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


APP = Path(__file__).resolve().parents[2]
BUNDLE = APP.parent
MIN_FREE_BYTES = 10 * 1024 ** 3
PYPI_INDEX = "https://pypi.org/simple"
TORCH_INDEX = {
    "cpu": "https://download.pytorch.org/whl/cpu",
    "cuda": "https://download.pytorch.org/whl/cu121",
}
DEPENDENCIES = ["numpy==1.26.4", "shapely==2.0.7"]


def environment_path(value: Path) -> Path:
    """Reject overwrites and paths overlapping code, inputs, or Python itself."""
    expanded = value.expanduser()
    if not expanded.is_absolute():
        raise ValueError("--env-dir must be an absolute path to a new directory.")
    if any(part.is_symlink() for part in (expanded, *expanded.parents)):
        raise ValueError("Environment path must not contain symbolic links.")
    target = expanded.resolve()
    if target.exists():
        raise ValueError("Environment directory already exists; it is never overwritten or reused.")
    reserved = [Path(path) for path in
                ("/usr", "/etc", "/bin", "/sbin", "/lib", "/lib64", "/proc", "/sys", "/dev", "/boot")]
    if target == Path(target.anchor) or any(root == target or root in target.parents for root in reserved):
        raise ValueError("A system directory cannot be used for the experiment environment.")
    protected = [Path(sys.prefix).resolve(), APP.resolve(),
                 (BUNDLE / "data").resolve(), (BUNDLE / "baseline").resolve(),
                 (BUNDLE / "vendor").resolve()]
    if any(target == source or target in source.parents or source in target.parents for source in protected):
        raise ValueError("Environment must not overlap the active Python, application, or research inputs.")
    return target


def installation_commands(target: Path, device: str) -> list[list[str]]:
    python = str(target / "bin/python")
    pip = [python, "-m", "pip", "--isolated", "install", "--no-cache-dir"]
    return [
        [sys.executable, "-m", "venv", str(target)],
        [*pip, "--index-url", PYPI_INDEX, *DEPENDENCIES],
        [*pip, "--index-url", TORCH_INDEX[device], "torch==2.4.1"],
    ]


def isolated_environment(device: str) -> dict[str, str]:
    environment = os.environ.copy()
    for name in ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV", "PIP_TARGET", "PIP_PREFIX", "PIP_USER"):
        environment.pop(name, None)
    environment.update(PYTHONDONTWRITEBYTECODE="1", PYTHONNOUSERSITE="1",
                       PIP_DISABLE_PIP_VERSION_CHECK="1", OMP_NUM_THREADS="1",
                       MKL_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1", NUMEXPR_NUM_THREADS="1")
    if device == "cpu":
        environment["CUDA_VISIBLE_DEVICES"] = ""
    return environment


def verify_platform() -> None:
    if sys.platform != "linux":
        raise ValueError("--create is for Linux. Plan mode is available on any operating system.")
    if not (3, 10) <= sys.version_info[:2] <= (3, 12):
        raise ValueError("Use Python 3.10, 3.11 or 3.12 for the pinned PyTorch 2.4.1 environment; do not upgrade system Python.")


def verify_disk(target: Path) -> None:
    existing = target.parent
    while not existing.exists():
        existing = existing.parent
    if not existing.is_dir() or shutil.disk_usage(existing).free < MIN_FREE_BYTES:
        raise ValueError("At least 10 GiB free space is required on the environment filesystem.")


def verify_cuda_driver(environment: dict[str, str]) -> list[dict]:
    """Query the driver without importing CUDA, then refuse an occupied GPU."""
    result = subprocess.run(
        ["nvidia-smi", "--query-gpu=name,driver_version,memory.total", "--format=csv,noheader,nounits"],
        env=environment, check=True, capture_output=True, text=True, timeout=10,
    )
    devices = []
    for row in csv.reader(io.StringIO(result.stdout)):
        if len(row) != 3:
            raise ValueError("Could not parse GPU details from nvidia-smi.")
        name, version, memory = (part.strip() for part in row)
        try:
            driver = tuple(int(part) for part in version.split("."))
            memory_mib = int(memory)
        except ValueError as error:
            raise ValueError("Could not parse GPU driver or memory details.") from error
        if (driver + (0, 0, 0))[:3] < (525, 60, 13):
            raise ValueError("CUDA 12.1 requires Linux driver >= 525.60.13; this script never changes drivers.")
        devices.append({"name": name, "driver": version, "memory_mib": memory_mib})
    if not devices:
        raise ValueError("No NVIDIA GPU was reported. Use --device cpu or check the server image.")
    active = subprocess.run(
        ["nvidia-smi", "--query-compute-apps=pid", "--format=csv,noheader,nounits"],
        env=environment, check=True, capture_output=True, text=True, timeout=10,
    )
    if active.stdout.strip():
        raise ValueError("GPU compute processes are present. No environment was created; retry manually when idle.")
    return devices


def dependency_check(device: str) -> str:
    # No dataset or model is loaded, and no training is performed.
    return (
        "import json,numpy,torch,shapely; "
        "torch.set_num_threads(1); "
        f"device={device!r}; "
        "assert device!='cuda' or torch.cuda.is_available(), 'CUDA is unavailable'; "
        "x=torch.ones((2,2),device=device); "
        "assert float((x@x).sum().item())==8.0; "
        "print(json.dumps({'check':'passed','device':device,'torch':torch.__version__,"
        "'numpy':numpy.__version__,'shapely':shapely.__version__}))"
    )


def create_environment(target: Path, device: str) -> dict:
    verify_platform()
    target = environment_path(target)
    verify_disk(target)
    environment = isolated_environment(device)
    gpu = verify_cuda_driver(environment) if device == "cuda" else []
    # mkdir is exclusive: even a directory created between preflight and here
    # cannot be silently reused. A failed install is left for manual inspection.
    target.mkdir(parents=True, exist_ok=False)
    for command in installation_commands(target, device):
        subprocess.run(command, env=environment, check=True)
    python = str(target / "bin/python")
    subprocess.run([python, "-c", dependency_check(device)], env=environment, check=True)
    check = BUNDLE / "check_environment.py"
    if check.is_file():
        subprocess.run([python, str(check)], cwd=BUNDLE,
                       env=isolated_environment("cpu"), check=True)
    return {"status": "prepared_only", "environment": str(target), "device": device,
            "gpu": gpu, "training_started": False, "queue_created": False,
            "web_service_started": False}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-dir", type=Path, default=BUNDLE / ".roomwise-venv")
    parser.add_argument("--device", choices=("cpu", "cuda"), default="cpu")
    parser.add_argument("--create", action="store_true", help="create a new environment and install dependencies; never starts training")
    args = parser.parse_args(argv)
    try:
        target = environment_path(args.env_dir)
        if not args.create:
            print(json.dumps({"status": "plan_only", "environment": str(target),
                              "device": args.device, "requires": "Linux, Python 3.10-3.12, >=10 GiB free disk",
                              "commands": installation_commands(target, args.device),
                              "environment_created": False, "training_started": False,
                              "queue_created": False, "web_service_started": False}, ensure_ascii=False))
            return 0
        print(json.dumps(create_environment(target, args.device), ensure_ascii=False))
        return 0
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        parser.error(str(error))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

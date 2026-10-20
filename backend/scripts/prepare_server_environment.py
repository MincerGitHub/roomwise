"""Plan, or manually prepare an isolated environment after acquisition ends.

Stdlib only. No waiting, queue, training, automatic scheduling, or CUDA import.
Without --create the command only prints a plan. With --create it requires a
verified complete collection, no live profile_full.py, and no GPU compute job.
The collector environment is read-only; packages are installed only in a new
experiment virtual environment from the bundled offline wheel directory.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys

APP = Path(__file__).resolve().parents[2]
BUNDLE = APP.parent


def isolated_paths(collector_env: Path, env_dir: Path) -> tuple[Path, Path]:
    if env_dir.is_symlink():
        raise ValueError("Experiment environment must not be a symbolic link.")
    collector, experiment = collector_env.resolve(), env_dir.resolve()
    if collector == experiment or collector in experiment.parents or experiment in collector.parents:
        raise ValueError("Experiment and collector environments must have no parent/child overlap.")
    return collector, experiment


def collector_site_packages(collector: Path) -> Path:
    """Read configuration only, never execute the collector interpreter."""
    cfg = collector / "pyvenv.cfg"
    values = dict(line.split("=", 1) for line in cfg.read_text().splitlines() if "=" in line)
    values = {key.strip(): value.strip() for key, value in values.items()}
    match = re.match(r"(\d+)\.(\d+)", values.get("version", ""))
    if not match:
        raise ValueError("Collector pyvenv.cfg must record its Python version.")
    version = tuple(map(int, match.groups()))
    if version < (3, 10) or version != sys.version_info[:2]:
        raise ValueError("Use the same Python major/minor version as the collector, at least Python 3.10.")
    site = collector / "lib" / f"python{version[0]}.{version[1]}" / "site-packages"
    if not site.is_dir():
        raise ValueError("Collector site-packages directory is missing.")
    return site.resolve()


def verify_completion(path: Path, expected_fingerprint: str) -> dict:
    if not re.fullmatch(r"[0-9a-f]{64}", expected_fingerprint):
        raise ValueError("Expected fingerprint must be the recorded 64-character SHA256.")
    marker = json.loads(path.read_text(encoding="utf-8"))
    expected = {
        "full_trainval_complete": True, "selected_scope_complete": True,
        "completed_chunks": 1089, "requested_chunks": 1089,
        "remaining_chunks": 0, "actions_per_chunk": 100, "error": None,
        "cpu_debug_only": False, "fingerprint": expected_fingerprint,
    }
    mismatches = [key for key, value in expected.items()
                  if key not in marker or type(marker[key]) is not type(value) or marker[key] != value]
    if mismatches:
        raise ValueError("Collection is not verified complete; marker fields differ: " + ", ".join(mismatches))
    return marker


def verify_collector_exited(pid: int, proc: Path = Path("/proc")) -> None:
    if pid <= 1 or pid == os.getpid():
        raise ValueError("Provide the original collector PID greater than 1.")
    directory = proc / str(pid)
    if directory.exists():
        state = next((line.split()[1] for line in (directory / "status").read_text().splitlines()
                      if line.startswith("State:")), None)
        if state not in {"Z", "X"}:
            raise ValueError("Original collector PID is still live, or its PID has been reused.")
    for entry in proc.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            argv = [part.decode(errors="replace") for part in
                    (entry / "cmdline").read_bytes().split(b"\0") if part]
        except FileNotFoundError:
            continue
        if any(Path(argument).name == "profile_full.py" for argument in argv[1:]):
            raise ValueError(f"A profile_full.py process is still live: PID {entry.name}.")


def verify_gpu_free() -> None:
    result = subprocess.run(
        ["nvidia-smi", "--query-compute-apps=pid", "--format=csv,noheader,nounits"],
        capture_output=True, text=True, check=True, timeout=10,
    )
    if result.stdout.strip():
        raise ValueError("GPU compute processes are still present; environment preparation was not started.")


def prepare_environment(args) -> dict:
    """Run only after explicit --create, never invoked by the default plan mode."""
    if sys.platform != "linux" or sys.version_info < (3, 10):
        raise ValueError("Environment creation requires Linux and Python 3.10 or later.")
    if args.completion is None or args.collector_pid is None or not args.expected_fingerprint:
        raise ValueError("--create requires --completion, --collector-pid and --expected-fingerprint.")
    collector, experiment = isolated_paths(args.collector_env, args.env_dir)
    site = collector_site_packages(collector)
    marker = verify_completion(args.completion, args.expected_fingerprint)
    verify_collector_exited(args.collector_pid)
    verify_gpu_free()
    if experiment.exists():
        raise ValueError("Use a new experiment environment directory; an existing environment is never overwritten.")
    wheels = BUNDLE / "vendor/wheels"
    if not list(wheels.glob("shapely-2.0.7-*.whl")):
        raise ValueError("Bundled offline Shapely 2.0.7 wheel is missing.")
    check = BUNDLE / "check_environment.py"
    if not check.is_file():
        raise ValueError("Bundled CPU check_environment.py is missing.")
    env = os.environ.copy()
    env.update(PYTHONDONTWRITEBYTECODE="1", PYTHONNOUSERSITE="1", CUDA_VISIBLE_DEVICES="",
               OMP_NUM_THREADS="1", MKL_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1",
               NUMEXPR_NUM_THREADS="1", PIP_DISABLE_PIP_VERSION_CHECK="1")
    # Clear inherited activated-venv and Python search paths before starting the
    # independent environment. All subprocess commands are structured argv.
    env.pop("PYTHONPATH", None)
    env.pop("PYTHONHOME", None)
    env.pop("VIRTUAL_ENV", None)
    subprocess.run([sys.executable, "-m", "venv", str(experiment)], env=env, check=True)
    own_site = experiment / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "site-packages"
    if not own_site.is_dir():
        raise ValueError("New environment site-packages directory was not created.")
    # A .pth contains only a path, never executable Python. The collector's
    # packages are reused for reading; bytecode writes are suppressed.
    (own_site / "roomwise_collector_readonly.pth").write_text(str(site) + "\n", encoding="utf-8")
    python = experiment / "bin/python"
    subprocess.run([str(python), "-m", "pip", "--isolated", "install", "--no-index", "--no-deps", "--ignore-installed",
                    "--find-links", str(wheels), "shapely==2.0.7"], env=env, check=True)
    subprocess.run([str(python), str(check)], cwd=BUNDLE, env=env, check=True)
    return {"status": "prepared_only", "environment": str(experiment),
            "collector_environment_read_only": str(collector), "collection_fingerprint": marker["fingerprint"],
            "gpu_used": False, "training_started": False, "queue_created": False}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--collector-env", type=Path, required=True)
    parser.add_argument("--env-dir", type=Path, default=BUNDLE / ".experiment-venv")
    parser.add_argument("--completion", type=Path)
    parser.add_argument("--collector-pid", type=int)
    parser.add_argument("--expected-fingerprint")
    parser.add_argument("--create", action="store_true", help="manually prepare only after successful collection and idle GPU checks")
    args = parser.parse_args(argv)
    try:
        collector, experiment = isolated_paths(args.collector_env, args.env_dir)
        if not args.create:
            print(json.dumps({"status": "plan_only", "collector_environment_read_only": str(collector),
                              "planned_environment": str(experiment), "offline_package": "shapely==2.0.7",
                              "requires_verified_collection_completion": True, "requires_idle_gpu": True,
                              "environment_created": False, "training_started": False, "queue_created": False},
                             ensure_ascii=False))
            return 0
        print(json.dumps(prepare_environment(args), ensure_ascii=False))
        return 0
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        parser.error(str(error))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

"""Manually started layout experiments, only after acquisition has finished.

There is no queue, waiting loop, or scheduled start. Validation selects the
checkpoint, and held-out data only reports the selected result. Defaults stay
CPU; CUDA needs an explicit option. The production checkpoint is preserved.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time
import zipfile

APP = Path(__file__).resolve().parents[2]
SCRIPTS = Path(__file__).resolve().parent


def experiment_environment(device: str, threads: int) -> dict[str, str]:
    """Prepare a child environment without changing the caller's environment."""
    environment = os.environ.copy()
    if device == "cpu":
        environment["CUDA_VISIBLE_DEVICES"] = ""
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    for name in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
        environment[name] = str(threads)
    return environment


def collector_pids(proc: Path = Path("/proc")) -> list[int]:
    if not sys.platform.startswith("linux"):
        return []
    result = []
    for entry in proc.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            arguments = [part.decode(errors="replace") for part in
                         (entry / "cmdline").read_bytes().split(b"\0") if part]
        except (FileNotFoundError, PermissionError, ProcessLookupError):
            continue
        if arguments and Path(arguments[0]).name == "ffmpeg":
            result.append(int(entry.name))
        elif arguments and Path(arguments[0]).name.startswith("python"):
            if any(Path(argument).name in {"profile_full.py", "stage.py"} for argument in arguments[1:]):
                result.append(int(entry.name))
    return result


def require_no_collection() -> None:
    pids = collector_pids()
    if pids:
        raise RuntimeError(f"A known acquisition or preprocessing task is still running (PIDs {pids}). No experiment was started; there is no queue.")


def require_free_gpu() -> None:
    result = subprocess.run(["nvidia-smi", "--query-compute-apps=pid", "--format=csv,noheader,nounits"],
                            capture_output=True, text=True, timeout=10, check=False)
    if result.returncode or result.stdout.strip():
        raise RuntimeError("GPU is busy or its status cannot be verified. No experiment was started.")


def child_parent_death_signal(expected_parent: int) -> None:
    import ctypes
    libc = ctypes.CDLL(None, use_errno=True)
    libc.prctl.argtypes = [ctypes.c_int, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong]
    libc.prctl.restype = ctypes.c_int
    if libc.prctl(1, int(signal.SIGKILL), 0, 0, 0) != 0:
        raise OSError(ctypes.get_errno(), "Could not set task parent-death signal")
    if os.getppid() != expected_parent:
        os.kill(os.getpid(), signal.SIGKILL)


def atomic_json(path: Path, value: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def read_metrics(path: Path) -> dict:
    report = json.loads(path.read_text(encoding="utf-8"))
    if report.get("evaluation_split") != "validation":
        raise ValueError("Only validation metrics may select a checkpoint.")
    level = next(row for row in report["levels"] if abs(row["position_noise_std_m"] - .45) < 1e-8)
    metrics = dict(level["methods"]["model_3_steps"])
    metrics["clean_position_drift_m"] = report["clean_layout_drift"]["position_mae_m"]
    for name in ("position_mae_m", "angle_mae_deg", "clean_position_drift_m",
                 "footprint_outside_item_rate", "overlap_pair_rate"):
        if not math.isfinite(metrics[name]) or metrics[name] < 0:
            raise ValueError(f"Invalid validation metric: {name}")
    return metrics


def candidate_eligible(candidate: dict, baseline: dict) -> bool:
    """Engineering comparison tolerances, not physical safety guarantees."""
    return (
        candidate["position_mae_m"] <= baseline["position_mae_m"] + .005
        and candidate["clean_position_drift_m"] <= baseline["clean_position_drift_m"] + .01
        and candidate["footprint_outside_item_rate"] <= baseline["footprint_outside_item_rate"] + .01
        and candidate["overlap_pair_rate"] <= baseline["overlap_pair_rate"] + .01
        and candidate["locked_position_max_change_m"] <= 1e-7
        and candidate["locked_angle_max_change_deg"] <= 1e-5
    )


def validation_score(metrics: dict) -> float:
    # Same position+angle criterion as original training; extra eligibility gates
    # prevent selecting a coordinate gain with appreciably worse drift/geometry.
    return metrics["position_mae_m"] + metrics["angle_mae_deg"] / 180


def child(script: str, arguments: list[str], log: Path, environment: dict[str, str]) -> None:
    require_no_collection()
    command = [sys.executable, str(SCRIPTS / script), *arguments]
    print(json.dumps({"command": command, "log": str(log)}, ensure_ascii=False), flush=True)
    with log.open("w", encoding="utf-8") as output:
        options = {}
        if sys.platform.startswith("linux"):
            parent = os.getpid()
            options["preexec_fn"] = lambda: child_parent_death_signal(parent)
        process = subprocess.Popen(command, cwd=APP, env=environment, stdout=output,
                                   stderr=subprocess.STDOUT, **options)
        try:
            while process.poll() is None:
                require_no_collection()
                time.sleep(2)
            result = process.returncode
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
    if result:
        raise RuntimeError(f"{script} exited with {result}; see {log}")


def create_result_archive(root: Path) -> Path:
    """Export this run only; omit source data, host credentials and old uploads."""
    destination = root.with_suffix(".results.zip")
    allowed = {".json", ".pt", ".log", ".png", ".md"}
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(root.rglob("*")):
            if (path.is_file() and not path.is_symlink() and path.suffix in allowed
                    and not path.name.endswith("_plot_polygons.json")
                    and not path.name.endswith("_examples.png")):
                archive.write(path, path.relative_to(root))
    return destination


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def materialize_selected(root: Path, selected: dict) -> dict:
    """Make a self-contained result, including an unchanged winning baseline.

    Copy bytes rather than reserialising a checkpoint: torch versions can
    produce different file hashes for an otherwise identical state dict.
    """
    source = Path(selected["checkpoint"]).resolve()
    source_metadata = source.with_suffix(".json")
    metadata = json.loads(source_metadata.read_text(encoding="utf-8"))
    expected = metadata["checkpoint_sha256"]
    if file_sha256(source) != expected:
        raise ValueError("Selected checkpoint does not match its recorded SHA256.")
    destination = root / "selected/models/layout_denoiser.pt"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination_metadata = destination.with_suffix(".json")
    shutil.copyfile(source, destination)
    shutil.copyfile(source_metadata, destination_metadata)
    if (file_sha256(destination) != expected
            or file_sha256(destination_metadata) != file_sha256(source_metadata)):
        raise ValueError("Selected checkpoint or metadata changed while copying.")
    return dict(selected, source_checkpoint=str(source),
                checkpoint=destination.relative_to(root).as_posix(),
                metadata=destination_metadata.relative_to(root).as_posix(),
                checkpoint_sha256=expected)


def interrupted(signum, frame):
    raise KeyboardInterrupt(f"Experiment interrupted by signal {signum}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=APP.parent / "data/Roomwise/bedrooms_prepared.npz")
    parser.add_argument("--baseline-checkpoint", type=Path,
                        default=APP.parent / "baseline/models/layout_denoiser.pt")
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--seeds", type=int, nargs="+", default=[20261014, 20261015])
    parser.add_argument("--epochs", type=int, default=40)
    parser.add_argument("--max-seconds-per-run", type=float, default=180)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--device", choices=("cpu", "cuda"), default="cpu")
    parser.add_argument("--threads", type=int, default=1)
    parser.add_argument("--smoke", action="store_true",
                        help="one short training run and validation; omit held-out evaluation")
    args = parser.parse_args()
    for name in ("SIGTERM", "SIGINT", "SIGHUP"):
        if hasattr(signal, name):
            signal.signal(getattr(signal, name), interrupted)
    if (args.epochs < 1 or not math.isfinite(args.max_seconds_per_run)
            or args.max_seconds_per_run <= 0 or args.batch_size < 1 or not 1 <= args.threads <= 4):
        parser.error("epochs, seconds and batch size must be positive; threads must be 1..4")
    require_no_collection()
    if args.device == "cuda":
        require_free_gpu()
    environment = experiment_environment(args.device, args.threads)
    data = args.data.resolve()
    checkpoint = args.baseline_checkpoint.resolve()
    for path in (data, data.with_suffix(".polygons.json"), checkpoint):
        if not path.is_file():
            parser.error(f"Required input missing: {path}")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    root = (args.output_dir or APP / "results" / f"idle-{stamp}-{os.getpid()}").resolve()
    production = (APP / "artifacts").resolve()
    if root == production or production in root.parents:
        parser.error("Use a separate result directory outside production artifacts")
    if root.exists() and any(root.iterdir()):
        parser.error("Output directory must be new or empty; existing results are preserved")
    root.mkdir(parents=True, exist_ok=True)
    report = {
        "started_at_utc": datetime.now(timezone.utc).isoformat(), "status": "running",
        "device": args.device, "threads": args.threads, "smoke": args.smoke,
        "baseline_checkpoint": str(checkpoint),
        "baseline_sha256": file_sha256(checkpoint),
        "selection_split": "validation", "heldout_for_selection": False,
        "selection_method": "position_mae_m + angle_mae_deg/180; eligibility gates for clean drift and geometry",
        "eligibility_tolerances": {"position_m": .005, "clean_drift_m": .01, "outside_rate": .01, "overlap_rate": .01},
        "limitations": ["Simulation on source bedrooms, not real moving-house observations.",
                        "Bounding-box intersections can include intended table/chair contact.",
                        "No candidate is automatically installed as the production model.",
                        "Manual experiments only after timing acquisition ends; no scheduled start or queue.",
                        "GPU compatibility still requires validation on the actual target machine.",
                        "Training chooses an epoch using one-step validation; this driver selects among saved checkpoints using three-step validation. It does not find the best three-step epoch.",
                        "The fixed test split was reported in earlier project experiments. Reuse is a descriptive regression benchmark, not a new untouched generalisation test."],
        "test_benchmark_previously_reported": True,
        "test_protocol": "Evaluate only the selected checkpoint once per full run; do not use this result to select a trial.",
        "trials": [],
    }
    summary = root / "experiment_summary.json"
    atomic_json(summary, report)
    common = ["--data", str(data), "--device", args.device, "--threads", str(args.threads),
              "--batch-size", str(args.batch_size)]
    try:
        baseline_root = root / "baseline"
        child("evaluate_layout.py", common + ["--checkpoint", str(checkpoint),
              "--output-dir", str(baseline_root), "--evaluate-split", "validation", "--no-figures"], root / "baseline_validation.log", environment)
        baseline = read_metrics(baseline_root / "experiments/validation_metrics.json")
        report["baseline_validation"] = baseline
        selected = {"name": "existing_baseline", "checkpoint": str(checkpoint),
                    "validation": baseline, "score": validation_score(baseline)}
        configurations = [(seed, clean) for seed in dict.fromkeys(args.seeds) for clean in (.12, .4)]
        if args.smoke:
            configurations = configurations[:1]
        for seed, clean in configurations:
            name = f"seed-{seed}-clean-{int(clean * 100)}"
            run_root = root / name
            child("train_layout.py", common + ["--resume-from", str(checkpoint),
                  "--output-dir", str(run_root), "--seed", str(seed),
                  "--clean-probability", str(clean), "--epochs", str(1 if args.smoke else args.epochs),
                  "--max-seconds", str(5 if args.smoke else args.max_seconds_per_run)], root / f"{name}_training.log", environment)
            trained = run_root / "models/layout_denoiser.pt"
            child("evaluate_layout.py", common + ["--checkpoint", str(trained),
                  "--output-dir", str(run_root), "--evaluate-split", "validation", "--no-figures"], root / f"{name}_validation.log", environment)
            evaluation = read_metrics(run_root / "experiments/validation_metrics.json")
            eligible = candidate_eligible(evaluation, baseline)
            score = validation_score(evaluation)
            trial = {"name": name, "seed": seed, "clean_probability": clean,
                     "checkpoint": str(trained), "validation": evaluation,
                     "eligible": eligible, "score": score}
            report["trials"].append(trial)
            if eligible and score < selected["score"]:
                selected = {"name": name, "checkpoint": str(trained), "validation": evaluation, "score": score}
            report["selected"] = selected
            atomic_json(summary, report)
        selected = materialize_selected(root, selected)
        report["selected"] = selected
        atomic_json(summary, report)
        if not args.smoke:
            child("evaluate_layout.py", common + ["--checkpoint", str(root / selected["checkpoint"]),
                  "--output-dir", str(root / "selected"), "--evaluate-split", "test", "--no-figures"], root / "selected_heldout.log", environment)
            report["heldout_report"] = "selected/experiments/heldout_metrics.json"
            report["heldout_used_to_select"] = False
        report["status"] = "completed_smoke" if args.smoke else "completed"
        report["selected"] = selected
        report["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
        atomic_json(summary, report)
        destination = create_result_archive(root)
        print(json.dumps({"summary": str(summary), "results_zip": str(destination),
                          "selected": selected["name"], "production_model_replaced": False}, ensure_ascii=False), flush=True)
    except BaseException as error:
        report["status"] = "failed_or_interrupted"
        report["error"] = str(error)
        atomic_json(summary, report)
        raise


if __name__ == "__main__":
    main()

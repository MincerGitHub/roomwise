"""Portable device selection and isolated, real CPU training/evaluation checks.

Synthetic inputs exercise execution and file contracts, not model accuracy.
No CUDA context or remote-server operation is needed for these tests.
"""
import json
from pathlib import Path
import subprocess
import sys
from unittest import mock

import numpy as np
import pytest

APP = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(APP / "backend"))
sys.path.insert(0, str(APP / "backend/scripts"))
from roomwise import learning
from train_layout import noisy_batch, predict


pytestmark = pytest.mark.skipif(learning.torch is None, reason="PyTorch not installed")


def synthetic_data(path):
    count = 6
    floor = np.array([[-2.5, -2], [2.5, -2], [2.5, 2], [-2.5, 2]], np.float32)
    data = {
        "pos": np.tile(np.array([[[-.8, 0], [1.6, 0]]], np.float32), (count, 1, 1)),
        "size": np.tile(np.array([[[1.4, 2, .6], [.6, 1.2, 2]]], np.float32), (count, 1, 1)),
        "angle": np.zeros((count, 2), np.float32),
        "classes": np.tile(np.array([[7, 18]], np.int64), (count, 1)),
        "boundary": np.tile(learning.boundary_points(floor)[None], (count, 1, 1)),
        "dims": np.tile(np.array([[5, 4]], np.float32), (count, 1)),
        "house": np.array([f"synthetic-house-{i}" for i in range(count)]),
        "split": np.array([0, 0, 0, 1, 1, 2]),
    }
    np.savez_compressed(path, **data)
    path.with_suffix(".polygons.json").write_text(json.dumps([floor.tolist()] * count), encoding="utf-8")
    return data


def run_script(script, *args):
    result = subprocess.run(
        [sys.executable, str(APP / "backend/scripts" / script), *map(str, args)],
        capture_output=True, text=True, encoding="utf-8", timeout=45,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return result


def test_cpu_default_does_not_probe_cuda():
    with mock.patch.object(learning.torch.cuda, "is_available", side_effect=AssertionError("CPU must not probe CUDA")):
        assert learning.resolve_device().type == "cpu"


def test_explicit_cuda_fails_without_gpu_instead_of_falling_back():
    with mock.patch.object(learning.torch.cuda, "is_available", return_value=False):
        with pytest.raises(RuntimeError, match="explicitly requested"):
            learning.resolve_device("cuda")


def test_clean_probability_and_cpu_prediction_preserve_input(tmp_path):
    data = synthetic_data(tmp_path / "data.npz")
    batch = noisy_batch(data, np.arange(3), np.random.default_rng(7), clean_probability=1)
    np.testing.assert_equal(batch["noisy_pos"], batch["pos"])
    np.testing.assert_equal(batch["noisy_angle"], batch["angle"])
    model = learning.LayoutDenoiser().eval()
    output_pos, output_angle = predict(model, batch)
    np.testing.assert_equal(output_pos, batch["noisy_pos"])
    np.testing.assert_equal(output_angle, batch["noisy_angle"])


def test_isolated_training_resume_and_validation_do_not_replace_live_artifacts(tmp_path):
    data_path = tmp_path / "data.npz"
    synthetic_data(data_path)
    live_checkpoint = learning.MODEL_PATH
    live_mtime = live_checkpoint.stat().st_mtime_ns if live_checkpoint.exists() else None
    first = tmp_path / "first"
    # Tiny time budget must stop after a real batch and still write honest metrics.
    run_script("train_layout.py", "--data", data_path, "--epochs", 3,
               "--batch-size", 2, "--threads", 1, "--max-seconds", .000001,
               "--clean-probability", .4, "--output-dir", first)
    metadata = json.loads((first / "models/layout_denoiser.json").read_text(encoding="utf-8"))
    history = json.loads((first / "experiments/training_history.json").read_text(encoding="utf-8"))
    assert metadata["device"] == "cpu"
    assert metadata["stop_reason"] == "max_seconds_reached"
    assert metadata["steps"] == 1
    assert metadata["clean_training_probability"] == .4
    assert history[0]["complete_epoch"] is False
    assert metadata["environment"]["gpu_name"] is None
    assert "T" in metadata["trained_at"]
    model = learning.load_checkpoint(first / "models/layout_denoiser.pt")
    assert next(model.parameters()).device.type == "cpu"
    saved = learning.torch.load(first / "models/layout_denoiser.pt", weights_only=True)
    assert all(tensor.device.type == "cpu" for tensor in saved["state_dict"].values())

    second = tmp_path / "second"
    run_script("train_layout.py", "--data", data_path, "--epochs", 1,
               "--batch-size", 2, "--threads", 1, "--max-seconds", 5,
               "--resume-from", first / "models/layout_denoiser.pt", "--output-dir", second)
    resumed = json.loads((second / "models/layout_denoiser.json").read_text(encoding="utf-8"))
    resumed_history = json.loads((second / "experiments/training_history.json").read_text(encoding="utf-8"))
    assert resumed_history[0] == history[0]
    assert resumed["steps"] > metadata["steps"]
    assert resumed["training_stages"][-1]["resume_source_sha256"] == metadata["checkpoint_sha256"]
    assert resumed["training_stages"][-1]["resumed"] is True

    run_script("evaluate_layout.py", "--data", data_path, "--threads", 1,
               "--checkpoint", second / "models/layout_denoiser.pt", "--output-dir", second,
               "--evaluate-split", "validation")
    report = json.loads((second / "experiments/validation_metrics.json").read_text(encoding="utf-8"))
    assert report["evaluation_split"] == "validation"
    assert report["evaluated_rooms"] == 2
    assert report["checkpoint_sha256"] == resumed["checkpoint_sha256"]
    assert "clean_layout_drift" in report
    assert not (second / "experiments/heldout_metrics.json").exists()
    assert (live_checkpoint.stat().st_mtime_ns if live_checkpoint.exists() else None) == live_mtime


def test_clean_probability_argument_rejects_out_of_range_before_training(tmp_path):
    result = subprocess.run(
        [sys.executable, str(APP / "backend/scripts/train_layout.py"),
         "--clean-probability", "1.2", "--output-dir", str(tmp_path / "unused")],
        capture_output=True, text=True, encoding="utf-8", timeout=30,
    )
    assert result.returncode != 0
    assert "between 0 and 1" in result.stderr
    assert not (tmp_path / "unused").exists()


@pytest.mark.parametrize("script", ["train_layout.py", "evaluate_layout.py"])
def test_explicit_research_output_cannot_overwrite_production(script):
    result = subprocess.run(
        [sys.executable, str(APP / "backend/scripts" / script),
         "--output-dir", str(APP / "artifacts/experiments")],
        capture_output=True, text=True, encoding="utf-8", timeout=30,
    )
    assert result.returncode != 0
    assert "outside production artifacts" in result.stderr

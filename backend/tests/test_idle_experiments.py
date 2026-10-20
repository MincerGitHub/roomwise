"""Prevent held-out model selection and harmful drift from small CPU trials."""
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock
import zipfile

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/run_idle_experiments.py"
spec = importlib.util.spec_from_file_location("idle_experiments", SCRIPT)
driver = importlib.util.module_from_spec(spec)
spec.loader.exec_module(driver)


def metrics():
    return {"position_mae_m": .2, "angle_mae_deg": 6,
            "clean_position_drift_m": .1, "footprint_outside_item_rate": .3,
            "overlap_pair_rate": .15, "locked_position_max_change_m": 0,
            "locked_angle_max_change_deg": 0}


class IdleExperimentChecks(unittest.TestCase):
    def test_stage_and_ffmpeg_are_busy_even_without_a_gpu_process(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            commands = {"10": b"python\0stage.py\0", "11": b"/usr/bin/ffmpeg\0-i\0video.mp4\0",
                        "12": b"python\0train_layout.py\0"}
            for pid, argv in commands.items():
                directory = root / pid
                directory.mkdir()
                (directory / "cmdline").write_bytes(argv)
            with mock.patch.object(driver.sys, "platform", "linux"):
                self.assertEqual(sorted(driver.collector_pids(root)), [10, 11])

    def test_environment_keeps_callers_gpu_selection_and_explicit_defaults(self):
        with mock.patch.dict(os.environ, {"CUDA_VISIBLE_DEVICES": "0", "OMP_NUM_THREADS": "7"}):
            cpu = driver.experiment_environment("cpu", 1)
            gpu = driver.experiment_environment("cuda", 2)
            self.assertEqual(cpu["CUDA_VISIBLE_DEVICES"], "")
            self.assertEqual(gpu["CUDA_VISIBLE_DEVICES"], "0")
            self.assertEqual(cpu["OMP_NUM_THREADS"], "1")
            self.assertEqual(gpu["OMP_NUM_THREADS"], "2")
            self.assertEqual(os.environ["OMP_NUM_THREADS"], "7")
            self.assertEqual(os.environ["CUDA_VISIBLE_DEVICES"], "0")

    def test_current_acquisition_refuses_experiment_without_waiting(self):
        with mock.patch.object(driver, "collector_pids", return_value=[348810]):
            with self.assertRaisesRegex(RuntimeError, "No experiment was started"):
                driver.require_no_collection()

    def test_busy_gpu_refuses_experiment(self):
        with mock.patch.object(driver.subprocess, "run", return_value=mock.Mock(returncode=0, stdout="348810\n")):
            with self.assertRaisesRegex(RuntimeError, "GPU is busy"):
                driver.require_free_gpu()

    def test_coordinate_gain_with_worse_drift_is_ineligible(self):
        baseline = metrics()
        trial = dict(baseline, position_mae_m=.15, clean_position_drift_m=.13)
        self.assertFalse(driver.candidate_eligible(trial, baseline))
        trial = dict(baseline, position_mae_m=.15, footprint_outside_item_rate=.35)
        self.assertFalse(driver.candidate_eligible(trial, baseline))

    def test_moving_locked_item_is_ineligible(self):
        baseline = metrics()
        self.assertFalse(driver.candidate_eligible(dict(baseline, locked_position_max_change_m=.01), baseline))
        self.assertTrue(driver.candidate_eligible(baseline, baseline))

    def test_heldout_report_cannot_select_checkpoint(self):
        with tempfile.TemporaryDirectory() as temporary:
            report = Path(temporary) / "metrics.json"
            report.write_text(json.dumps({"evaluation_split": "test"}))
            with self.assertRaisesRegex(ValueError, "validation"):
                driver.read_metrics(report)

    def test_return_archive_omits_source_polygons_and_arrays(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "run"
            root.mkdir()
            for name in ("validation_metrics.json", "validation_plot_polygons.json", "validation_examples.png", "cache.npz"):
                (root / name).write_text("{}")
            destination = driver.create_result_archive(root)
            with zipfile.ZipFile(destination) as archive:
                self.assertEqual(archive.namelist(), ["validation_metrics.json"])

    def test_selected_baseline_is_portable_and_copied_without_reserialising(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "baseline/models/layout_denoiser.pt"
            source.parent.mkdir(parents=True)
            source.write_bytes(b"original checkpoint bytes, not a reserialised state dict")
            metadata = source.with_suffix(".json")
            metadata.write_text(json.dumps({"checkpoint_sha256": driver.file_sha256(source)}))
            original_metadata = metadata.read_bytes()
            root = Path(temporary) / "run"
            selected = driver.materialize_selected(root, {"name": "existing_baseline", "checkpoint": str(source)})
            self.assertEqual(selected["checkpoint"], "selected/models/layout_denoiser.pt")
            self.assertEqual(selected["metadata"], "selected/models/layout_denoiser.json")
            self.assertEqual((root / selected["checkpoint"]).read_bytes(), source.read_bytes())
            self.assertEqual((root / selected["metadata"]).read_bytes(), original_metadata)
            self.assertEqual(selected["checkpoint_sha256"], driver.file_sha256(source))
            with zipfile.ZipFile(driver.create_result_archive(root)) as archive:
                self.assertEqual(archive.read(selected["checkpoint"]), source.read_bytes())
                self.assertEqual(archive.read(selected["metadata"]), original_metadata)

    def test_selected_checkpoint_hash_mismatch_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "baseline.pt"
            source.write_bytes(b"changed checkpoint")
            source.with_suffix(".json").write_text(json.dumps({"checkpoint_sha256": "0" * 64}))
            root = Path(temporary) / "run"
            with self.assertRaisesRegex(ValueError, "SHA256"):
                driver.materialize_selected(root, {"checkpoint": str(source)})
            self.assertFalse((root / "selected/models/layout_denoiser.pt").exists())

    def test_final_evaluation_uses_exported_checkpoint_when_baseline_wins(self):
        """Exercise the driver without importing torch or launching training."""
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            source = directory / "baseline/models/layout_denoiser.pt"
            source.parent.mkdir(parents=True)
            source.write_bytes(b"winning baseline")
            source.with_suffix(".json").write_text(json.dumps({"checkpoint_sha256": driver.file_sha256(source)}))
            data = directory / "bedrooms_prepared.npz"
            data.write_bytes(b"not opened by mocked child")
            data.with_suffix(".polygons.json").write_text("[]")
            root = directory / "run"
            evaluated_test_paths = []

            def fake_child(script, arguments, log, environment):
                output = Path(arguments[arguments.index("--output-dir") + 1])
                if script == "train_layout.py":
                    trained = output / "models/layout_denoiser.pt"
                    trained.parent.mkdir(parents=True)
                    trained.write_bytes(b"candidate with an equal validation score")
                    trained.with_suffix(".json").write_text(json.dumps({"checkpoint_sha256": driver.file_sha256(trained)}))
                else:
                    split = arguments[arguments.index("--evaluate-split") + 1]
                    if split == "test":
                        exported = Path(arguments[arguments.index("--checkpoint") + 1])
                        evaluated_test_paths.append(exported)
                        self.assertEqual(exported.read_bytes(), source.read_bytes())
                    experiments = output / "experiments"
                    experiments.mkdir(parents=True, exist_ok=True)
                    name = "validation_metrics.json" if split == "validation" else "heldout_metrics.json"
                    (experiments / name).write_text(json.dumps({
                        "evaluation_split": split,
                        "levels": [{"position_noise_std_m": .45, "methods": {"model_3_steps": metrics()}}],
                        "clean_layout_drift": {"position_mae_m": .1}}))

            arguments = [str(SCRIPT), "--data", str(data), "--baseline-checkpoint", str(source),
                         "--output-dir", str(root), "--seeds", "1"]
            with mock.patch.object(sys, "argv", arguments), mock.patch.object(driver, "child", side_effect=fake_child), \
                    mock.patch.object(driver, "require_no_collection"):
                driver.main()
            summary = json.loads((root / "experiment_summary.json").read_text())
            self.assertEqual(summary["selected"]["name"], "existing_baseline")
            self.assertEqual(evaluated_test_paths, [root / "selected/models/layout_denoiser.pt"])
            self.assertTrue(summary["test_benchmark_previously_reported"])
            with zipfile.ZipFile(root.with_suffix(".results.zip")) as archive:
                self.assertEqual(archive.read(summary["selected"]["checkpoint"]), source.read_bytes())


if __name__ == "__main__":
    unittest.main()

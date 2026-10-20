"""Manual preparation contracts; no real package installation or server calls."""
import argparse
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from unittest import mock

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/prepare_server_environment.py"
spec = importlib.util.spec_from_file_location("collection_setup", SCRIPT)
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)
FINGERPRINT = "b7a3518ac4de53a1e4f9c823dd269d6f03559bfbde56c38c91cc2056a1389df4"


def complete_marker(path):
    marker = {"full_trainval_complete": True, "selected_scope_complete": True,
              "completed_chunks": 1089, "requested_chunks": 1089, "remaining_chunks": 0,
              "actions_per_chunk": 100, "error": None, "cpu_debug_only": False,
              "fingerprint": FINGERPRINT}
    path.write_text(json.dumps(marker), encoding="utf-8")
    return marker


def test_default_only_prints_plan_without_subprocess_or_files(tmp_path, capsys):
    with mock.patch.object(setup.subprocess, "run", side_effect=AssertionError("plan must not execute")):
        assert setup.main(["--collector-env", str(tmp_path / "collector"),
                           "--env-dir", str(tmp_path / "new-env")]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "plan_only"
    assert not output["environment_created"]
    assert not output["training_started"]
    assert not output["queue_created"]
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("relationship", ["same", "inside", "parent"])
def test_environments_cannot_overlap(tmp_path, relationship):
    collector = tmp_path / "collector"
    experiment = {"same": collector, "inside": collector / "extra", "parent": tmp_path}[relationship]
    with pytest.raises(ValueError, match="overlap"):
        setup.isolated_paths(collector, experiment)


@pytest.mark.parametrize("field,value", [
    ("full_trainval_complete", False), ("selected_scope_complete", False),
    ("completed_chunks", 1088), ("remaining_chunks", 1), ("error", "interrupted"),
    ("cpu_debug_only", True), ("fingerprint", "0" * 64),
    ("completed_chunks", True),
])
def test_incomplete_marker_refuses_preparation(tmp_path, field, value):
    path = tmp_path / "completion.json"
    marker = complete_marker(path)
    marker[field] = value
    path.write_text(json.dumps(marker), encoding="utf-8")
    with pytest.raises(ValueError, match="not verified complete"):
        setup.verify_completion(path, FINGERPRINT)


def test_live_collector_or_another_collector_refuses(tmp_path):
    process = tmp_path / "123"
    process.mkdir()
    (process / "status").write_text("State:\tS (sleeping)\n")
    (process / "cmdline").write_bytes(b"python\0profile_full.py\0--run\0")
    with pytest.raises(ValueError, match="still live"):
        setup.verify_collector_exited(123, tmp_path)
    with pytest.raises(ValueError, match="profile_full.py"):
        setup.verify_collector_exited(456, tmp_path)


def test_gpu_compute_job_refuses():
    with mock.patch.object(setup.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, stdout="1234\n")):
        with pytest.raises(ValueError, match="GPU compute processes"):
            setup.verify_gpu_free()


def test_create_without_completion_inputs_refuses_before_any_action(tmp_path):
    args = argparse.Namespace(collector_env=tmp_path / "collector", env_dir=tmp_path / "own",
                              completion=None, collector_pid=None, expected_fingerprint=None)
    with mock.patch.object(setup.sys, "platform", "linux"), \
            mock.patch.object(setup.subprocess, "run", side_effect=AssertionError("must not execute")):
        with pytest.raises(ValueError, match="--create requires"):
            setup.prepare_environment(args)
    assert not (tmp_path / "own").exists()


def test_prepare_only_owns_new_env_offline_and_never_trains(tmp_path):
    collector, own = tmp_path / "collector", tmp_path / "own"
    collector.mkdir()
    version = f"{sys.version_info.major}.{sys.version_info.minor}"
    (collector / "pyvenv.cfg").write_text(f"version = {version}.0\n")
    collector_site = collector / "lib" / f"python{version}" / "site-packages"
    collector_site.mkdir(parents=True)
    marker_path = tmp_path / "completion.json"
    complete_marker(marker_path)
    vendor = tmp_path / "vendor/wheels"
    vendor.mkdir(parents=True)
    (vendor / "shapely-2.0.7-placeholder.whl").write_bytes(b"test-only")
    (tmp_path / "check_environment.py").write_text("# test-only\n")
    before = {str(path.relative_to(collector)): path.read_bytes()
              for path in collector.rglob("*") if path.is_file()}
    commands = []

    def fake_run(command, **kwargs):
        commands.append((command, kwargs))
        if command[1:3] == ["-m", "venv"]:
            (own / "lib" / f"python{version}" / "site-packages").mkdir(parents=True)
            (own / "bin").mkdir()
        return subprocess.CompletedProcess(command, 0)

    args = argparse.Namespace(collector_env=collector, env_dir=own, completion=marker_path,
                              collector_pid=123, expected_fingerprint=FINGERPRINT)
    with mock.patch.object(setup, "BUNDLE", tmp_path), mock.patch.object(setup.sys, "platform", "linux"), \
            mock.patch.object(setup, "verify_collector_exited") as exited, \
            mock.patch.object(setup, "verify_gpu_free") as gpu, \
            mock.patch.object(setup.subprocess, "run", side_effect=fake_run):
        result = setup.prepare_environment(args)
    exited.assert_called_once_with(123)
    gpu.assert_called_once_with()
    assert result["status"] == "prepared_only"
    assert result["training_started"] is False and result["queue_created"] is False
    assert len(commands) == 3
    pip, check = commands[1][0], commands[2][0]
    assert pip[0] == str(own / "bin/python")
    assert "--no-index" in pip and "--no-deps" in pip and "--ignore-installed" in pip
    assert pip[-1] == "shapely==2.0.7"
    assert check == [str(own / "bin/python"), str(tmp_path / "check_environment.py")]
    assert all("train_layout" not in " ".join(command) for command, _ in commands)
    assert all(options["env"]["PYTHONDONTWRITEBYTECODE"] == "1" for _, options in commands)
    assert all(options["env"]["CUDA_VISIBLE_DEVICES"] == "" for _, options in commands)
    pth = own / "lib" / f"python{version}" / "site-packages/roomwise_collector_readonly.pth"
    assert pth.read_text().strip() == str(collector_site.resolve())
    after = {str(path.relative_to(collector)): path.read_bytes()
             for path in collector.rglob("*") if path.is_file()}
    assert before == after

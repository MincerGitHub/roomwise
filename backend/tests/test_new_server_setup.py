"""New-host preparation checks; no real installation, SSH or GPU work."""
import importlib.util
import json
from pathlib import Path
import subprocess
from unittest import mock

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/prepare_new_server.py"
SPEC = importlib.util.spec_from_file_location("new_server_setup", SCRIPT)
setup = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(setup)


def test_default_plan_does_not_create_files_or_execute(tmp_path, capsys):
    with mock.patch.object(setup.subprocess, "run", side_effect=AssertionError("must not execute")):
        assert setup.main(["--env-dir", str(tmp_path / "new-env"), "--device", "cuda"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "plan_only"
    assert not any(result[name] for name in
                   ("environment_created", "training_started", "queue_created", "web_service_started"))
    assert not list(tmp_path.iterdir())
    assert result["commands"][2][-3:] == ["--index-url", setup.TORCH_INDEX["cuda"], "torch==2.4.1"]


def test_existing_directory_is_never_reused_even_when_empty(tmp_path):
    target = tmp_path / "existing"
    target.mkdir()
    with pytest.raises(ValueError, match="already exists"):
        setup.environment_path(target)
    assert not list(target.iterdir())


def test_relative_environment_path_refused():
    with pytest.raises(ValueError, match="absolute"):
        setup.environment_path(Path("relative-env"))


def test_research_inputs_and_active_python_cannot_overlap(tmp_path):
    bundle = tmp_path / "bundle"
    with mock.patch.object(setup, "BUNDLE", bundle), mock.patch.object(setup, "APP", bundle / "app"), \
            mock.patch.object(setup.sys, "prefix", str(tmp_path / "active-env")):
        for path in (bundle / "data/env", bundle / "baseline/env", bundle / "app/env",
                     bundle, tmp_path / "active-env/nested"):
            with pytest.raises(ValueError, match="overlap"):
                setup.environment_path(path)
        assert setup.environment_path(bundle / ".roomwise-venv") == bundle / ".roomwise-venv"


def test_system_directory_refused():
    # Windows path parsing differs, so this assertion is Linux-specific.
    if setup.os.name == "nt":
        pytest.skip("POSIX path handling")
    with pytest.raises(ValueError, match="system"):
        setup.environment_path(Path("/usr/roomwise-new-env"))


@pytest.mark.parametrize("version", [(3, 9), (3, 13)])
def test_unsupported_python_refused_before_modification(tmp_path, version):
    with mock.patch.object(setup.sys, "platform", "linux"), \
            mock.patch.object(setup.sys, "version_info", version), \
            mock.patch.object(setup.subprocess, "run", side_effect=AssertionError("must not execute")):
        with pytest.raises(ValueError, match="Python 3.10, 3.11 or 3.12"):
            setup.create_environment(tmp_path / "new-env", "cpu")
    assert not list(tmp_path.iterdir())


def test_create_only_installs_own_environment_and_checks_dependencies(tmp_path):
    target = tmp_path / "new-env"
    commands = []

    def record(command, **options):
        commands.append((command, options))
        return subprocess.CompletedProcess(command, 0)

    original_env = dict(setup.os.environ)
    with mock.patch.object(setup, "BUNDLE", tmp_path / "bundle"), \
            mock.patch.object(setup, "verify_platform"), mock.patch.object(setup, "verify_disk"), \
            mock.patch.object(setup.subprocess, "run", side_effect=record):
        result = setup.create_environment(target, "cpu")
    assert result["status"] == "prepared_only"
    assert not result["training_started"] and not result["queue_created"]
    assert target.is_dir()
    assert len(commands) == 4
    assert commands[0][0][1:3] == ["-m", "venv"]
    assert all(command[0] == str(target / "bin/python") for command, _ in commands[1:])
    assert all("--isolated" in command and "--no-cache-dir" in command for command, _ in commands[1:3])
    assert all(options["env"]["CUDA_VISIBLE_DEVICES"] == "" for _, options in commands)
    assert setup.os.environ == original_env
    assert not any("train_layout" in " ".join(command) for command, _ in commands)


@pytest.mark.parametrize("output,reason", [
    ("Tesla T4, 520.61.05, 15360\n", "requires Linux driver"),
    ("", "No NVIDIA GPU"),
    ("Tesla T4, unknown, 15360\n", "parse GPU driver"),
])
def test_cuda_preflight_refuses_invalid_driver(output, reason):
    response = subprocess.CompletedProcess([], 0, stdout=output)
    with mock.patch.object(setup.subprocess, "run", return_value=response):
        with pytest.raises(ValueError, match=reason):
            setup.verify_cuda_driver({})


def test_busy_gpu_refuses_before_environment_creation(tmp_path):
    responses = [subprocess.CompletedProcess([], 0, stdout="Tesla T4, 580.126.20, 15360\n"),
                 subprocess.CompletedProcess([], 0, stdout="1234\n")]
    with mock.patch.object(setup, "verify_platform"), mock.patch.object(setup, "verify_disk"), \
            mock.patch.object(setup.subprocess, "run", side_effect=responses):
        with pytest.raises(ValueError, match="compute processes"):
            setup.create_environment(tmp_path / "new-env", "cuda")
    assert not list(tmp_path.iterdir())


def test_free_gpu_driver_details_are_read_only():
    responses = [subprocess.CompletedProcess([], 0, stdout="Tesla T4, 580.126.20, 15360\n"),
                 subprocess.CompletedProcess([], 0, stdout="")]
    with mock.patch.object(setup.subprocess, "run", side_effect=responses) as run:
        assert setup.verify_cuda_driver({}) == [{"name": "Tesla T4", "driver": "580.126.20", "memory_mib": 15360}]
    assert all(call.args[0][0] == "nvidia-smi" and "--query-" in call.args[0][1]
               for call in run.call_args_list)


def test_not_enough_disk_refuses_before_creation(tmp_path):
    usage = mock.Mock(free=setup.MIN_FREE_BYTES - 1)
    with mock.patch.object(setup, "verify_platform"), mock.patch.object(setup.shutil, "disk_usage", return_value=usage), \
            mock.patch.object(setup.subprocess, "run", side_effect=AssertionError("must not execute")):
        with pytest.raises(ValueError, match="10 GiB"):
            setup.create_environment(tmp_path / "new-env", "cpu")
    assert not list(tmp_path.iterdir())


def test_script_has_no_old_host_or_collection_dependency():
    source = SCRIPT.read_text(encoding="utf-8")
    assert "profile_full" not in source
    assert "collector" not in source
    assert "completion" not in source
    assert "system-site-packages" not in source
    assert ".pth" not in source

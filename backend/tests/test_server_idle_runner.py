"""Safety-contract tests; optional real-process checks run only on Linux.

ROOMWISE_LINUX_PROCESS_TESTS=1 python backend/tests/test_server_idle_runner.py
never touches an existing collector. Integration collectors are temporary
sleeping Python processes whose script name is profile_full.py.
"""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import signal
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/server_idle_runner.py"
spec = importlib.util.spec_from_file_location("roomwise_idle_runner_test_module", SCRIPT)
runner = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = runner
spec.loader.exec_module(runner)


def collector(**overrides):
    values = dict(pid=348810, state="S", pgrp=348800, ticks=123,
                  starttime=1000, rss=1024, argv=("python", "-u", "profile_full.py", "--run"))
    values.update(overrides)
    return runner.Process(**values)


class GuardContractTests(unittest.TestCase):
    def test_default_is_observation_without_run(self):
        args = runner.parser().parse_args(["--collector-pid", "348810", "--status", "s.json", "--task-log", "t.log"])
        self.assertFalse(args.run)
        self.assertEqual(args.baseline_seconds, 30)
        self.assertEqual(args.min_available_gib, 8)
        self.assertEqual(args.max_task_rss_gib, 4)
        self.assertEqual(args.command, [])

    def test_collector_must_be_actual_script_argument(self):
        with patch.object(runner, "read_process", return_value=collector()):
            self.assertEqual(runner.validate_collector(348810).pid, 348810)
        for argv in [("python", "-c", "print('profile_full.py')"),
                     ("python", "other.py", "profile_full.py"),
                     ("bash", "profile_full.py")]:
            with patch.object(runner, "read_process", return_value=collector(argv=argv)):
                with self.assertRaises(ValueError):
                    runner.validate_collector(348810)

    def test_stopped_collector_rejected_and_pid_reuse_detected(self):
        with patch.object(runner, "read_process", return_value=collector(state="T")):
            with self.assertRaises(ValueError):
                runner.validate_collector(348810)
        with patch.object(runner, "read_process", return_value=collector(starttime=2000)):
            self.assertFalse(runner.collector_still_running(collector()))
        with patch.object(runner, "read_process", side_effect=FileNotFoundError):
            self.assertFalse(runner.collector_still_running(collector()))

    def test_process_stat_parses_command_parentheses(self):
        with tempfile.TemporaryDirectory() as folder:
            proc = Path(folder); task = proc / "321"; task.mkdir()
            fields = ["0"] * 22
            fields[0] = "S"; fields[2] = "319"
            fields[11] = "17"; fields[12] = "4"
            fields[19] = "9021"; fields[21] = "5"
            (task / "stat").write_text("321 (test (name)) " + " ".join(fields))
            (task / "cmdline").write_bytes(b"python\0profile_full.py\0")
            with patch.object(runner.os, "sysconf", return_value=4096, create=True):
                process = runner.read_process(321, proc)
            self.assertEqual((process.pgrp, process.ticks, process.starttime, process.rss),
                             (319, 21, 9021, 20480))

    def test_command_whitelist_and_absolute_paths(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            scripts = root / "scripts"; scripts.mkdir()
            interpreter = root / "python3"; interpreter.write_text("")
            allowed = scripts / "train_layout.py"; allowed.write_text("")
            command = [str(interpreter), str(allowed), "--threads", "1"]
            self.assertEqual(runner.validate_command(command, scripts), command)
            for rejected in [["python", str(allowed)], [str(interpreter), "train_layout.py"],
                             [str(interpreter), "-c", "print(1)"]]:
                with self.assertRaises(ValueError):
                    runner.validate_command(rejected, scripts)
            other = root / "train_layout.py"; other.write_text("")
            with self.assertRaises(ValueError):
                runner.validate_command([str(interpreter), str(other)], scripts)

    def test_cpu_environment_does_not_change_collector_environment(self):
        with patch.dict(os.environ, {"CUDA_VISIBLE_DEVICES": "0", "OMP_NUM_THREADS": "32"}):
            child_env = runner.cpu_environment()
            self.assertEqual(child_env["CUDA_VISIBLE_DEVICES"], "")
            self.assertEqual(child_env["OMP_NUM_THREADS"], "1")
            self.assertEqual(os.environ["CUDA_VISIBLE_DEVICES"], "0")
            self.assertEqual(os.environ["OMP_NUM_THREADS"], "32")

    def test_pressure_controls_use_reserves_and_collector_demand(self):
        limits = runner.Limits(max_load=11, collector_cpu_baseline=.2)
        good = dict(load=1, available=60 * runner.GIB, own_rss=runner.GIB, collector_cpu=.3)
        self.assertEqual(runner.pressure_reasons(limits, **good), [])
        for key, value in [("load", 12), ("available", 7 * runner.GIB),
                           ("own_rss", 5 * runner.GIB), ("collector_cpu", 1.3)]:
            changed = dict(good); changed[key] = value
            self.assertEqual(len(runner.pressure_reasons(limits, **changed)), 1)

    def test_log_mtime_reports_activity_without_inventing_throughput(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "collector.log"
            observer = runner.ProgressObserver(path)
            self.assertIsNone(observer.observe(0))
            path.write_text("collecting")
            self.assertIsNone(observer.observe(1))
            path.write_text("collecting\nnext message")
            self.assertEqual(observer.observe(2), 0)
            self.assertEqual(observer.observe(100), 98)
            self.assertFalse(hasattr(observer, "stale_after"))

    def test_least_busy_cpu_stays_within_allowed_affinity(self):
        before = {0:(100, 100), 1:(100, 50), 2:(100, 50)}
        after = {0:(200, 200), 1:(200, 50), 2:(200, 130)}
        self.assertEqual(runner.least_busy_cpu(before, after, {1, 2}), 2)

    def test_only_owned_group_is_signalled(self):
        child = Mock(pid=555); child.poll.return_value = None
        with patch.object(runner.os, "getpgid", return_value=555, create=True), \
             patch.object(runner.os, "getpgrp", return_value=700, create=True), \
             patch.object(runner.os, "killpg", create=True) as send:
            task = runner.OwnedTask(child, collector())
            task.send(signal.SIGTERM)
            send.assert_called_once_with(555, signal.SIGTERM)

    def test_collector_group_can_never_be_owned_group(self):
        child = Mock(pid=555)
        with patch.object(runner.os, "getpgid", return_value=555, create=True), \
             patch.object(runner.os, "getpgrp", return_value=700, create=True):
            with self.assertRaises(RuntimeError):
                runner.OwnedTask(child, collector(pgrp=555))

    def test_atomic_status_is_valid_json(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "status.json"
            runner.status_write(path, state="monitoring_only", zero_interference_guaranteed=False)
            self.assertFalse(json.loads(path.read_text())["zero_interference_guaranteed"])
            self.assertFalse(path.with_suffix(".json.tmp").exists())

    @patch.object(runner.signal, "SIGKILL", 9, create=True)
    def test_child_parent_death_signal_is_installed_without_collector_signals(self):
        libc = Mock(); libc.prctl.return_value = 0
        with patch("ctypes.CDLL", return_value=libc), \
             patch.object(runner.os, "getppid", return_value=321), \
             patch.object(runner.os, "getpid", return_value=654), \
             patch.object(runner.os, "kill") as kill:
            runner.child_parent_death_signal(321)
            libc.prctl.assert_called_once_with(1, int(signal.SIGKILL), 0, 0, 0)
            kill.assert_not_called()
        libc.prctl.reset_mock()
        with patch("ctypes.CDLL", return_value=libc), \
             patch.object(runner.os, "getppid", return_value=111), \
             patch.object(runner.os, "getpid", return_value=654), \
             patch.object(runner.os, "kill") as kill:
            runner.child_parent_death_signal(321)
            kill.assert_called_once_with(654, signal.SIGKILL)


@unittest.skipUnless(sys.platform == "linux" and os.environ.get("ROOMWISE_LINUX_PROCESS_TESTS") == "1",
                     "opt-in Linux integration uses only isolated temporary dummy processes")
class LinuxProcessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="roomwise-guard-test-")
        self.root = Path(self.temp.name)
        self.collector_script = self.root / "profile_full.py"
        self.collector_script.write_text("import time\nwhile True: time.sleep(.1)\n")
        self.collector = subprocess.Popen([sys.executable, str(self.collector_script)],
                                         start_new_session=True)
        self.children = []

    def tearDown(self):
        for child in self.children:
            if child.poll() is None:
                child.terminate()
                try:
                    child.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    child.kill(); child.wait()
        if self.collector.poll() is None:
            self.collector.terminate(); self.collector.wait(timeout=5)
        self.temp.cleanup()

    def test_real_owned_group_pause_resume_termination_preserves_collector(self):
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"],
                                 env=runner.cpu_environment(), start_new_session=True)
        self.children.append(child)
        task = runner.OwnedTask(child, runner.validate_collector(self.collector.pid))
        task.pause(); time.sleep(.05)
        self.assertEqual(runner.read_process(child.pid).state, "T")
        self.assertIsNone(self.collector.poll())
        task.resume(); time.sleep(.05)
        self.assertNotEqual(runner.read_process(child.pid).state, "T")
        task.terminate()
        self.assertIsNotNone(child.poll())
        self.assertIsNone(self.collector.poll())

    def test_default_launcher_observes_without_task(self):
        status = self.root / "status.json"
        child = subprocess.Popen([sys.executable, str(SCRIPT), "--collector-pid", str(self.collector.pid),
                                 "--status", str(status), "--task-log", str(self.root / "task.log"),
                                 "--max-seconds", "34", "--poll-seconds", "1"])
        self.children.append(child)
        child.wait(timeout=45)
        result = json.loads(status.read_text())
        self.assertTrue(result["monitor_only"])
        self.assertNotIn("task_pid", result)
        self.assertIsNone(self.collector.poll())

    def test_launcher_cpu_limits_and_collector_exit_cleanup(self):
        if not shutil.which("ionice") or runner.available_memory() < 8 * runner.GIB:
            self.skipTest("idle I/O utility and 8 GiB reserve required for --run integration")
        scripts = self.root / "app/backend/scripts"; scripts.mkdir(parents=True)
        guard = scripts / SCRIPT.name; shutil.copyfile(SCRIPT, guard)
        evidence = self.root / "task-evidence.json"
        task_script = scripts / "train_layout.py"
        task_script.write_text(
            "import json, os, sys, time\n"
            "from pathlib import Path\n"
            "Path(sys.argv[1]).write_text(json.dumps({'pid':os.getpid(),"
            "'cuda':os.environ.get('CUDA_VISIBLE_DEVICES'),"
            "'threads':os.environ.get('OMP_NUM_THREADS'),'nice':os.getpriority(os.PRIO_PROCESS,0),"
            "'affinity':list(os.sched_getaffinity(0))}))\n"
            "while True: time.sleep(.1)\n")
        status = self.root / "run-status.json"
        child = subprocess.Popen([sys.executable, str(guard), "--collector-pid", str(self.collector.pid),
            "--status", str(status), "--task-log", str(self.root / "run.log"), "--run",
            "--max-seconds", "50", "--resume-seconds", "1", "--poll-seconds", "1",
            "--max-load", "100000", "--", sys.executable, str(task_script), str(evidence)])
        self.children.append(child)
        deadline = time.monotonic() + 42
        while not evidence.exists() and child.poll() is None and time.monotonic() < deadline:
            time.sleep(.1)
        self.assertTrue(evidence.exists(), status.read_text() if status.exists() else "launcher did not start")
        facts = json.loads(evidence.read_text())
        self.assertEqual(facts["cuda"], "")
        self.assertEqual(facts["threads"], "1")
        self.assertEqual(facts["nice"], 19)
        self.assertEqual(len(facts["affinity"]), 1)
        self.assertIsNone(self.collector.poll())
        self.collector.terminate(); self.collector.wait(timeout=5)
        child.wait(timeout=10)
        self.assertEqual(json.loads(status.read_text())["state"], "stopped")
        try:
            remains = runner.read_process(facts["pid"])
            self.assertIn(remains.state, {"Z", "X"})
        except FileNotFoundError:
            pass


if __name__ == "__main__":
    unittest.main()

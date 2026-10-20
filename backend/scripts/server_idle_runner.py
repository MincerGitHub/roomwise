"""Run one CPU-only experiment at low priority while observing a collector.

Linux only; no third-party imports, package installation, or collector signals.
This reduces interference; shared CPU, RAM and storage cannot promise zero
change in collection throughput. CUDA_VISIBLE_DEVICES only constrains the
trusted experiment; it is not a security sandbox against arbitrary code.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
import shutil
import signal
import statistics
import subprocess
import sys
import time

SCRIPTS = Path(__file__).resolve().parent
ALLOWED_SCRIPTS = {"prepare_data.py", "train_layout.py", "evaluate_layout.py",
                   "evaluate_application.py", "run_idle_experiments.py"}
GIB = 1024 ** 3


@dataclass(frozen=True)
class Process:
    pid: int
    state: str
    pgrp: int
    ticks: int
    starttime: int
    rss: int
    argv: tuple[str, ...]


def read_process(pid: int, proc: Path = Path("/proc")) -> Process:
    directory = proc / str(pid)
    raw = (directory / "stat").read_text()
    # comm may contain spaces and parentheses. Fields below start at field 3.
    tail = raw[raw.rfind(")") + 2:].split()
    argv = tuple(x.decode(errors="replace") for x in
                 (directory / "cmdline").read_bytes().split(b"\0") if x)
    return Process(pid, tail[0], int(tail[2]), int(tail[11]) + int(tail[12]),
                   int(tail[19]), int(tail[21]) * os.sysconf("SC_PAGE_SIZE"), argv)


def validate_collector(pid: int, proc: Path = Path("/proc")) -> Process:
    if pid <= 1 or pid == os.getpid():
        raise ValueError("collector PID must name the existing profile_full.py process")
    collector = read_process(pid, proc)
    # Require an actual script argument rather than text in '-c' or a shell.
    python_flags = {"-u", "-B", "-E", "-s", "-S", "-I", "-O", "-OO"}
    arguments = list(collector.argv[1:])
    while arguments and arguments[0] in python_flags:
        arguments.pop(0)
    if (not collector.argv or not Path(collector.argv[0]).name.startswith("python")
            or not arguments or Path(arguments[0]).name != "profile_full.py"):
        raise ValueError("collector command must contain a profile_full.py script argument")
    if collector.state in {"Z", "X", "T", "t"}:
        raise ValueError("collector is exited or stopped; do not start an experiment")
    return collector


def collector_still_running(expected: Process, proc: Path = Path("/proc")) -> bool:
    try:
        current = read_process(expected.pid, proc)
        return current.starttime == expected.starttime and current.state not in {"Z", "X", "T", "t"}
    except (OSError, ValueError, IndexError):
        return False


def validate_command(command: list[str], scripts: Path = SCRIPTS) -> list[str]:
    if len(command) < 2:
        raise ValueError("use -- /absolute/venv/bin/python /absolute/scripts/allowed_script.py [args]")
    interpreter = Path(command[0])
    script = Path(command[1])
    if not interpreter.is_absolute() or not interpreter.is_file():
        raise ValueError("Python interpreter must be an existing absolute file path")
    if not interpreter.name.startswith("python"):
        raise ValueError("only a Python interpreter is supported")
    if not script.is_absolute() or not script.is_file():
        raise ValueError("experiment script must be an existing absolute file path")
    script = script.resolve()
    if script.parent != scripts.resolve() or script.name not in ALLOWED_SCRIPTS:
        raise ValueError("experiment script is outside the local project whitelist")
    return [str(interpreter), str(script), *command[2:]]


def cpu_environment() -> dict[str, str]:
    env = os.environ.copy()
    env.update(CUDA_VISIBLE_DEVICES="", OMP_NUM_THREADS="1", MKL_NUM_THREADS="1",
               OPENBLAS_NUM_THREADS="1", NUMEXPR_NUM_THREADS="1", VECLIB_MAXIMUM_THREADS="1",
               PYTHONUNBUFFERED="1")
    return env


def child_parent_death_signal(expected_parent: int):
    """Linux preexec hook: kill this task if its launcher abruptly disappears.

    An experiment which creates its own children must set the same hook there;
    PDEATHSIG does not automatically cover grandchildren.
    """
    import ctypes
    libc = ctypes.CDLL(None, use_errno=True)
    libc.prctl.argtypes = [ctypes.c_int, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong]
    libc.prctl.restype = ctypes.c_int
    if libc.prctl(1, int(signal.SIGKILL), 0, 0, 0) != 0:  # PR_SET_PDEATHSIG
        raise OSError(ctypes.get_errno(), "could not set experiment parent-death signal")
    if os.getppid() != expected_parent:
        os.kill(os.getpid(), signal.SIGKILL)


def available_memory(proc: Path = Path("/proc")) -> int:
    for line in (proc / "meminfo").read_text().splitlines():
        if line.startswith("MemAvailable:"):
            return int(line.split()[1]) * 1024
    raise RuntimeError("MemAvailable was not reported; cannot establish a safe memory margin")


def cpu_counters(proc: Path = Path("/proc")) -> dict[int, tuple[int, int]]:
    output = {}
    for line in (proc / "stat").read_text().splitlines():
        fields = line.split()
        if fields and fields[0].startswith("cpu") and fields[0][3:].isdigit():
            values = [int(x) for x in fields[1:]]
            # guest/guest_nice are already included in user/nice.
            output[int(fields[0][3:])] = (sum(values[:8]), values[3] + values[4])
    return output


def least_busy_cpu(before: dict, after: dict, allowed: set[int]) -> int:
    def busy(cpu):
        a, b = before.get(cpu), after.get(cpu)
        if not a or not b or b[0] <= a[0]:
            return 1.0
        return 1 - (b[1] - a[1]) / (b[0] - a[0])
    return min(allowed, key=lambda cpu: (busy(cpu), cpu))


@dataclass
class Limits:
    max_load: float
    min_available: int = 8 * GIB
    max_own_rss: int = 4 * GIB
    collector_cpu_baseline: float = 0.0  # cores, not percent
    max_collector_cpu_increase: float = 1.0


def pressure_reasons(limits: Limits, *, load: float, available: int,
                     own_rss: int, collector_cpu: float) -> list[str]:
    reasons = []
    if load > limits.max_load:
        reasons.append("system load above limit")
    if available < limits.min_available:
        reasons.append("available RAM below reserve")
    if own_rss > limits.max_own_rss:
        reasons.append("experiment RSS above limit")
    if collector_cpu > limits.collector_cpu_baseline + limits.max_collector_cpu_increase:
        reasons.append("collector CPU demand increased")
    return reasons


class ProgressObserver:
    """Report log activity only. mtime is never treated as throughput."""
    def __init__(self, path: Path | None):
        self.path = path
        self.signature = None
        self.last_update = None

    def observe(self, now: float) -> float | None:
        if self.path is None:
            return None
        try:
            info = self.path.stat()
            signature = (info.st_mtime_ns, info.st_size)
        except OSError:
            return None  # Missing/silent logs do not prove collector slowdown.
        if self.signature is not None and signature != self.signature:
            self.last_update = now
        self.signature = signature
        return None if self.last_update is None else now - self.last_update


def own_group_rss(pgrp: int, proc: Path = Path("/proc")) -> int:
    total = 0
    for entry in proc.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            process = read_process(int(entry.name), proc)
            if process.pgrp == pgrp:
                total += process.rss
        except (OSError, ValueError, IndexError):
            pass
    return total


class OwnedTask:
    def __init__(self, child: subprocess.Popen, collector: Process):
        self.child, self.collector = child, collector
        self.pgrp = os.getpgid(child.pid)
        if self.pgrp != child.pid or self.pgrp == collector.pgrp or self.pgrp == os.getpgrp():
            raise RuntimeError("experiment must have its own separate process group")
        self.paused = False

    def send(self, sig: int):
        # Only the process group created by start_new_session is signalled.
        try:
            os.killpg(self.pgrp, sig)
        except ProcessLookupError:
            pass

    def pause(self):
        if not self.paused:
            self.send(signal.SIGSTOP)
            self.paused = True

    def resume(self):
        if self.paused:
            self.send(signal.SIGCONT)
            self.paused = False

    def terminate(self):
        # SIGTERM pending on stopped processes needs SIGCONT to be handled.
        self.send(signal.SIGTERM)
        self.resume()
        try:
            self.child.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.send(signal.SIGKILL)
            self.child.wait(timeout=5)
        # A failed experiment leader must not leave a training grandchild.
        self.send(signal.SIGKILL)


def status_write(path: Path, **values):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(values, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--collector-pid", type=int, required=True)
    p.add_argument("--progress-log", type=Path, help="optional collector log; read-only")
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--run", action="store_true", help="explicitly run the CPU experiment; shared-resource impact is possible")
    mode.add_argument("--dry-run", "--monitor-only", action="store_true", help="observe only (the default)")
    p.add_argument("--status", type=Path, required=True, help="new status JSON outside collector directory")
    p.add_argument("--task-log", type=Path, required=True, help="new experiment stdout/stderr file")
    p.add_argument("--baseline-seconds", type=float, default=30)
    p.add_argument("--max-seconds", type=float, default=1800, help="wall time including pauses/baseline")
    p.add_argument("--poll-seconds", type=float, default=2)
    p.add_argument("--resume-seconds", type=float, default=20)
    p.add_argument("--max-pause-seconds", type=float, default=300)
    p.add_argument("--max-load", type=float, help="default: 35%% of available logical CPUs")
    p.add_argument("--min-available-gib", type=float, default=8)
    p.add_argument("--max-task-rss-gib", type=float, default=4)
    p.add_argument("command", nargs=argparse.REMAINDER)
    return p


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if sys.platform != "linux":
        raise SystemExit("This launcher requires Linux /proc, affinity and Unix process groups.")
    supplied = args.command[1:] if args.command[:1] == ["--"] else args.command
    command = validate_command(supplied) if supplied else None
    if args.run and command is None:
        raise SystemExit("--run requires an explicit whitelisted experiment command")
    collector = validate_collector(args.collector_pid)
    positive = [args.baseline_seconds, args.max_seconds, args.poll_seconds,
                args.resume_seconds, args.max_pause_seconds, args.min_available_gib, args.max_task_rss_gib]
    if any(not math.isfinite(value) or value <= 0 for value in positive):
        raise SystemExit("all timing/memory settings must be finite and positive")
    if args.min_available_gib < 8 or args.max_task_rss_gib > 4:
        raise SystemExit("keep at least 8 GiB available and limit task RSS to at most 4 GiB")
    if args.baseline_seconds < 30 or args.poll_seconds < 1:
        raise SystemExit("baseline must be >=30 seconds and monitoring interval >=1 second")
    allowed = set(os.sched_getaffinity(0))
    max_load = args.max_load if args.max_load is not None else max(0.5, len(allowed) * .35)
    if not math.isfinite(max_load) or max_load <= 0:
        raise SystemExit("max-load must be finite and positive")
    limits = Limits(max_load, int(args.min_available_gib * GIB), int(args.max_task_rss_gib * GIB))
    log_path, status_path = args.task_log.resolve(), args.status.resolve()
    if log_path == status_path or (args.progress_log and
            args.progress_log.resolve() in {log_path, status_path}):
        raise SystemExit("experiment log/status must differ from the collector log")
    if log_path.exists() or status_path.exists():
        raise SystemExit("use new status/task-log paths; existing files are never overwritten")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    os.setpriority(os.PRIO_PROCESS, 0, 19)
    ionice = shutil.which("ionice")
    io_idle = False
    if ionice:
        result = subprocess.run([ionice, "-c", "3", "-p", str(os.getpid())], check=False,
                                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        io_idle = result.returncode == 0
    if args.run and not io_idle:
        raise SystemExit("ionice idle priority could not be set; stay in monitor-only mode")
    # Set low priority before baseline; affinity is fixed after choosing a core.
    begin = time.monotonic()
    before_cpu = cpu_counters()
    previous, previous_at = collector, begin
    observed_cpu = []
    progress = ProgressObserver(args.progress_log)
    task = None
    clock_ticks = os.sysconf("SC_CLK_TCK")
    state = {"collector_pid": collector.pid, "collector_starttime": collector.starttime,
             "runner_pid": os.getpid(), "command": command, "cpu_only": True,
             "nice": 19, "io_idle": io_idle, "zero_interference_guaranteed": False,
             "monitor_only": not args.run, "throughput_monitor_available": False,
             "warning": "CPU/RAM/disk are shared; collector throughput is not measured. No zero-impact guarantee."}
    status_write(status_path, **state, state="observing_baseline")
    shutdown = False
    def interrupted(_signum, _frame):
        nonlocal shutdown
        shutdown = True
    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)
    signal.signal(signal.SIGHUP, interrupted)
    try:
        while time.monotonic() - begin < args.baseline_seconds:
            if shutdown or not collector_still_running(collector):
                status_write(status_path, **state, state="not_started", reason="collector stopped or runner interrupted")
                return 2
            if time.monotonic() - begin >= args.max_seconds:
                status_write(status_path, **state, state="not_started", reason="wall-time limit during baseline")
                return 2
            time.sleep(args.poll_seconds)
            now, current = time.monotonic(), read_process(collector.pid)
            observed_cpu.append((current.ticks - previous.ticks) / clock_ticks / (now - previous_at))
            previous, previous_at = current, now
            progress.observe(now)
        limits.collector_cpu_baseline = statistics.median(observed_cpu)
        core = least_busy_cpu(before_cpu, cpu_counters(), allowed)
        os.sched_setaffinity(0, {core})
        state.update(cpu_core=core, collector_cpu_baseline=limits.collector_cpu_baseline,
                     baseline_seconds=args.baseline_seconds)
        idle_since = None
        pause_since = None
        with log_path.open("x", encoding="utf-8") as task_log:
            while not shutdown and time.monotonic() - begin < args.max_seconds:
                now = time.monotonic()
                if not collector_still_running(collector):
                    state["reason"] = "collector stopped, exited, or PID was reused"
                    break
                current = read_process(collector.pid)
                demand = (current.ticks - previous.ticks) / clock_ticks / max(.001, now - previous_at)
                previous, previous_at = current, now
                load, available = os.getloadavg()[0], available_memory()
                rss = own_group_rss(task.pgrp) if task else 0
                reasons = pressure_reasons(limits, load=load, available=available, own_rss=rss,
                                          collector_cpu=demand)
                progress_age = progress.observe(now)
                if reasons:
                    idle_since = None
                    if pause_since is None:
                        pause_since = now
                    if task:
                        task.pause()
                    current_state = "paused" if task else "waiting_for_idle"
                    if now - pause_since >= args.max_pause_seconds:
                        state["reason"] = "resource pressure persisted beyond pause limit"
                        break
                else:
                    idle_since = now if idle_since is None else idle_since
                    current_state = "paused" if task and task.paused else "waiting_for_idle"
                    if args.run and now - idle_since >= args.resume_seconds:
                        pause_since = None
                        if task is None:
                            # CPU affinity, nice and I/O priority are inherited.
                            parent_pid = os.getpid()
                            child = subprocess.Popen(command, cwd=SCRIPTS.parents[1],
                                env=cpu_environment(), stdin=subprocess.DEVNULL,
                                stdout=task_log, stderr=subprocess.STDOUT, start_new_session=True,
                                preexec_fn=lambda: child_parent_death_signal(parent_pid))
                            task = OwnedTask(child, collector)
                            state.update(task_pid=child.pid, task_process_group=task.pgrp)
                        task.resume()
                        current_state = "running"
                if not args.run:
                    current_state = "monitoring_only"
                status_write(status_path, **state, state=current_state, elapsed_seconds=round(now-begin, 2),
                             pressure_reasons=reasons, load1=load, available_ram_bytes=available,
                             task_rss_bytes=rss, collector_cpu_cores=demand,
                             progress_log_last_observed_update_age_seconds=progress_age)
                if task and task.child.poll() is not None:
                    exit_code = task.child.returncode
                    status_write(status_path, **state, state="finished", task_exit_code=exit_code,
                                 elapsed_seconds=round(time.monotonic()-begin, 2))
                    return exit_code
                time.sleep(args.poll_seconds)
        state.setdefault("reason", "runner interrupted" if shutdown else "wall-time limit")
        observed = not args.run and not shutdown and state["reason"] == "wall-time limit"
        status_write(status_path, **state, state="observed" if observed else "stopped",
                     elapsed_seconds=round(time.monotonic()-begin, 2))
        return 0 if observed else 2
    finally:
        if task:
            task.terminate()


if __name__ == "__main__":
    raise SystemExit(main())

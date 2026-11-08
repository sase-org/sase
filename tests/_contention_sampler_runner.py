"""Bounded resource and signal sampler for the contention soak.

Diagnostic only. `tools/run_pytest contention` starts this as
``python -m tests._contention_sampler`` beside its pytest repeats and stops it
by closing its stdin. Every interval it appends one JSON sample and prints one
flushed log line: the soak's process tree (RSS, PSS, swap, threads), host and
cgroup memory, pressure stall information, OOM counters, filesystem headroom
for the scratch root, ``/tmp``, and the workspace, and the repeat's live
progress from `tests._contention_progress`.

Lines go to the job log as well as ``samples.jsonl``, because a runner that is
being torn down may never run the step that uploads the file.

The sampler stays in the soak's process group and blocks SIGTERM, SIGINT, and
SIGHUP, consuming them with ``sigtimedwait``. A signal broad enough to reach the
whole soak therefore reaches it too, and it can record what nothing else here
can: the sending PID and that sender's ancestry, matched to the worker and test
that were running. It keeps sampling until the soak parent exits.

It moves itself off the soak's pinned CPUs so the starvation it measures is
neither worsened by it nor delaying it. It never signals another process; the
harness owns its lifetime.
"""

from __future__ import annotations

import argparse
import os
import select
import signal
import subprocess
import sys
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

from tests._contention_procfs import ProcFS
from tests._contention_sampler_common import (
    CAPTURED_SIGNALS,
    DEFAULT_INTERVAL_SECONDS,
    LOG_PREFIX,
    POLL_SECONDS,
    SAMPLER_REAP_TIMEOUT_SECONDS,
    SAMPLER_STOP_TIMEOUT_SECONDS,
)
from tests._contention_sampler_sampler import Sampler


def _stop_reason(root_pid: int, control: TextIO) -> str | None:
    if os.getppid() != root_pid:
        return "soak parent exited"
    try:
        readable, _, _ = select.select([control], [], [], 0)
        if readable and not os.read(control.fileno(), 64):
            return "stopped by the harness"
    except (OSError, ValueError, AttributeError):
        pass
    return None


def _move_off_pinned_cpus() -> None:
    try:
        os.sched_setaffinity(0, range(os.cpu_count() or 1))
    except OSError:
        pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root-pid", type=int, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--interval", type=float, default=DEFAULT_INTERVAL_SECONDS)
    parser.add_argument("--path", action="append", default=[], metavar="LABEL=PATH")
    parser.add_argument("--proc-root", type=Path, default=Path("/proc"))
    parser.add_argument("--cgroup-root", type=Path, default=Path("/sys/fs/cgroup"))
    args = parser.parse_args(argv)
    signal.pthread_sigmask(signal.SIG_BLOCK, CAPTURED_SIGNALS)
    procfs = ProcFS(args.proc_root, args.cgroup_root)
    soak_cpus = procfs.cpus_allowed(args.root_pid)
    _move_off_pinned_cpus()
    args.out.mkdir(parents=True, exist_ok=True)
    paths = dict(item.split("=", 1) for item in args.path)
    sampler = Sampler(
        root_pid=args.root_pid,
        out=args.out,
        paths={label: Path(path) for label, path in paths.items()},
        procfs=procfs,
        stream=sys.stdout,
    )
    sampler.header(soak_cpus)
    due = time.monotonic()
    reason: str | None = None
    while reason is None:
        if time.monotonic() >= due:
            try:
                sampler.sample()
            except Exception as error:  # one bad read must not end the record
                sampler.emit(f" sample failed: {type(error).__name__}: {error}")
            due = time.monotonic() + args.interval
        wait = max(0.0, min(POLL_SECONDS, due - time.monotonic()))
        info = signal.sigtimedwait(CAPTURED_SIGNALS, wait)
        if info is not None:
            try:
                sampler.on_signal(info)
            except Exception as error:
                sampler.emit(f" signal record failed: {type(error).__name__}: {error}")
            # Sample at once: the memory and progress picture at the signal.
            due = time.monotonic()
            continue
        reason = _stop_reason(args.root_pid, sys.stdin)
    sampler.finish(reason)
    return 0


@dataclass
class SamplerHandle:
    """The harness's handle on the one sampler it started."""

    process: subprocess.Popen[bytes]

    def stop(self, timeout: float = SAMPLER_STOP_TIMEOUT_SECONDS) -> int | None:
        """Ask the sampler to finish, and reap it. Never raises."""
        try:
            if self.process.stdin is not None:
                self.process.stdin.close()
        except OSError:
            pass
        try:
            return self.process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            # It blocks SIGTERM by design; only this run's own sampler is killed.
            self.process.kill()
            try:
                return self.process.wait(timeout=SAMPLER_REAP_TIMEOUT_SECONDS)
            except subprocess.TimeoutExpired:
                return None


def start_sampler(
    out: Path,
    *,
    root_pid: int,
    paths: Mapping[str, Path],
    interval: float,
    cwd: Path,
) -> SamplerHandle | None:
    """Start the sampler, or warn and return ``None``: the soak runs either way."""
    command = [
        sys.executable,
        "-m",
        "tests._contention_sampler",
        "--root-pid",
        str(root_pid),
        "--out",
        str(out),
        "--interval",
        f"{interval:g}",
    ]
    for label, path in paths.items():
        command.extend(["--path", f"{label}={path}"])
    try:
        out.mkdir(parents=True, exist_ok=True)
        process = subprocess.Popen(command, stdin=subprocess.PIPE, cwd=cwd)
    except Exception as error:
        print(f"{LOG_PREFIX} sampler unavailable: {error}", file=sys.stderr, flush=True)
        return None
    return SamplerHandle(process)

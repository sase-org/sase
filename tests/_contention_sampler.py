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
import json
import os
import platform
import select
import signal
import subprocess
import sys
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TextIO

from tests._contention import (
    CONTROLLER_PROGRESS_FILENAME,
    KILLS_FILENAME,
    PROGRESS_DIRNAME,
    WORKER_PROGRESS_PREFIX,
    read_json,
)
from tests._contention_procfs import (
    ProcFS,
    ProcStat,
    filesystem,
    scan_usage,
    soak_tree,
)


LOG_PREFIX = "[contention-diag]"
SAMPLES_FILENAME = "samples.jsonl"
SIGNALS_FILENAME = "signals.jsonl"
CAPTURED_SIGNALS = (signal.SIGTERM, signal.SIGINT, signal.SIGHUP)
DEFAULT_INTERVAL_SECONDS = 15.0
POLL_SECONDS = 1.0
MAX_SAMPLE_RECORDS = 2000
MAX_SIGNAL_RECORDS = 20
#: The scratch tree is walked on the first sample and every Nth after it.
USAGE_SCAN_EVERY = 8
PRINT_LIMIT = 30
#: How long an exited soak process stays identifiable, so a sender that died
#: right after signalling can still be named from the sample before.
LAST_SEEN_SECONDS = 120.0
LAST_SEEN_LIMIT = 512
BYTE_PEAKS = frozenset(
    {
        "soak_rss",
        "soak_pss",
        "soak_swap",
        "min_mem_available",
        "min_swap_free",
        "cgroup_current",
        "scratch_bytes",
    }
)
SI_CODE_NAMES = {0: "SI_USER", 0x80: "SI_KERNEL", -1: "SI_QUEUE", -6: "SI_TKILL"}
ROLE_NAMES = ("parent", "controller", "worker")


def role(depth: int) -> str:
    return ROLE_NAMES[depth] if depth < len(ROLE_NAMES) else "descendant"


def read_progress(progress_root: Path) -> dict[str, Any] | None:
    """The latest repeat's controller record, worker records, and kill audit."""
    try:
        repeats = sorted(path for path in progress_root.iterdir() if path.is_dir())
    except OSError:
        return None
    if not repeats:
        return None
    current = repeats[-1]
    workers: dict[int, dict[str, Any]] = {}
    for path in current.glob(f"{WORKER_PROGRESS_PREFIX}*.json"):
        record = read_json(path)
        if record is not None and isinstance(record.get("pid"), int):
            workers[record["pid"]] = record
    kills: list[dict[str, Any]] = []
    try:
        lines = (current / KILLS_FILENAME).read_text().splitlines()
    except OSError:
        lines = []
    for line in lines:
        try:
            kills.append(json.loads(line))
        except ValueError:
            continue
    return {
        "repeat": current.name,
        "controller": read_json(current / CONTROLLER_PROGRESS_FILENAME),
        "workers": workers,
        "kill_count": len(kills),
        "kills": kills[-3:],
    }


def _gib(value: object) -> str:
    return f"{value / 2**30:.1f}G" if isinstance(value, int) else "?"


def _peak_text(key: str, value: object) -> str:
    is_bytes = key in BYTE_PEAKS or key.startswith("min_free_")
    return f"{key} {_gib(value) if is_bytes else value}"


def _running(workers: Mapping[int, Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """Workers inside a test, longest-running first."""
    running = [
        record
        for record in workers.values()
        if record.get("nodeid") and record.get("finished_at") is None
    ]
    return sorted(running, key=lambda record: record.get("started_at") or 0.0)


def _age(now: float, started: object) -> str:
    return f"{now - started:.0f}s" if isinstance(started, (int, float)) else "?"


class Sampler:
    """Collects samples and signal records, and renders their log lines."""

    def __init__(
        self,
        *,
        root_pid: int,
        out: Path,
        paths: Mapping[str, Path],
        procfs: ProcFS,
        stream: TextIO,
    ) -> None:
        self.root_pid = root_pid
        self.out = out
        self.paths = dict(paths)
        self.procfs = procfs
        self.stream = stream
        self.started = time.monotonic()
        self.samples = 0
        self.signals = 0
        self.peaks: dict[str, Any] = {}
        self.baseline: dict[str, int] = {}
        self.last_seen: dict[int, dict[str, Any]] = {}

    def _elapsed(self) -> float:
        return round(time.monotonic() - self.started, 1)

    def emit(self, line: str) -> None:
        try:
            self.stream.write(f"{LOG_PREFIX}{line}\n")
            self.stream.flush()
        except (OSError, ValueError):
            pass

    def _append(self, filename: str, record: Mapping[str, Any], limit: int) -> None:
        if limit <= 0:
            return
        try:
            with (self.out / filename).open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, sort_keys=True) + "\n")
        except OSError:
            pass

    def header(self, soak_cpus: str | None) -> dict[str, Any]:
        memory = self.procfs.meminfo()
        cgroup = self.procfs.cgroup() or {}
        record = {
            "kind": "header",
            "at": time.time(),
            "root_pid": self.root_pid,
            "sampler_pid": os.getpid(),
            "python": platform.python_version(),
            "kernel": platform.release(),
            "cpu_count": os.cpu_count(),
            "soak_cpus": soak_cpus,
            "sampler_cpus": self.procfs.cpus_allowed(os.getpid()),
            "memory": memory,
            "cgroup": cgroup,
            "paths": {label: filesystem(path) for label, path in self.paths.items()},
        }
        self._append(SAMPLES_FILENAME, record, MAX_SAMPLE_RECORDS)
        self.emit(
            f" root pid {self.root_pid}, sampler pid {os.getpid()} on cpus "
            f"{record['sampler_cpus']} (soak cpus {soak_cpus}), python "
            f"{record['python']}, {record['cpu_count']} cpus, host mem "
            f"{_gib(memory.get('MemTotal'))} swap {_gib(memory.get('SwapTotal'))}, "
            f"cgroup {cgroup.get('path', '?')} max {cgroup.get('max', '?')}, "
            f"out {self.out}"
        )
        return record

    def _tree(self) -> tuple[dict[int, ProcStat], dict[int, int]]:
        stats = self.procfs.all_stats()
        return stats, soak_tree(stats, self.root_pid, exclude=os.getpid())

    def _peak(self, key: str, value: object, *, lowest: bool = False) -> None:
        if not isinstance(value, (int, float)):
            return
        current = self.peaks.get(key)
        if current is None or (value < current if lowest else value > current):
            self.peaks[key] = value

    def sample(self, reason: str = "interval") -> dict[str, Any]:
        stats, depths = self._tree()
        roles: dict[str, dict[str, int]] = {}
        totals = {"rss": 0, "pss": 0, "swap": 0, "threads": 0, "major_faults": 0}
        top: list[tuple[int, int, str]] = []
        for pid, depth in depths.items():
            stat = stats[pid]
            rollup = self.procfs.rollup(pid)
            totals["rss"] += stat.rss_bytes
            totals["pss"] += rollup.get("Pss", 0)
            totals["swap"] += rollup.get("Swap", 0)
            totals["threads"] += stat.threads
            totals["major_faults"] += stat.major_faults
            group = roles.setdefault(role(depth), {"count": 0, "rss": 0, "pss": 0})
            group["count"] += 1
            group["rss"] += stat.rss_bytes
            group["pss"] += rollup.get("Pss", 0)
            top.append((stat.rss_bytes, pid, role(depth)))
        self._remember(stats, depths)
        memory = self.procfs.meminfo()
        vmstat = self.procfs.vmstat()
        cgroup = self.procfs.cgroup()
        for key, value in vmstat.items():
            self.baseline.setdefault(key, value)
        record: dict[str, Any] = {
            "kind": "sample",
            "reason": reason,
            "at": time.time(),
            "elapsed": self._elapsed(),
            "soak": {"procs": len(depths), **totals, "by_role": roles},
            "top_rss": [
                {"pid": pid, "role": name, "rss": rss}
                for rss, pid, name in sorted(top, reverse=True)[:5]
            ],
            "memory": memory,
            "vmstat": vmstat,
            "cgroup": cgroup,
            "pressure": {
                name: self.procfs.pressure(self.procfs.read("pressure", name))
                for name in ("memory", "io", "cpu")
            },
            "loadavg": self.procfs.loadavg(),
            "filesystems": {
                label: filesystem(path) for label, path in self.paths.items()
            },
            "progress": read_progress(self.out / PROGRESS_DIRNAME),
        }
        if "scratch" in self.paths and self.samples % USAGE_SCAN_EVERY == 0:
            record["scratch_usage"] = scan_usage(self.paths["scratch"])
        self.samples += 1
        self._track_peaks(record)
        record["peaks"] = dict(self.peaks)
        self._append(SAMPLES_FILENAME, record, MAX_SAMPLE_RECORDS - self.samples)
        self.emit(self.format_sample(record))
        return record

    def _remember(
        self, stats: Mapping[int, ProcStat], depths: Mapping[int, int]
    ) -> None:
        """Keep recently seen soak processes identifiable after they exit."""
        elapsed = self._elapsed()
        for pid, depth in depths.items():
            known = self.last_seen.get(pid)
            cmdline = known.get("cmdline") if known else self.procfs.cmdline(pid)
            self.last_seen[pid] = {
                "comm": stats[pid].comm,
                "ppid": stats[pid].ppid,
                "role": role(depth),
                "cmdline": cmdline,
                "seen_at": elapsed,
            }
        stale = [
            pid
            for pid, known in self.last_seen.items()
            if elapsed - known["seen_at"] > LAST_SEEN_SECONDS
        ]
        for pid in stale:
            del self.last_seen[pid]
        while len(self.last_seen) > LAST_SEEN_LIMIT:
            del self.last_seen[next(iter(self.last_seen))]

    def _track_peaks(self, record: Mapping[str, Any]) -> None:
        soak = record["soak"]
        for key in ("procs", "rss", "pss", "swap", "threads"):
            self._peak(f"soak_{key}", soak[key])
        memory = record["memory"]
        self._peak("min_mem_available", memory.get("MemAvailable"), lowest=True)
        self._peak("min_swap_free", memory.get("SwapFree"), lowest=True)
        cgroup = record["cgroup"] or {}
        self._peak("cgroup_current", cgroup.get("current"))
        self._peak("pressure_memory_full", record["pressure"]["memory"].get("full"))
        for label, fs in record["filesystems"].items():
            if fs is not None:
                self._peak(f"min_free_{label}", fs["free_bytes"], lowest=True)
                self._peak(f"min_inodes_{label}", fs["free_inodes"], lowest=True)
        if "scratch_usage" in record:
            self._peak("scratch_bytes", record["scratch_usage"]["bytes"])
        for key, value in record["vmstat"].items():
            self._peak(f"{key}_delta", value - self.baseline[key])

    def format_sample(self, record: Mapping[str, Any]) -> str:
        soak, memory = record["soak"], record["memory"]
        roles = soak["by_role"]
        cgroup = record["cgroup"] or {}
        pressure = record["pressure"]
        parts = [
            f" +{record['elapsed']:.0f}s soak {soak['procs']}p/{soak['threads']}t "
            f"rss {_gib(soak['rss'])} pss {_gib(soak['pss'])} swap "
            f"{_gib(soak['swap'])} majflt {soak['major_faults']}",
            ", ".join(
                f"{group['count']} {name} rss {_gib(group['rss'])} pss "
                f"{_gib(group['pss'])}"
                for name, group in roles.items()
            ),
            f"host avail {_gib(memory.get('MemAvailable'))}/"
            f"{_gib(memory.get('MemTotal'))} swapfree {_gib(memory.get('SwapFree'))}/"
            f"{_gib(memory.get('SwapTotal'))} oom_kill +"
            f"{self.peaks.get('oom_kill_delta', '?')}",
            f"psi10 mem {pressure['memory'].get('some', '?')}/"
            f"{pressure['memory'].get('full', '?')} io {pressure['io'].get('full', '?')}"
            f" cpu {pressure['cpu'].get('some', '?')}",
            f"cgroup {_gib(cgroup.get('current'))}/{cgroup.get('max', '?')} "
            f"oom_kill {cgroup.get('events', {}).get('oom_kill', '?')}",
            "free "
            + " ".join(
                f"{label} {_gib(fs['free_bytes'])}/{fs['free_inodes']}i"
                for label, fs in record["filesystems"].items()
                if fs is not None
            ),
        ]
        if "scratch_usage" in record:
            usage = record["scratch_usage"]
            parts.append(
                f"scratch used {_gib(usage['bytes'])} in {usage['entries']} entries"
                + (" (truncated)" if usage["truncated"] else "")
            )
        parts.append(self._format_progress(record.get("progress"), record["at"]))
        return " | ".join(parts)

    def _format_progress(self, progress: Mapping[str, Any] | None, now: float) -> str:
        if not progress:
            return "progress none yet"
        controller = progress.get("controller") or {}
        collection = controller.get("collection") or {}
        text = (
            f"{progress['repeat']} collected {collection.get('workers_finished', 0)}/"
            f"{controller.get('workers_configured', '?')} workers "
            f"({collection.get('items', 0)} items) tests {controller.get('finished', 0)}"
            f" done {controller.get('failed_reports', 0)} failed"
        )
        running = _running(progress.get("workers") or {})
        if running:
            oldest = running[0]
            text += (
                f" | {len(running)} in flight, oldest "
                f"{_age(now, oldest.get('started_at'))} {oldest.get('worker')} "
                f"{oldest.get('nodeid')}"
            )
        if progress.get("kill_count"):
            text += f" | {progress['kill_count']} hazardous kill call(s)"
        return text

    def on_signal(self, info: Any) -> dict[str, Any]:
        stats, depths = self._tree()
        progress = read_progress(self.out / PROGRESS_DIRNAME) or {}
        workers = progress.get("workers") or {}
        chain: list[dict[str, Any]] = []
        pid = int(info.si_pid)
        while pid > 0 and len(chain) < 8 and all(item["pid"] != pid for item in chain):
            stat = stats.get(pid) or self.procfs.stat(pid)
            worker = (workers.get(pid) or {}).get("worker")
            if stat is not None:
                chain.append(
                    {
                        "pid": pid,
                        "comm": stat.comm,
                        "role": role(depths[pid]) if pid in depths else "outside soak",
                        "worker": worker,
                        "cmdline": self.procfs.cmdline(pid),
                    }
                )
                pid = stat.ppid
                continue
            known = self.last_seen.get(pid)
            if known is None:
                chain.append({"pid": pid, "gone": True})
                break
            chain.append(
                {
                    "pid": pid,
                    "comm": known["comm"],
                    "role": known["role"],
                    "worker": worker,
                    "cmdline": known["cmdline"],
                    "gone": True,
                    "last_seen_elapsed": known["seen_at"],
                }
            )
            pid = known["ppid"]
        sender_worker = next(
            (workers[item["pid"]] for item in chain if item["pid"] in workers), None
        )
        now = time.time()
        record = {
            "kind": "signal",
            "at": now,
            "elapsed": self._elapsed(),
            "signal": signal.Signals(info.si_signo).name,
            "code": SI_CODE_NAMES.get(info.si_code, str(info.si_code)),
            "sender_pid": info.si_pid,
            "sender_uid": info.si_uid,
            "sender_in_soak": info.si_pid in depths,
            "sender_chain": chain,
            "sender_worker": sender_worker,
            "soak_procs": len(depths),
            "inflight": _running(workers),
            "kill_count": progress.get("kill_count", 0),
            "kills": progress.get("kills", []),
        }
        self.signals += 1
        self._append(SIGNALS_FILENAME, record, MAX_SIGNAL_RECORDS - self.signals + 1)
        for line in self.format_signal(record):
            self.emit(line)
        return record

    def format_signal(self, record: Mapping[str, Any]) -> list[str]:
        where = "inside" if record["sender_in_soak"] else "outside"
        lines = [
            f" +{record['elapsed']:.0f}s {record['signal']} ({record['code']}) from pid "
            f"{record['sender_pid']} uid {record['sender_uid']}, {where} the soak tree "
            f"({record['soak_procs']} soak processes alive)"
        ]
        for item in record["sender_chain"]:
            if "comm" not in item:
                label = "exited before it could be read and was never sampled"
            else:
                worker = f" {item['worker']}" if item.get("worker") else ""
                label = f"{item['comm']} [{item['role']}{worker}]"
                if item.get("gone"):
                    label += (
                        f" (exited; last sampled at +{item['last_seen_elapsed']:.0f}s)"
                    )
                label += f" {item.get('cmdline') or ''}"
            lines.append(f"   sender chain: {item['pid']} {label}")
        if record["sender_worker"]:
            worker = record["sender_worker"]
            lines.append(
                f"   sender's worker {worker.get('worker')} was running "
                f"{worker.get('nodeid')}"
            )
        for item in record["inflight"][:PRINT_LIMIT]:
            lines.append(
                f"   in flight: {item.get('worker')} pid {item.get('pid')} "
                f"{_age(record['at'], item.get('started_at'))} {item.get('nodeid')}"
            )
        for kill in record["kills"]:
            lines.append(
                f"   hazardous kill: {kill.get('worker')} {kill.get('call')} "
                f"({kill.get('reason')}) during {kill.get('nodeid')}"
            )
        return lines

    def finish(self, reason: str) -> None:
        self.sample(reason=f"final: {reason}")
        peaks = ", ".join(
            _peak_text(key, value) for key, value in sorted(self.peaks.items())
        )
        self.emit(
            f" stopped ({reason}) after {self._elapsed():.0f}s, {self.samples} samples, "
            f"{self.signals} signal(s); peaks: {peaks}"
        )


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

    def stop(self, timeout: float = 10.0) -> int | None:
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
                return self.process.wait(timeout=5)
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


if __name__ == "__main__":
    raise SystemExit(main())

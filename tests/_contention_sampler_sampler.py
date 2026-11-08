"""The contention sampler's collection loop."""

from __future__ import annotations

import json
import os
import platform
import signal
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any, TextIO

from tests._contention import PROGRESS_DIRNAME
from tests._contention_procfs import (
    ProcFS,
    ProcStat,
    filesystem,
    scan_usage,
    soak_tree,
)
from tests._contention_sampler_common import (
    LAST_SEEN_LIMIT,
    LAST_SEEN_SECONDS,
    MAX_SAMPLE_RECORDS,
    MAX_SIGNAL_RECORDS,
    POST_ROOT_OBSERVATION_LIMIT,
    SAMPLER_REAP_TIMEOUT_SECONDS,
    SAMPLER_STOP_TIMEOUT_SECONDS,
    SAMPLES_FILENAME,
    SIGNALS_FILENAME,
    SI_CODE_NAMES,
    USAGE_SCAN_EVERY,
    LOG_PREFIX,
    read_progress,
    role,
)
from tests._contention_sampler_format import (
    format_header_text,
    format_peaks_text,
    format_sample_text,
    format_signal_lines,
    format_progress_text,
    running_workers,
)


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
        root = procfs.stat(root_pid)
        self.root_start_time_ticks = root.start_time_ticks if root is not None else None
        self.root_alive = self.root_start_time_ticks is not None
        self.post_root_observations = 0
        self.membership = "descendants"
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
            "root_start_time_ticks": self.root_start_time_ticks,
            "post_root_observation_limit": POST_ROOT_OBSERVATION_LIMIT,
            "sampler_stop_timeout_seconds": SAMPLER_STOP_TIMEOUT_SECONDS,
            "sampler_reap_timeout_seconds": SAMPLER_REAP_TIMEOUT_SECONDS,
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
        self.emit(format_header_text(record, os.getpid(), self.out))
        return record

    def _tree(self) -> tuple[dict[int, ProcStat], dict[int, int]]:
        if (
            not self.root_alive
            and self.post_root_observations >= POST_ROOT_OBSERVATION_LIMIT
        ):
            return {}, {}
        stats = self.procfs.all_stats()
        root = stats.get(self.root_pid)
        if root is None:
            root = self.procfs.stat(self.root_pid)
            if root is not None:
                stats[root.pid] = root
        if (
            root is not None
            and self.root_start_time_ticks is not None
            and root.start_time_ticks == self.root_start_time_ticks
        ):
            self.root_alive = True
            self.post_root_observations = 0
            self.membership = "descendants"
            return stats, soak_tree(stats, self.root_pid, exclude=os.getpid())

        self.root_alive = False
        self.membership = "observed-survivors"
        if self.post_root_observations >= POST_ROOT_OBSERVATION_LIMIT:
            return stats, {}
        self.post_root_observations += 1
        return stats, self._survivor_tree(stats)

    def _survivor_tree(self, stats: Mapping[int, ProcStat]) -> dict[int, int]:
        """Only keep prior run members with the same PID and kernel start tick.

        Descendants of a surviving, identity-checked member are also in the
        run-owned tree. Process-group membership alone is never evidence.
        """
        children: dict[int, list[int]] = {}
        for stat in stats.values():
            children.setdefault(stat.ppid, []).append(stat.pid)

        depths: dict[int, int] = {}
        pending: list[tuple[int, int]] = []
        reused_pids: set[int] = set()
        for pid, known in self.last_seen.items():
            stat = stats.get(pid)
            if stat is None:
                continue
            if stat.start_time_ticks != known.get("start_time_ticks"):
                reused_pids.add(pid)
                continue
            depth = known.get("depth")
            if isinstance(depth, int) and pid != os.getpid():
                depths[pid] = depth
                pending.append((pid, depth))

        while pending:
            parent, depth = pending.pop()
            for child in children.get(parent, ()):
                if child == os.getpid() or child in depths or child in reused_pids:
                    continue
                depths[child] = depth + 1
                pending.append((child, depth + 1))
        return depths

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
            "root_alive": self.root_alive,
            "root_start_time_ticks": self.root_start_time_ticks,
            "post_root_observations": self.post_root_observations,
            "membership": self.membership,
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
            same_process = (
                known is not None
                and known.get("start_time_ticks") == stats[pid].start_time_ticks
            )
            cmdline = (
                known.get("cmdline")
                if same_process and known
                else self.procfs.cmdline(pid)
            )
            self.last_seen[pid] = {
                "comm": stats[pid].comm,
                "ppid": stats[pid].ppid,
                "start_time_ticks": stats[pid].start_time_ticks,
                "depth": depth,
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
        return format_sample_text(record, self.peaks)

    def _format_progress(self, progress: Mapping[str, Any] | None, now: float) -> str:
        return format_progress_text(progress, now)

    def on_signal(self, info: Any) -> dict[str, Any]:
        stats, depths = self._tree()
        progress = read_progress(self.out / PROGRESS_DIRNAME) or {}
        workers = progress.get("workers") or {}

        def matching_worker(pid: int) -> Mapping[str, Any] | None:
            worker = workers.get(pid)
            if not isinstance(worker, Mapping):
                return None
            stat = stats.get(pid)
            known = self.last_seen.get(pid)
            start_time_ticks = (
                stat.start_time_ticks
                if stat is not None
                else known.get("start_time_ticks")
                if known is not None
                else None
            )
            worker_start = worker.get("start_time_ticks")
            if (
                not isinstance(start_time_ticks, int)
                or not isinstance(worker_start, int)
                or start_time_ticks != worker_start
            ):
                return None
            return worker

        chain: list[dict[str, Any]] = []
        pid = int(info.si_pid)
        while pid > 0 and len(chain) < 8 and all(item["pid"] != pid for item in chain):
            stat = stats.get(pid) or self.procfs.stat(pid)
            worker_record = matching_worker(pid)
            worker = worker_record.get("worker") if worker_record else None
            if stat is not None:
                chain.append(
                    {
                        "pid": pid,
                        "comm": stat.comm,
                        "role": role(depths[pid]) if pid in depths else "outside soak",
                        "worker": worker,
                        "start_time_ticks": stat.start_time_ticks,
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
                    "start_time_ticks": known["start_time_ticks"],
                    "cmdline": known["cmdline"],
                    "gone": True,
                    "last_seen_elapsed": known["seen_at"],
                }
            )
            pid = known["ppid"]
        sender_worker = next(
            (record for item in chain if (record := matching_worker(item["pid"]))),
            None,
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
            "root_alive": self.root_alive,
            "post_root_observations": self.post_root_observations,
            "sender_chain": chain,
            "sender_worker": sender_worker,
            "soak_procs": len(depths),
            "inflight": running_workers(workers),
            "kill_count": progress.get("kill_count", 0),
            "kills": progress.get("kills", []),
        }
        self.signals += 1
        self._append(SIGNALS_FILENAME, record, MAX_SIGNAL_RECORDS - self.signals + 1)
        for line in self.format_signal(record):
            self.emit(line)
        return record

    def format_signal(self, record: Mapping[str, Any]) -> list[str]:
        return format_signal_lines(record)

    def finish(self, reason: str) -> None:
        self.sample(reason=f"final: {reason}")
        peaks = format_peaks_text(self.peaks)
        self.emit(
            f" stopped ({reason}) after {self._elapsed():.0f}s, {self.samples} samples, "
            f"{self.signals} signal(s); peaks: {peaks}"
        )

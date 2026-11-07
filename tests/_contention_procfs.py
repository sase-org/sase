"""Best-effort ``/proc``, cgroup, and filesystem readers for the contention sampler.

Diagnostic only, and standard library only: `tests._contention_sampler` runs as
its own process and must not pay for importing pytest. Every reader tolerates a
missing or unreadable field -- a container without PSI, a cgroup v1 host, a
process that exited mid-read -- by leaving that field out rather than failing.
The roots are parameters so tests can describe such hosts with plain files.
"""

from __future__ import annotations

import os
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any


#: Scratch walks are capped by entry count and wall time, so a deliberately
#: starved run is not also an I/O soak.
USAGE_SCAN_MAX_ENTRIES = 200_000
USAGE_SCAN_MAX_SECONDS = 2.0
CMDLINE_LIMIT = 240
PAGE_SIZE = os.sysconf("SC_PAGE_SIZE")


@dataclass(frozen=True)
class ProcStat:
    """The ``/proc/<pid>/stat`` fields the sampler reports."""

    pid: int
    ppid: int
    pgrp: int
    comm: str
    state: str
    threads: int
    rss_bytes: int
    major_faults: int


def parse_stat(pid: int, raw: str) -> ProcStat:
    close = raw.rindex(")")
    fields = raw[close + 2 :].split()
    return ProcStat(
        pid=pid,
        ppid=int(fields[1]),
        pgrp=int(fields[2]),
        comm=raw[raw.index("(") + 1 : close],
        state=fields[0],
        threads=int(fields[17]),
        rss_bytes=int(fields[21]) * PAGE_SIZE,
        major_faults=int(fields[9]),
    )


def _kib_fields(raw: str | None, names: frozenset[str]) -> dict[str, int]:
    values: dict[str, int] = {}
    for line in (raw or "").splitlines():
        key, _, rest = line.partition(":")
        if key in names and rest.split():
            try:
                values[key] = int(rest.split()[0]) * 1024
            except ValueError:
                continue
    return values


class ProcFS:
    """Best-effort readers; a missing or unreadable field is simply absent."""

    def __init__(
        self,
        root: Path = Path("/proc"),
        cgroup_root: Path = Path("/sys/fs/cgroup"),
    ) -> None:
        self.root = root
        self.cgroup_root = cgroup_root

    def read(self, *parts: str | int) -> str | None:
        try:
            return self.root.joinpath(*map(str, parts)).read_text(errors="replace")
        except OSError:
            return None

    def stat(self, pid: int) -> ProcStat | None:
        raw = self.read(pid, "stat")
        try:
            return None if raw is None else parse_stat(pid, raw)
        except (ValueError, IndexError):
            return None

    def all_stats(self) -> dict[int, ProcStat]:
        stats: dict[int, ProcStat] = {}
        try:
            names = [entry.name for entry in os.scandir(self.root)]
        except OSError:
            return stats
        for name in names:
            if name.isdigit() and (stat := self.stat(int(name))) is not None:
                stats[stat.pid] = stat
        return stats

    def cmdline(self, pid: int) -> str | None:
        raw = self.read(pid, "cmdline")
        if not raw:
            return None
        return raw.replace("\0", " ").strip()[:CMDLINE_LIMIT]

    def rollup(self, pid: int) -> dict[str, int]:
        return _kib_fields(self.read(pid, "smaps_rollup"), frozenset({"Pss", "Swap"}))

    def cpus_allowed(self, pid: int) -> str | None:
        for line in (self.read(pid, "status") or "").splitlines():
            if line.startswith("Cpus_allowed_list:"):
                return line.split(":", 1)[1].strip()
        return None

    def meminfo(self) -> dict[str, int]:
        names = frozenset(
            {"MemTotal", "MemAvailable", "SwapTotal", "SwapFree", "Shmem"}
        )
        return _kib_fields(self.read("meminfo"), names)

    def vmstat(self) -> dict[str, int]:
        values: dict[str, int] = {}
        for line in (self.read("vmstat") or "").splitlines():
            key, _, value = line.partition(" ")
            if key in ("oom_kill", "pswpin", "pswpout") and value.strip().isdigit():
                values[key] = int(value)
        return values

    def pressure(self, raw: str | None) -> dict[str, float]:
        values: dict[str, float] = {}
        for line in (raw or "").splitlines():
            kind, _, rest = line.partition(" ")
            for item in rest.split():
                key, _, value = item.partition("=")
                if key == "avg10":
                    try:
                        values[kind] = float(value)
                    except ValueError:
                        pass
        return values

    def loadavg(self) -> list[float] | None:
        try:
            return [float(value) for value in (self.read("loadavg") or "").split()[:3]]
        except ValueError:
            return None

    def cgroup(self) -> dict[str, Any] | None:
        raw = self.read("self", "cgroup") or ""
        path = next(
            (line[3:] for line in raw.splitlines() if line.startswith("0::")), None
        )
        if path is None:
            return None
        base = self.cgroup_root / path.lstrip("/")
        record: dict[str, Any] = {"path": path}
        for name in (
            "memory.current",
            "memory.max",
            "memory.peak",
            "memory.swap.current",
        ):
            try:
                value = (base / name).read_text().strip()
            except OSError:
                continue
            record[name.removeprefix("memory.")] = (
                int(value) if value.isdigit() else value
            )
        try:
            events = (base / "memory.events").read_text()
        except OSError:
            events = ""
        record["events"] = {
            key: int(value)
            for key, _, value in (line.partition(" ") for line in events.splitlines())
            if value.strip().isdigit()
        }
        try:
            record["pressure"] = self.pressure((base / "memory.pressure").read_text())
        except OSError:
            pass
        return record


def soak_tree(stats: Mapping[int, ProcStat], root: int, exclude: int) -> dict[int, int]:
    """PID to depth for ``root`` and its descendants, minus ``exclude``'s subtree.

    Each PID is visited once, so nested child trees are never double-counted.
    """
    children: dict[int, list[int]] = {}
    for stat in stats.values():
        children.setdefault(stat.ppid, []).append(stat.pid)
    depths: dict[int, int] = {}
    pending = [(root, 0)] if root in stats else []
    while pending:
        pid, depth = pending.pop()
        if pid in depths or pid == exclude:
            continue
        depths[pid] = depth
        pending.extend((child, depth + 1) for child in children.get(pid, ()))
    return depths


def scan_usage(path: Path) -> dict[str, Any]:
    """Allocated bytes under ``path``, capped by entry count and wall time."""
    allocated = entries = 0
    truncated = False
    deadline = time.monotonic() + USAGE_SCAN_MAX_SECONDS
    pending = [str(path)]
    while pending and not truncated:
        try:
            with os.scandir(pending.pop()) as listing:
                for entry in listing:
                    entries += 1
                    try:
                        allocated += entry.stat(follow_symlinks=False).st_blocks * 512
                        if entry.is_dir(follow_symlinks=False):
                            pending.append(entry.path)
                    except OSError:
                        pass
                    if entries >= USAGE_SCAN_MAX_ENTRIES or time.monotonic() > deadline:
                        truncated = True
                        break
        except OSError:
            continue
    return {"bytes": allocated, "entries": entries, "truncated": truncated}


def filesystem(path: Path) -> dict[str, Any] | None:
    try:
        stats = os.statvfs(path)
        device = os.stat(path).st_dev
    except OSError:
        return None
    return {
        "path": str(path),
        "device": device,
        "free_bytes": stats.f_bavail * stats.f_frsize,
        "total_bytes": stats.f_blocks * stats.f_frsize,
        "free_inodes": stats.f_favail,
        "total_inodes": stats.f_files,
    }

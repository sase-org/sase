"""Demand resource usage: tree RSS, load sampling, rusage, and formatters."""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pytest

from sase.tool.demand import (
    TREE_RSS_UNAVAILABLE,
    build_resource_usage,
    format_ceiling_seconds,
    format_cpu_cores,
    tree_rss_kib,
)
from sase.tool.render import format_kib
from sase.tool.sample import LoadSampler


def _write_stat(proc_root: Path, pid: int, comm: str, ppid: int, rss: int) -> None:
    directory = proc_root / str(pid)
    directory.mkdir(parents=True, exist_ok=True)
    # state ppid pgrp session tty tpgid flags minflt cminflt majflt cmajflt
    # utime stime cutime cstime priority nice threads itreal starttime vsize
    # rss: 22 fields, ppid at 1 and rss pages at 21.
    fields = (
        ["S", str(ppid), "1", "1", "0", "-1", "0"]
        + ["0"] * 8
        + [
            "20",
            "0",
            "1",
            "0",
            "100",
            "0",
            str(rss),
        ]
    )
    assert len(fields) == 22
    (directory / "stat").write_text(
        f"{pid} ({comm}) {' '.join(fields)}", encoding="utf-8"
    )


def test_tree_rss_sums_descendants_and_survives_tricky_comm(
    tmp_path: Path,
) -> None:
    proc = tmp_path / "proc"
    _write_stat(proc, 100, "mycmd", 1, 10)
    _write_stat(proc, 101, "child", 100, 20)
    _write_stat(proc, 102, "we)ird) (name", 101, 30)
    _write_stat(proc, 200, "unrelated", 1, 1000)
    # 60 pages at 4 KiB pages.
    assert tree_rss_kib(100, proc_root=proc, page_size=4096) == 60 * 4
    assert tree_rss_kib(101, proc_root=proc, page_size=4096) == 50 * 4


def test_tree_rss_vanished_pid_and_missing_root(tmp_path: Path) -> None:
    proc = tmp_path / "proc"
    _write_stat(proc, 100, "mycmd", 1, 10)
    assert tree_rss_kib(999, proc_root=proc) is None
    assert tree_rss_kib(100, proc_root=tmp_path / "absent") is None


def test_load_sampler_tracks_peak_and_unavailability(tmp_path: Path) -> None:
    proc = tmp_path / "proc"
    _write_stat(proc, 100, "mycmd", 1, 10)
    sampler = LoadSampler(run_id="run-1", started=time.monotonic(), child_pid=100)
    sampler.proc_root = str(proc)
    first = sampler.maybe_sample_tree_rss()
    assert first == 10 * (os.sysconf("SC_PAGE_SIZE") // 1024)
    assert sampler.tree_rss_samples == 1
    assert sampler.peak_tree_rss_kib == first
    sampler.stop_tree_sampling()
    assert sampler.maybe_sample_tree_rss() is None
    assert sampler.tree_rss_samples == 1


def test_load_sampler_without_proc_root_reports_unavailable(
    tmp_path: Path,
) -> None:
    sampler = LoadSampler(
        run_id="run-1",
        started=time.monotonic(),
        child_pid=100,
        proc_root=str(tmp_path / "absent"),
    )
    assert sampler.maybe_sample_tree_rss() is None
    assert sampler.tree_rss_unavailable == "tree RSS unavailable on this host"
    assert sampler.tree_rss_samples == 0


class _Rusage:
    def __init__(self, utime: float, stime: float, maxrss: int) -> None:
        self.ru_utime = utime
        self.ru_stime = stime
        self.ru_maxrss = maxrss


def test_build_resource_usage_from_rusage() -> None:
    usage = build_resource_usage(
        _Rusage(1.5, 0.25, 2048),
        peak_tree_rss_kib=10240,
        tree_rss_samples=3,
    )
    assert usage == {
        "cpu_user_ms": 1500,
        "cpu_system_ms": 250,
        "max_process_rss_kib": 2048,
        "peak_tree_rss_kib": 10240,
        "tree_rss_samples": 3,
        "availability": [],
    }


def test_build_resource_usage_without_rusage_carries_reason() -> None:
    usage = build_resource_usage(None, tree_rss_samples=2)
    assert usage["tree_rss_samples"] == 2
    assert usage["availability"] == ["rusage unavailable"]
    assert "cpu_user_ms" not in usage
    assert "max_process_rss_kib" not in usage


def test_build_resource_usage_normalizes_darwin_bytes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "platform", "darwin")
    usage = build_resource_usage(_Rusage(0.0, 0.0, 2048 * 1024))
    assert usage["max_process_rss_kib"] == 2048


def test_build_resource_usage_floors_zero_tree_peak_at_process_rss() -> None:
    """A zombie-state tree sample reads RSS 0; the peak floors at ru_maxrss."""

    usage = build_resource_usage(
        _Rusage(1.5, 0.25, 2048),
        peak_tree_rss_kib=0,
        tree_rss_samples=1,
    )
    assert usage["peak_tree_rss_kib"] == 2048
    assert usage["tree_rss_samples"] == 1


def test_build_resource_usage_floors_missing_tree_peak_at_process_rss() -> None:
    """A child gone before every sample leaves no peak; ru_maxrss fills it."""

    usage = build_resource_usage(_Rusage(1.5, 0.25, 2048))
    assert usage["peak_tree_rss_kib"] == 2048
    assert usage["tree_rss_samples"] == 0


def test_build_resource_usage_keeps_smaller_nonzero_tree_peak() -> None:
    """Only a missing or zero peak falls back; a measured peak stands."""

    usage = build_resource_usage(
        _Rusage(1.5, 0.25, 2048),
        peak_tree_rss_kib=512,
        tree_rss_samples=2,
    )
    assert usage["peak_tree_rss_kib"] == 512


def test_build_resource_usage_no_floor_when_tree_unavailable() -> None:
    """Without a process tree to sample, no process-RSS value poses as one."""

    usage = build_resource_usage(
        _Rusage(1.5, 0.25, 2048), availability=[TREE_RSS_UNAVAILABLE]
    )
    assert "peak_tree_rss_kib" not in usage
    assert usage["availability"] == [TREE_RSS_UNAVAILABLE]


def test_build_resource_usage_floor_uses_darwin_normalized_rss(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "platform", "darwin")
    usage = build_resource_usage(
        _Rusage(0.0, 0.0, 2048 * 1024),
        peak_tree_rss_kib=0,
        tree_rss_samples=1,
    )
    assert usage["max_process_rss_kib"] == 2048
    assert usage["peak_tree_rss_kib"] == 2048


def test_format_kib() -> None:
    assert format_kib(None) == "—"
    assert format_kib(512) == "512 KiB"
    assert format_kib(1127) == "1.1 MiB"
    assert format_kib(10276045) == "9.8 GiB"


def test_format_ceiling_seconds() -> None:
    assert format_ceiling_seconds(None) == "—"
    assert format_ceiling_seconds(14400) == "4h"
    assert format_ceiling_seconds(600) == "10m"
    assert format_ceiling_seconds(45) == "45s"


def test_format_cpu_cores() -> None:
    assert format_cpu_cores(2340000, 600000) == "3.9"
    assert format_cpu_cores(100, 999) is None
    assert format_cpu_cores(None, 600000) is None
    assert format_cpu_cores(100, None) is None

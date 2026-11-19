"""Per-process TUI faulthandler spools and their harvest into tui_faults.log."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from sase.logs import tui_faults
from sase.logs.tui_faults import (
    FAULT_LOG_NAME,
    SPOOL_DIR_NAME,
    close_tui_fault_spool,
    harvest_tui_fault_spools,
    open_tui_fault_spool,
)


def _dead_pid() -> int:
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()
    return proc.pid


def _spool(logs_dir: Path, name: str, content: str) -> Path:
    spool_dir = logs_dir / SPOOL_DIR_NAME
    spool_dir.mkdir(parents=True, exist_ok=True)
    path = spool_dir / name
    path.write_text(content, encoding="utf-8")
    return path


def test_open_spool_names_pid_start_and_sanitized_version(tmp_path: Path) -> None:
    spool = open_tui_fault_spool(
        tmp_path, version="0.19.1-rc/1", pid=4321, start_time=1_700_000_000.5
    )
    try:
        assert (
            spool.path
            == tmp_path / SPOOL_DIR_NAME / "4321-1700000000500-0.19.1_rc_1.log"
        )
        assert spool.path.read_text() == ""
        assert spool.file.fileno() >= 0
    finally:
        close_tui_fault_spool(spool)


def test_close_deletes_an_empty_spool_and_keeps_a_written_one(tmp_path: Path) -> None:
    empty = open_tui_fault_spool(tmp_path, version="1.0", pid=1, start_time=1.0)
    close_tui_fault_spool(empty)
    assert not empty.path.exists()

    written = open_tui_fault_spool(tmp_path, version="1.0", pid=2, start_time=2.0)
    written.file.write("Fatal Python error\n")
    close_tui_fault_spool(written)
    assert written.path.read_text() == "Fatal Python error\n"


def test_harvest_appends_dead_faults_under_headers_in_start_order(
    tmp_path: Path,
) -> None:
    pid = _dead_pid()
    later = _spool(tmp_path, f"{pid}-1700000060000-0.19.0.log", "second fault")
    earlier = _spool(tmp_path, f"{pid}-1700000000000-0.18.0.log", "first fault\n")
    empty = _spool(tmp_path, f"{pid}-1700000030000-0.19.0.log", "")

    assert harvest_tui_fault_spools(tmp_path) == 2

    assert (tmp_path / FAULT_LOG_NAME).read_text() == (
        f"\n[2023-11-14T22:13:20Z] pid={pid} sase=0.18.0\nfirst fault\n"
        f"\n[2023-11-14T22:14:20Z] pid={pid} sase=0.19.0\nsecond fault\n"
    )
    assert not later.exists()
    assert not earlier.exists()
    assert not empty.exists()


def test_harvest_leaves_live_spools_and_foreign_files_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    live_pid = 4242
    real_kill = os.kill

    def fake_kill(pid: int, signal: int) -> None:
        if pid == live_pid:
            return
        real_kill(pid, signal)

    monkeypatch.setattr(tui_faults.os, "kill", fake_kill)
    live = _spool(tmp_path, f"{live_pid}-1700000000000-0.19.0.log", "in flight")
    foreign = _spool(tmp_path, "notes.txt", "not a spool")

    assert harvest_tui_fault_spools(tmp_path) == 0

    assert live.read_text() == "in flight"
    assert foreign.read_text() == "not a spool"
    assert not (tmp_path / FAULT_LOG_NAME).exists()


def test_harvest_treats_this_pids_other_spools_as_an_earlier_exec_image(
    tmp_path: Path,
) -> None:
    spool = _spool(tmp_path, f"{os.getpid()}-1700000000000-0.18.0.log", "crash")

    assert harvest_tui_fault_spools(tmp_path) == 1

    assert "crash" in (tmp_path / FAULT_LOG_NAME).read_text()
    assert not spool.exists()


def test_harvest_without_a_spool_dir_is_a_no_op(tmp_path: Path) -> None:
    assert harvest_tui_fault_spools(tmp_path) == 0
    assert not (tmp_path / FAULT_LOG_NAME).exists()

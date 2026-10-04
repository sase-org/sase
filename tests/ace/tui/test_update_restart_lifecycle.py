"""Isolated-process regressions for TUI update-restart independence."""

from __future__ import annotations

import os
import signal
import sys
import time
from pathlib import Path

import pytest

from sase.ace.hooks.processes import is_process_running
from sase.ace.tui.proc_observer import ProcObserver, ProcObserverSnapshot
from sase.procs import (
    get_proc,
    kill_proc,
    read_proc_log_tail,
    submit_proc,
    wait_for_proc,
)
from sase.service.config import (
    ServiceEnablementSource,
    ServiceLauncher,
    ServiceProcConfig,
)
from sase.service.host import _ServiceHost


_TOKEN = "lifecycle-ok"


def _wait_until(predicate, *, timeout: float, message: str) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.05)  # sase-test-wait: bounded handshake for isolated procs
    pytest.fail(message)


def _wait_for_running(proc_id: str):
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        proc = get_proc(proc_id)
        assert proc is not None
        if proc.status == "running":
            return proc
        if proc.status not in {"pending", "running"}:
            pytest.fail(f"proc became {proc.status} before it was observed running")
        time.sleep(min(0.025, max(0.0, deadline - time.monotonic())))
    pytest.fail("proc did not enter running state")


def _observer_row(observer: ProcObserver, proc_id: str):
    snapshot = observer.poll_once()
    if snapshot is None:
        return None
    for row in snapshot.projection.rows:
        if row.proc_id == proc_id or row.durable_proc_id == proc_id:
            return row
    return None


def _service_entry(*, argv: tuple[str, ...], name: str = "demo") -> ServiceProcConfig:
    return ServiceProcConfig(
        name=name,
        available=True,
        source="user",
        declared_by="pytest",
        enabled=True,
        enablement=ServiceEnablementSource(explicit=True, layer="pytest"),
        mode="daemon",
        restart="on-failure",
        stop_signal="SIGTERM",
        stop_timeout_seconds=1.0,
        log_max_bytes=1024,
        launcher=ServiceLauncher(
            kind="command",
            command=list(argv),
            argv=argv,
        ),
        success_exit_codes=(0,),
    )


def test_tool_run_survives_observer_stop_and_reconnect(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    snapshots: list[ProcObserverSnapshot] = []
    observer = ProcObserver(on_snapshot=snapshots.append)
    proc = None
    try:
        observer.start()
        assert observer.running
        proc = submit_proc(
            [
                sys.executable,
                "-c",
                (f"import time, sys; print({_TOKEN!r}, flush=True); time.sleep(8)"),
            ],
            label="tool-run lifecycle",
            cwd=tmp_path,
            origin="tool-run",
        )
        running = _wait_for_running(proc.proc_id)
        assert running.pid is not None
        first_pid = running.pid
        _wait_until(
            lambda: _observer_row(observer, proc.proc_id) is not None,
            timeout=10,
            message="first observer never published the tool-run row",
        )
        observer.stop()
        assert not observer.running

        reconnect = ProcObserver(on_snapshot=snapshots.append)
        try:
            reconnect.start()
            assert reconnect.running
            _wait_until(
                lambda: _observer_row(reconnect, proc.proc_id) is not None,
                timeout=10,
                message="reconnected observer never published the tool-run row",
            )
            still = get_proc(proc.proc_id)
            assert still is not None
            assert still.pid == first_pid
            assert is_process_running(first_pid)
            finished = wait_for_proc(proc.proc_id, timeout=15)
            assert finished.status == "success"
            assert finished.exit_code == 0
            log = read_proc_log_tail(proc.proc_id, 20, log_path=finished.log_path)
            assert _TOKEN in log
            settled = get_proc(proc.proc_id)
            assert settled is not None
            assert settled.status == "success"
        finally:
            reconnect.stop()
    finally:
        observer.stop()
        if proc is not None:
            current = get_proc(proc.proc_id)
            if current is not None and current.status in {"pending", "running"}:
                kill_proc(proc.proc_id)
                wait_for_proc(proc.proc_id, timeout=15)


def test_detached_command_survives_isolated_service_host_restart(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    detached = submit_proc(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        label="unrelated tool-run",
        cwd=tmp_path,
        origin="tool-run",
    )
    host_child_pid: int | None = None
    try:
        running = _wait_for_running(detached.proc_id)
        assert running.pid is not None
        detached_pid = running.pid
        entry = _service_entry(
            argv=(sys.executable, "-c", "import time; time.sleep(30)"),
        )
        host = _ServiceHost()
        host._launch(entry, history=None)
        assert "demo" in host._children
        host_child_pid = host._children["demo"].process.pid
        assert host_child_pid is not None
        assert is_process_running(host_child_pid)
        host._stop_all_children()
        _wait_until(
            lambda: not is_process_running(host_child_pid),
            timeout=10,
            message="service-host child kept running after stop",
        )
        recreated = _ServiceHost()
        assert recreated._children == {}
        still = get_proc(detached.proc_id)
        assert still is not None
        assert still.pid == detached_pid
        assert is_process_running(detached_pid)
        assert still.status == "running"
    finally:
        current = get_proc(detached.proc_id)
        if current is not None and current.status in {"pending", "running"}:
            kill_proc(detached.proc_id)
            wait_for_proc(detached.proc_id, timeout=15)
        if host_child_pid is not None and is_process_running(host_child_pid):
            try:
                os.kill(host_child_pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError, OSError):
                pass

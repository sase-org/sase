"""Proc requests and oneshot settle: explicit start/restart plus orphans."""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pytest

from sase.ace.hooks.processes import is_process_running
from sase.procs import ACTIVE_PROC_STATUSES, TERMINAL_PROC_STATUSES, get_proc
from sase.procs.identity import supervisor_identity_token
from sase.procs.oneshot import settle_orphaned_oneshots
from sase.service.config import ServiceConfigComposition
from sase.service.state import (
    read_service_state,
    record_service_stop,
    request_service_proc,
)
from sase.service.host import _ServiceHost
from tests.service.service_host_scenario_helpers import (
    _SLEEPER,
    _claim_row,
    _compose,
    _layer_spec,
    _reserve_oneshot_row,
    _service_host,
    _wait_for,
)


def test_host_start_settles_orphaned_oneshots_without_relaunching(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A leftover active oneshot settles terminally with unknown outcome."""
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))

    orphan_id = _reserve_oneshot_row("oneshot-orphan", tmp_path)
    _claim_row(orphan_id, supervisor_id="dead-boot:12345", pid=424242, pgid=424242)
    fresh_id = _reserve_oneshot_row("oneshot-fresh", tmp_path)
    alive_id = _reserve_oneshot_row("oneshot-alive", tmp_path)
    _claim_row(
        alive_id,
        supervisor_id=supervisor_identity_token(os.getpid()),
        pid=os.getpid(),
        pgid=os.getpgrp(),
    )
    for proc_id in (orphan_id, fresh_id, alive_id):
        assert get_proc(proc_id) is not None
        assert get_proc(proc_id).status in ACTIVE_PROC_STATUSES  # type: ignore[union-attr]

    settled = settle_orphaned_oneshots()

    assert {proc.proc_id for proc in settled} == {orphan_id}
    orphan = get_proc(orphan_id)
    assert orphan is not None and orphan.status in TERMINAL_PROC_STATUSES
    assert "unknown" in (orphan.message or "")
    # Settle-once: a second startup pass finds nothing to do.
    assert settle_orphaned_oneshots() == []

    # Rows with a live supervisor (or still inside the unclaimed grace
    # window) are left alone for their owner to finish.
    for proc_id in (fresh_id, alive_id):
        current = get_proc(proc_id)
        assert current is not None and current.status in ACTIVE_PROC_STATUSES

    # The host reconcile loop never picks the settled row back up.
    monkeypatch.setattr(
        "sase.service.host_state.load_service_config", lambda: _compose({})
    )
    host = _ServiceHost()
    try:
        host._reconcile_once()
        assert not host._children
        assert not host._pending
        current = get_proc(orphan_id)
        assert current is not None and current.status in TERMINAL_PROC_STATUSES
    finally:
        host._stop_all_children()


def test_host_start_survives_a_oneshot_settle_error(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A proc-store error while settling oneshots must not stop the host."""
    import sase.service.host_lifecycle as host_lifecycle

    def _broken_settle() -> list[object]:
        raise RuntimeError("proc store unreadable")

    monkeypatch.setattr(
        "sase.service.host_lifecycle.settle_orphaned_oneshots", _broken_settle
    )

    host_lifecycle._settle_orphaned_oneshots_at_startup()

    assert "oneshot settle error: proc store unreadable" in capsys.readouterr().err


def test_proc_restart_request_replaces_child_and_completes_generation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A restart request is a confirmed transition to a new pid."""
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    cell: dict[str, ServiceConfigComposition] = {
        "composition": _compose({"theta": _layer_spec(_SLEEPER)})
    }
    with _service_host(monkeypatch, lambda: cell["composition"]) as host:
        host._reconcile_once()
        assert _wait_for(lambda: "theta" in host._children)
        old_pid = host._children["theta"].process.pid

        request_service_proc("theta", "restart", actor="pytest-restartgen")
        host._reconcile_desired(cell["composition"], read_service_state())

        assert "theta" in host._children
        new_pid = host._children["theta"].process.pid
        assert new_pid != old_pid
        assert not is_process_running(old_pid)

        stored = read_service_state().state.requests["theta"]
        assert stored.generation == 1
        assert stored.completed_generation == 1
        assert stored.outcome == "restarted"
        assert stored.pid == new_pid

        # A second tick consumes nothing new: the pid is stable.
        host._reconcile_desired(cell["composition"], read_service_state())
        assert host._children["theta"].process.pid == new_pid
        assert read_service_state().state.requests["theta"].completed_generation == 1


def test_proc_start_request_launches_stopped_proc_and_completes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A start request on a stopped proc launches it and completes."""
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    cell: dict[str, ServiceConfigComposition] = {
        "composition": _compose({"iota": _layer_spec(_SLEEPER)})
    }
    with _service_host(monkeypatch, lambda: cell["composition"]) as host:
        host._reconcile_once()
        assert _wait_for(lambda: "iota" in host._children)
        first_pid = host._children["iota"].process.pid

        record_service_stop("iota", actor="pytest-restartgen")
        host._reconcile_once()
        assert "iota" not in host._children
        assert not is_process_running(first_pid)

        request_service_proc("iota", "start", actor="pytest-restartgen")
        host._reconcile_desired(cell["composition"], read_service_state())

        assert _wait_for(lambda: "iota" in host._children)
        assert host._children["iota"].process.pid != first_pid

        stored = read_service_state().state.requests["iota"]
        assert stored.completed_generation == stored.generation
        assert stored.outcome == "started"
        assert stored.pid == host._children["iota"].process.pid


def test_proc_start_request_on_live_child_completes_already_running(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A start request for a live child launches nothing new."""
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    cell: dict[str, ServiceConfigComposition] = {
        "composition": _compose({"kappa": _layer_spec(_SLEEPER)})
    }
    with _service_host(monkeypatch, lambda: cell["composition"]) as host:
        host._reconcile_once()
        assert _wait_for(lambda: "kappa" in host._children)
        live_pid = host._children["kappa"].process.pid

        request_service_proc("kappa", "start", actor="pytest-restartgen")
        host._reconcile_desired(cell["composition"], read_service_state())

        assert host._children["kappa"].process.pid == live_pid

        stored = read_service_state().state.requests["kappa"]
        assert stored.completed_generation == stored.generation
        assert stored.outcome == "already_running"
        assert stored.pid == live_pid


def test_proc_request_for_disabled_proc_completes_not_desired(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A request for a disabled proc completes without launching."""
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    cell: dict[str, ServiceConfigComposition] = {
        "composition": _compose({"lambda": _layer_spec(_SLEEPER, enabled=False)})
    }
    with _service_host(monkeypatch, lambda: cell["composition"]) as host:
        request_service_proc("lambda", "start", actor="pytest-restartgen")
        host._reconcile_desired(cell["composition"], read_service_state())

        assert "lambda" not in host._children

        stored = read_service_state().state.requests["lambda"]
        assert stored.completed_generation == stored.generation
        assert stored.outcome == "not_desired"
        assert stored.error is not None and "disabled" in stored.error


def test_second_request_while_pending_is_consumed_exactly_once(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Two requests before one tick consume the latest generation once."""
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    cell: dict[str, ServiceConfigComposition] = {
        "composition": _compose({"mu": _layer_spec(_SLEEPER)})
    }
    with _service_host(monkeypatch, lambda: cell["composition"]) as host:
        host._reconcile_once()
        assert _wait_for(lambda: "mu" in host._children)
        old_pid = host._children["mu"].process.pid

        request_service_proc("mu", "restart", actor="pytest-restartgen")
        request_service_proc("mu", "restart", actor="pytest-restartgen")
        assert read_service_state().state.requests["mu"].generation == 2

        host._reconcile_desired(cell["composition"], read_service_state())

        assert "mu" in host._children
        new_pid = host._children["mu"].process.pid
        assert new_pid != old_pid

        stored = read_service_state().state.requests["mu"]
        assert stored.generation == 2
        assert stored.completed_generation == 2
        assert stored.outcome == "restarted"

        # The completed request is never consumed again.
        host._reconcile_desired(cell["composition"], read_service_state())
        assert host._children["mu"].process.pid == new_pid

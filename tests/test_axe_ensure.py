"""Tests for idempotent axe healing and watchdog installation."""

from __future__ import annotations

import subprocess
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest

from sase.axe.desired_state import read_desired_state, write_desired_state
from sase.axe.ensure import (
    DEFAULT_ENSURE_CADENCE_SECONDS,
    ensure_axe,
    install_ensure_timer,
    uninstall_ensure_timer,
)
from sase.axe.process import AxeStartResult, stop_axe_daemon_result
from sase.notifications.store import load_notifications


@pytest.fixture
def axe_state_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    state_dir = tmp_path / ".sase" / "axe"
    monkeypatch.setattr("sase.axe.state.AXE_STATE_DIR", state_dir)
    monkeypatch.setattr("sase.axe.state.JACK_STATE_DIR", state_dir / "lumberjacks")
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    yield state_dir


@pytest.mark.parametrize("marker_state", [None, "running"])
def test_ensure_starts_downed_axe_when_running_is_desired(
    axe_state_dir: Path,
    marker_state: str | None,
) -> None:
    if marker_state == "running":
        write_desired_state(
            "running",
            source="restart",
            timestamp="2026-07-19T12:00:00+00:00",
        )
    starts: list[dict[str, object]] = []
    notifications: list[tuple[float | None, int]] = []

    def start(**kwargs: object) -> AxeStartResult:
        starts.append(kwargs)
        return AxeStartResult(status="started", pid=4321, message="started")

    def notify(downtime: float | None, pid: int) -> str:
        notifications.append((downtime, pid))
        return "notification-id"

    result = ensure_axe(
        now_fn=lambda: 1_800_000_000.0,
        running_fn=lambda: False,
        start_fn=start,
        notify_fn=notify,
    )

    assert result.status == "healed"
    assert result.pid == 4321
    assert result.notification_id == "notification-id"
    assert starts == [
        {"desired_state_source": "axe ensure", "record_desired_state": True}
    ]
    assert notifications == [(result.downtime_seconds, 4321)]


def test_ensure_respects_explicit_stop(axe_state_dir: Path) -> None:
    write_desired_state("stopped", source="axe stop")
    starts = 0

    def start(**_kwargs: object) -> AxeStartResult:
        nonlocal starts
        starts += 1
        return AxeStartResult(status="started", pid=4321)

    result = ensure_axe(running_fn=lambda: False, start_fn=start)

    assert result.status == "stopped"
    assert starts == 0


def test_ensure_is_noop_when_orchestrator_is_running(axe_state_dir: Path) -> None:
    write_desired_state("running", source="restart")

    result = ensure_axe(
        running_fn=lambda: True,
        start_fn=lambda **_kwargs: pytest.fail("start should not be called"),
    )

    assert result.status == "healthy"


def test_runner_rate_limit_is_host_wide(axe_state_dir: Path) -> None:
    now = 1_800_000_000.0
    first = ensure_axe(
        rate_limit_seconds=DEFAULT_ENSURE_CADENCE_SECONDS,
        now_fn=lambda: now,
        running_fn=lambda: True,
    )
    second = ensure_axe(
        rate_limit_seconds=DEFAULT_ENSURE_CADENCE_SECONDS,
        now_fn=lambda: now + 1,
        running_fn=lambda: pytest.fail("rate-limited checks must not probe axe"),
    )

    assert first.status == "healthy"
    assert second.status == "rate_limited"
    assert (axe_state_dir / "ensure.json").exists()


def test_ensure_reports_start_failure(axe_state_dir: Path) -> None:
    result = ensure_axe(
        running_fn=lambda: False,
        start_fn=lambda **_kwargs: AxeStartResult(
            status="failed",
            message="lock stayed held",
        ),
    )

    assert result.status == "failed"
    assert result.succeeded is False
    assert result.message == "lock stayed held"


def test_explicit_stop_waits_for_in_progress_ensure(axe_state_dir: Path) -> None:
    """An in-flight heal cannot overwrite an operator's stopped marker."""
    write_desired_state("running", source="restart")
    start_entered = threading.Event()
    allow_start = threading.Event()
    stop_attempted = threading.Event()
    stop_finished = threading.Event()

    def start(**_kwargs: object) -> AxeStartResult:
        start_entered.set()
        assert allow_start.wait(timeout=2)
        # Match start_axe_daemon_result's desired-state write after the ensure
        # check. Without stop/ensure serialization this clobbers ``stopped``.
        write_desired_state("running", source="waiting agent runner")
        return AxeStartResult(status="started", pid=4321)

    ensure_thread = threading.Thread(
        target=lambda: ensure_axe(running_fn=lambda: False, start_fn=start)
    )

    def stop() -> None:
        stop_attempted.set()
        stop_axe_daemon_result(timeout=0, kill_timeout=0)
        stop_finished.set()

    stop_thread = threading.Thread(target=stop)
    ensure_thread.start()
    assert start_entered.wait(timeout=2)
    stop_thread.start()
    assert stop_attempted.wait(timeout=2)
    try:
        assert not stop_finished.wait(timeout=0.1)
    finally:
        allow_start.set()
        ensure_thread.join(timeout=2)
        stop_thread.join(timeout=2)

    assert not ensure_thread.is_alive()
    assert not stop_thread.is_alive()
    desired = read_desired_state()
    assert desired is not None
    assert desired.state == "stopped"
    assert desired.source == "stop"


def test_heal_writes_notification_inbox_entry(axe_state_dir: Path) -> None:
    write_desired_state(
        "running",
        source="restart",
        timestamp="2026-07-19T12:00:00+00:00",
    )

    result = ensure_axe(
        now_fn=lambda: 1_800_000_000.0,
        running_fn=lambda: False,
        start_fn=lambda **_kwargs: AxeStartResult(status="started", pid=7654),
    )

    notifications = load_notifications()
    assert result.status == "healed"
    assert result.notification_id is not None
    assert notifications[-1].id == result.notification_id
    assert notifications[-1].notes[0] == "Axe self-healed"
    assert "7654" in notifications[-1].notes[1]
    assert notifications[-1].tags == ["axe", "healed"]


def test_install_and_uninstall_ensure_timer(tmp_path: Path) -> None:
    unit_dir = tmp_path / "systemd" / "user"
    commands: list[list[str]] = []

    def run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, "", "")

    installed = install_ensure_timer(
        executable="/opt/sase/bin/sase",
        unit_dir=unit_dir,
        systemctl="/usr/bin/systemctl",
        run_fn=run,
    )

    assert installed.succeeded is True
    service = (unit_dir / "sase-axe-ensure.service").read_text()
    timer = (unit_dir / "sase-axe-ensure.timer").read_text()
    assert 'ExecStart="/opt/sase/bin/sase" axe ensure' in service
    assert f"OnUnitActiveSec={DEFAULT_ENSURE_CADENCE_SECONDS}s" in timer
    assert commands[-1][-3:] == ["enable", "--now", "sase-axe-ensure.timer"]

    removed = uninstall_ensure_timer(
        unit_dir=unit_dir,
        systemctl="/usr/bin/systemctl",
        run_fn=run,
    )

    assert removed.succeeded is True
    assert not (unit_dir / "sase-axe-ensure.service").exists()
    assert not (unit_dir / "sase-axe-ensure.timer").exists()

"""Tests for deriving the scheduler's desired state from the service host."""

from __future__ import annotations

from types import SimpleNamespace

from sase.axe._scheduler_desired_state import (
    scheduler_desired_running,
    scheduler_desired_state,
)

_GENERATED_AT = 1753185600.0


def _proc(
    *,
    name: str = "scheduler",
    desired: str = "running",
    enabled: bool = True,
    stop: SimpleNamespace | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        name=name,
        desired=desired,
        enablement=SimpleNamespace(enabled=enabled),
        stop=stop,
    )


def _snapshot(*procs: SimpleNamespace) -> SimpleNamespace:
    return SimpleNamespace(
        procs=list(procs),
        orphans=[],
        generated_at=_GENERATED_AT,
    )


def _patch_status(monkeypatch, snapshot: SimpleNamespace | None) -> None:
    if snapshot is None:

        def _raise() -> SimpleNamespace:
            raise RuntimeError("host state unavailable")

        monkeypatch.setattr("sase.service.control.persisted_or_current_status", _raise)
    else:
        monkeypatch.setattr(
            "sase.service.control.persisted_or_current_status",
            lambda: snapshot,
        )


def test_running_enabled_proc_is_desired_running(monkeypatch) -> None:
    _patch_status(monkeypatch, _snapshot(_proc()))

    record = scheduler_desired_state()

    assert record is not None
    assert (record.state, record.source) == ("running", "service host")
    assert record.timestamp == "2025-07-22T12:00:00+00:00"
    assert scheduler_desired_running() is True


def test_stop_marker_wins_over_desired_running(monkeypatch) -> None:
    stop = SimpleNamespace(stopped_at=_GENERATED_AT - 60.0, stopped_by="test")
    _patch_status(monkeypatch, _snapshot(_proc(stop=stop)))

    record = scheduler_desired_state()

    assert record is not None
    assert (record.state, record.source) == ("stopped", "service host")
    assert record.timestamp == "2025-07-22T11:59:00+00:00"
    assert scheduler_desired_running() is False


def test_desired_stopped_proc_is_not_wanted_running(monkeypatch) -> None:
    _patch_status(monkeypatch, _snapshot(_proc(desired="stopped")))

    record = scheduler_desired_state()

    assert record is not None
    assert record.state == "stopped"
    assert scheduler_desired_running() is False


def test_disabled_proc_is_not_wanted_running(monkeypatch) -> None:
    _patch_status(monkeypatch, _snapshot(_proc(enabled=False)))

    assert scheduler_desired_running() is False


def test_missing_proc_is_unknown(monkeypatch) -> None:
    _patch_status(monkeypatch, _snapshot(_proc(name="gateway")))

    assert scheduler_desired_state() is None
    assert scheduler_desired_running() is False


def test_unexpected_desired_value_is_unknown(monkeypatch) -> None:
    _patch_status(monkeypatch, _snapshot(_proc(desired="paused")))

    assert scheduler_desired_state() is None
    assert scheduler_desired_running() is False


def test_host_failure_is_unknown(monkeypatch) -> None:
    _patch_status(monkeypatch, None)

    assert scheduler_desired_state() is None
    assert scheduler_desired_running() is False

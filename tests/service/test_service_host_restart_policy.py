"""Restart policy: give-up parking, revive paths, and crash notifications."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from sase.service.config import ServiceConfigComposition
from sase.service.restart import ServiceRestartHistory
from sase.service.state import read_service_state, request_service_proc
from sase.service.status import read_service_status
from tests.service.service_host_scenario_helpers import (
    _CLEAN_EXIT,
    _FAIL_FAST,
    _SLEEPER,
    _SLOW_FAIL,
    _child_exited,
    _compose,
    _layer_spec,
    _service_host,
    _wait_for,
)


def test_on_failure_clean_exit_stays_down_with_single_launch(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """An on-failure proc that exits clean parks instead of relaunching."""
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    cell: dict[str, ServiceConfigComposition] = {
        "composition": _compose({"eta": _layer_spec(_CLEAN_EXIT)})
    }
    launches: list[str] = []
    with _service_host(monkeypatch, lambda: cell["composition"]) as host:
        real_launch = host._launch

        def _counting_launch(entry: object, **kwargs: object) -> None:
            launches.append(entry.name)  # type: ignore[attr-defined]
            return real_launch(entry, **kwargs)  # type: ignore[arg-type]

        monkeypatch.setattr(host, "_launch", _counting_launch)
        host._reconcile_once()
        assert _wait_for(lambda: _child_exited(host, "eta"), timeout=15)
        host._reconcile_once()

        assert "eta" not in host._children
        assert "eta" in host._given_up
        assert host._restart_decisions["eta"].action == "give_up"

        for _ in range(3):
            host._reconcile_once()
            assert "eta" not in host._children
            assert "eta" in host._given_up
        assert launches == ["eta"]


def test_never_policy_failure_stays_down_and_reports_exited(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A never proc that fails parks and reads as exited with its last exit."""
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    cell: dict[str, ServiceConfigComposition] = {
        "composition": _compose(
            {"theta_giveup": _layer_spec(_FAIL_FAST, restart="never")}
        )
    }
    with _service_host(monkeypatch, lambda: cell["composition"]) as host:
        host._reconcile_once()
        assert _wait_for(lambda: _child_exited(host, "theta_giveup"), timeout=15)
        host._reconcile_once()

        assert "theta_giveup" not in host._children
        assert "theta_giveup" in host._given_up
        assert host._restart_decisions["theta_giveup"].action == "give_up"

        for _ in range(3):
            host._reconcile_once()
            assert "theta_giveup" not in host._children
        assert "theta_giveup" in host._given_up

        snapshot = read_service_status()
        assert snapshot is not None
        row = next(p for p in snapshot.procs if p.name == "theta_giveup")
        assert row.state == "exited", row.summary
        assert row.last_exit is not None and row.last_exit.exit_code == 1


def test_spawn_failure_under_never_stays_down(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A never proc that cannot spawn parks instead of retrying."""
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    cell: dict[str, ServiceConfigComposition] = {
        "composition": _compose(
            {"badbin": _layer_spec(("no-such-sase-test-binary-xyz",), restart="never")}
        )
    }
    with _service_host(monkeypatch, lambda: cell["composition"]) as host:
        host._reconcile_once()

        assert "badbin" not in host._children
        assert "badbin" in host._given_up
        assert host._restart_decisions["badbin"].action == "give_up"

        for _ in range(3):
            host._reconcile_once()
            assert "badbin" not in host._children
        assert "badbin" in host._given_up


def test_explicit_start_revives_given_up_and_clears_record(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """An explicit start request relaunches a parked proc and clears it."""
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    cell: dict[str, ServiceConfigComposition] = {
        "composition": _compose(
            {"iota_giveup": _layer_spec(_FAIL_FAST, restart="never")}
        )
    }
    with _service_host(monkeypatch, lambda: cell["composition"]) as host:
        host._reconcile_once()
        assert _wait_for(lambda: _child_exited(host, "iota_giveup"), timeout=15)
        host._reconcile_once()
        assert "iota_giveup" in host._given_up

        request_service_proc("iota_giveup", "start", actor="pytest-giveup")
        host._reconcile_desired(cell["composition"], read_service_state())

        assert "iota_giveup" not in host._given_up
        assert "iota_giveup" in host._children

        stored = read_service_state().state.requests["iota_giveup"]
        assert stored.completed_generation == stored.generation
        assert stored.outcome == "started"


def test_signature_change_revives_given_up_without_request(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A new entry signature drops the parked record and relaunches."""
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    cell: dict[str, ServiceConfigComposition] = {
        "composition": _compose(
            {"kappa_giveup": _layer_spec(_FAIL_FAST, restart="never")}
        )
    }
    with _service_host(monkeypatch, lambda: cell["composition"]) as host:
        host._reconcile_once()
        assert _wait_for(lambda: _child_exited(host, "kappa_giveup"), timeout=15)
        host._reconcile_once()
        assert "kappa_giveup" in host._given_up

        cell["composition"] = _compose({"kappa_giveup": _layer_spec(_SLEEPER)})
        host._reconcile_once()

        assert "kappa_giveup" not in host._given_up
        assert _wait_for(lambda: "kappa_giveup" in host._children, timeout=15)


def test_crash_loop_notifies_once_per_episode_and_recovers(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Failures notify once; aged failures stay crash-loop; a healthy run clears."""
    import sase.service.notifications as service_notifications

    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    cell: dict[str, ServiceConfigComposition] = {
        "composition": _compose({"lambda_loop": _layer_spec(_SLOW_FAIL)})
    }
    seen: list[dict[str, object]] = []

    def _record(
        notification: object,
        *,
        plus_one_note: str | None = None,
        plus_one_timestamp: str | None = None,
        supersedes: str | None = None,
    ) -> object:
        seen.append(
            {
                "sender": notification.sender,  # type: ignore[attr-defined]
                "dedup_key": notification.dedup_key,  # type: ignore[attr-defined]
                "notes": list(notification.notes),  # type: ignore[attr-defined]
                "tags": list(notification.tags),  # type: ignore[attr-defined]
            }
        )

        class _Outcome:
            action = "created"

        return _Outcome()

    monkeypatch.setattr(service_notifications, "upsert_notification", _record)
    with _service_host(monkeypatch, lambda: cell["composition"]) as host:
        host._reconcile_once()
        for _ in range(3):
            assert _wait_for(lambda: _child_exited(host, "lambda_loop"), timeout=15)
            host._observe_exits(cell["composition"], read_service_state())
            pending = host._pending.get("lambda_loop")
            assert pending is not None
            # Jump past the backoff instead of sleeping through it.
            pending.restart_at = time.time() - 1
            host._reconcile_desired(cell["composition"], read_service_state())
            assert "lambda_loop" in host._children

        assert host._restart_decisions["lambda_loop"].crash_loop is True
        assert len(seen) == 1
        assert seen[0]["sender"] == "service"

        # Failures spaced past the backoff cap stay crash-loop without
        # notifying again: the sticky episode keeps alerting silently.
        running = host._children["lambda_loop"]
        now = time.time()
        running.restart_history = ServiceRestartHistory(
            started_at=running.restart_history.started_at,
            backoff_seconds=running.restart_history.backoff_seconds,
            consecutive_failures=3,
            recent_failures=(now - 200.0, now - 150.0, now - 130.0),
            alert_sent=True,
        )
        assert _wait_for(lambda: _child_exited(host, "lambda_loop"), timeout=15)
        host._observe_exits(cell["composition"], read_service_state())
        aged = host._restart_decisions["lambda_loop"]
        assert aged.action == "restart"
        assert aged.crash_loop is True
        assert aged.notify is False
        assert len(seen) == 1
        pending = host._pending.get("lambda_loop")
        assert pending is not None
        pending.restart_at = time.time() - 1
        host._reconcile_desired(cell["composition"], read_service_state())
        assert "lambda_loop" in host._children

        # A run that stays healthy past the threshold clears the episode.
        running = host._children["lambda_loop"]
        running.restart_history = ServiceRestartHistory(
            started_at=time.time() - 400.0,
            backoff_seconds=running.restart_history.backoff_seconds,
            consecutive_failures=running.restart_history.consecutive_failures,
            recent_failures=running.restart_history.recent_failures,
            alert_sent=True,
        )
        assert _wait_for(lambda: _child_exited(host, "lambda_loop"), timeout=15)
        host._observe_exits(cell["composition"], read_service_state())
        recovered = host._restart_decisions["lambda_loop"]
        assert recovered.action == "restart"
        assert recovered.crash_loop is False
        assert recovered.history.consecutive_failures == 1
        assert recovered.history.alert_sent is False
        assert len(seen) == 1


def test_give_up_notification_names_the_revive_command(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A parked desired proc upserts one service row with the revive command."""
    import sase.service.notifications as service_notifications

    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    cell: dict[str, ServiceConfigComposition] = {
        "composition": _compose({"nu_giveup": _layer_spec(_FAIL_FAST, restart="never")})
    }
    seen: list[dict[str, object]] = []

    def _record(
        notification: object,
        *,
        plus_one_note: str | None = None,
        plus_one_timestamp: str | None = None,
        supersedes: str | None = None,
    ) -> object:
        seen.append(
            {
                "sender": notification.sender,  # type: ignore[attr-defined]
                "dedup_key": notification.dedup_key,  # type: ignore[attr-defined]
                "notes": list(notification.notes),  # type: ignore[attr-defined]
                "tags": list(notification.tags),  # type: ignore[attr-defined]
            }
        )

        class _Outcome:
            action = "created"

        return _Outcome()

    monkeypatch.setattr(service_notifications, "upsert_notification", _record)
    with _service_host(monkeypatch, lambda: cell["composition"]) as host:
        host._reconcile_once()
        assert _wait_for(lambda: _child_exited(host, "nu_giveup"), timeout=15)
        host._reconcile_once()

        assert "nu_giveup" in host._given_up
        assert len(seen) == 1
        row = seen[0]
        assert row["sender"] == "service"
        assert "nu_giveup" in row["tags"]  # type: ignore[operator]
        notes = row["notes"]
        assert any("sase service proc start nu_giveup" in str(note) for note in notes)  # type: ignore[union-attr]
        assert any("Log:" in str(note) for note in notes)  # type: ignore[union-attr]

        # A second tick while parked notifies nothing new.
        host._reconcile_once()
        assert len(seen) == 1

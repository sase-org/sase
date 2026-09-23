"""Reconcile and config resilience: reloads, stop markers, backoff, outages."""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pytest

from sase.ace.hooks.processes import is_process_running
from sase.service.config import ServiceConfigComposition
from sase.service.state import (
    clear_service_stop,
    read_service_state,
    record_service_stop,
)
from sase.service.status import read_service_status
from tests.service.service_host_scenario_helpers import (
    _FAIL_FAST,
    _SLEEPER,
    _child_exited,
    _compose,
    _layer_spec,
    _service_host,
    _wait_for,
)


def test_host_config_reload_adds_stops_and_restarts_without_changing_the_host(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Reloads add, remove, and restart entries while the host pid is stable."""
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    cell: dict[str, ServiceConfigComposition] = {
        "composition": _compose({"alpha": _layer_spec(_SLEEPER)})
    }
    with _service_host(monkeypatch, lambda: cell["composition"]) as host:
        host._reconcile_once()
        assert _wait_for(lambda: "alpha" in host._children)
        alpha_pid = host._children["alpha"].process.pid
        assert read_service_state().state.host is not None
        assert read_service_state().state.host.pid == os.getpid()  # type: ignore[union-attr]

        # An added entry starts; the untouched entry keeps its pid.
        cell["composition"] = _compose(
            {
                "alpha": _layer_spec(_SLEEPER),
                "beta": _layer_spec(_SLEEPER),
            }
        )
        host._reconcile_once()
        assert _wait_for(lambda: "beta" in host._children)
        assert host._children["alpha"].process.pid == alpha_pid

        # A removed entry stops; a changed entry restarts with a new pid.
        changed = (
            sys.executable,
            "-c",
            "import time; time.sleep(31)",
        )
        cell["composition"] = _compose({"alpha": _layer_spec(changed)})
        host._reconcile_once()
        assert "beta" not in host._children
        assert "beta" not in host._pending
        assert host._children["alpha"].process.pid != alpha_pid
        assert not is_process_running(alpha_pid)

        # The host itself never changed across the reloads.
        assert read_service_state().state.host is not None
        assert read_service_state().state.host.pid == os.getpid()  # type: ignore[union-attr]


def test_stop_marker_racing_a_restart_settles_on_one_consistent_child(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A stop racing a restart never yields two children or a torn state file."""
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    cell: dict[str, ServiceConfigComposition] = {
        "composition": _compose({"gamma": _layer_spec(_SLEEPER)})
    }
    with _service_host(monkeypatch, lambda: cell["composition"]) as host:
        host._reconcile_once()
        assert _wait_for(lambda: "gamma" in host._children)
        first_pid = host._children["gamma"].process.pid

        # Stop marker plus changed entry in one reconcile: the stop wins and
        # no restart is scheduled behind it.
        record_service_stop("gamma", actor="pytest-host-scenarios")
        cell["composition"] = _compose(
            {
                "gamma": _layer_spec(
                    (sys.executable, "-c", "import time; time.sleep(31)")
                )
            }
        )
        host._reconcile_once()
        assert "gamma" not in host._children
        assert "gamma" not in host._pending
        assert not is_process_running(first_pid)

        # Clearing the stop relaunches exactly one child with the new command.
        clear_service_stop("gamma")
        host._reconcile_once()
        assert _wait_for(lambda: "gamma" in host._children)
        assert list(host._children) == ["gamma"]
        assert host._children["gamma"].process.pid != first_pid

        # A pending restart racing a stop is dropped, never launched.
        cell["composition"] = _compose({"delta": _layer_spec(_FAIL_FAST)})
        host._reconcile_once()
        assert _wait_for(lambda: _child_exited(host, "delta"))
        host._observe_exits(cell["composition"], read_service_state())
        assert "delta" in host._pending
        record_service_stop("delta", actor="pytest-host-scenarios")
        pending = host._pending["delta"]
        pending.restart_at = time.time() - 1
        host._reconcile_desired(cell["composition"], read_service_state())
        assert "delta" not in host._children
        assert "delta" not in host._pending

        snapshot = read_service_state()
        assert "delta" in snapshot.state.stops
        assert "gamma" not in snapshot.state.stops


def test_crashing_child_backs_off_while_the_host_stays_up(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A fail-fast child restarts with growing backoff; the host keeps serving."""
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    cell: dict[str, ServiceConfigComposition] = {
        "composition": _compose({"epsilon": _layer_spec(_FAIL_FAST)})
    }
    with _service_host(monkeypatch, lambda: cell["composition"]) as host:
        host._reconcile_once()
        delays: list[float] = []
        for _ in range(4):
            assert _wait_for(lambda: _child_exited(host, "epsilon"), timeout=15)
            host._observe_exits(cell["composition"], read_service_state())
            decision = host._restart_decisions["epsilon"]
            assert decision.action == "restart"
            assert decision.restart_at is not None
            delays.append(decision.delay_seconds)
            pending = host._pending.get("epsilon")
            assert pending is not None
            # Jump past the backoff instead of sleeping through it.
            pending.restart_at = time.time() - 1
            host._reconcile_desired(cell["composition"], read_service_state())
            assert "epsilon" in host._children

        assert delays == sorted(delays) and len(set(delays)) > 1
        final = host._restart_decisions["epsilon"]
        assert final.crash_loop is True
        assert final.history.consecutive_failures == 4
        assert host._running is True

        # Settle the relaunched child without forcing another restart, so the
        # crasher is deterministically parked in backoff below.
        assert _wait_for(lambda: _child_exited(host, "epsilon"), timeout=15)
        host._observe_exits(cell["composition"], read_service_state())
        assert "epsilon" in host._pending

        # The looping host still serves other entries: a healthy proc starts
        # while the crasher waits out its backoff.
        cell["composition"] = _compose(
            {
                "epsilon": _layer_spec(_FAIL_FAST),
                "zeta": _layer_spec(_SLEEPER),
            }
        )
        host._reconcile_once()
        assert _wait_for(lambda: "zeta" in host._children)
        assert "epsilon" in host._pending


def test_config_outage_keeps_last_good_and_publishes_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A raising composition leaves children running and publishes the error."""
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    cell: dict[str, ServiceConfigComposition] = {
        "composition": _compose({"alpha": _layer_spec(_SLEEPER)})
    }
    with _service_host(monkeypatch, lambda: cell["composition"]) as host:
        host._reconcile_once()
        assert _wait_for(lambda: "alpha" in host._children)
        alpha_pid = host._children["alpha"].process.pid
        baseline = read_service_status()
        assert baseline is not None
        assert baseline.host.error is None
        assert read_service_state().state.host is not None
        assert read_service_state().state.host.error is None  # type: ignore[union-attr]

        def _raise() -> ServiceConfigComposition:
            raise RuntimeError("boom config")

        monkeypatch.setattr("sase.service.host_state.load_service_config", _raise)
        host._reconcile_once()

        assert "alpha" in host._children
        assert host._children["alpha"].process.pid == alpha_pid
        assert is_process_running(alpha_pid)
        assert host._config_error is not None and "boom config" in host._config_error
        host_record = read_service_state().state.host
        assert host_record is not None
        assert host_record.error is not None and "boom config" in host_record.error
        snapshot = read_service_status()
        assert snapshot is not None
        assert snapshot.host.error is not None and "boom config" in snapshot.host.error
        assert snapshot.generated_at >= baseline.generated_at

        monkeypatch.setattr(
            "sase.service.host_state.load_service_config", lambda: cell["composition"]
        )
        host._reconcile_once()
        assert host._config_error is None
        assert host._last_good_config is not None
        recovered = read_service_state().state.host
        assert recovered is not None and recovered.error is None
        recovered_snapshot = read_service_status()
        assert recovered_snapshot is not None and recovered_snapshot.host.error is None
        assert host._children["alpha"].process.pid == alpha_pid


def test_exit_during_config_outage_settles_and_restarts(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A child that exits while the config raises is settled per its entry."""
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    cell: dict[str, ServiceConfigComposition] = {
        "composition": _compose({"epsilon": _layer_spec(_FAIL_FAST)})
    }
    with _service_host(monkeypatch, lambda: cell["composition"]) as host:
        host._reconcile_once()
        assert _wait_for(lambda: _child_exited(host, "epsilon"), timeout=15)

        def _raise() -> ServiceConfigComposition:
            raise RuntimeError("boom config during exit")

        monkeypatch.setattr("sase.service.host_state.load_service_config", _raise)
        host._reconcile_once()

        assert "epsilon" not in host._children
        assert "epsilon" in host._pending
        assert "epsilon" in host._last_exits
        assert host._pending["epsilon"].entry.name == "epsilon"
        assert host._config_error is not None
        assert "boom config during exit" in host._config_error
        snapshot = read_service_status()
        assert snapshot is not None
        assert snapshot.host.error is not None
        assert "boom config during exit" in snapshot.host.error

        host._pending["epsilon"].restart_at = time.time() - 1
        host._reconcile_once()
        assert _wait_for(lambda: "epsilon" in host._children, timeout=15)


def test_bad_config_at_startup_writes_degraded_snapshot(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """No last-good at startup still heartbeats and writes a fresh snapshot."""
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))

    def _raise() -> ServiceConfigComposition:
        raise RuntimeError("startup boom")

    with _service_host(monkeypatch, _raise) as host:
        assert not host._children
        host._reconcile_once()

        assert host._last_good_config is None
        assert host._config_error is not None
        assert "startup boom" in host._config_error
        host_record = read_service_state().state.host
        assert host_record is not None
        assert host_record.error is not None and "startup boom" in host_record.error
        snapshot = read_service_status()
        assert snapshot is not None
        assert snapshot.procs == ()
        assert snapshot.host.error is not None
        assert "startup boom" in snapshot.host.error

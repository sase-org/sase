"""Host shutdown snapshot reports the host as stopped."""

from __future__ import annotations

import os
import signal
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from sase.service.host import _ServiceHost
from sase.service.host_lifecycle import run_host
from sase.service.host_reporting import write_current_host_status
from sase.service.state import read_service_state
from sase.service.status import read_service_status
from tests.service.service_host_scenario_helpers import (
    _compose,
    _layer_spec,
    _preserved_host_globals,
    _wait_for,
)

_SLEEPER = (
    __import__("sys").executable,
    "-c",
    "import time; time.sleep(30)",
)


def _fake_host(*, unit: str | None = "sase.service") -> SimpleNamespace:
    return SimpleNamespace(
        _boot_id="boot-test",
        _started_at=time.time() - 10.0,
        _unit=unit,
        _children={},
        _pending={},
        _last_exits={},
        _restart_decisions={},
        _given_up={},
        _last_good_config=_compose({"worker": _layer_spec(_SLEEPER, stop_timeout=0.5)}),
        _config_error=None,
    )


def test_write_current_host_status_host_exited_reports_stopped(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("SASE_SERVICE_ENV", raising=False)
    host = _fake_host(unit="sase.service")

    write_current_host_status(host, host_exited=True)

    snapshot = read_service_status()
    assert snapshot is not None
    assert snapshot.host.state == "stopped"
    assert snapshot.host.platform_unit == "sase.service"
    worker = next(proc for proc in snapshot.procs if proc.name == "worker")
    assert worker.desired == "running"


def test_run_host_final_snapshot_reports_stopped(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("SASE_SERVICE_ENV", raising=False)
    monkeypatch.setattr(
        "sase.service.host_state.load_service_config", lambda: _compose({})
    )
    host = _ServiceHost()

    def _driver() -> None:
        try:
            assert _wait_for(
                lambda: read_service_state().state.host is not None,
                timeout=10,
            )
        finally:
            os.kill(os.getpid(), signal.SIGTERM)

    with _preserved_host_globals():
        driver = threading.Thread(target=_driver, daemon=True)
        driver.start()
        assert run_host(host, 30.0) == 0
        driver.join(timeout=15)
        assert not driver.is_alive()

    snapshot = read_service_status()
    assert snapshot is not None
    assert snapshot.host.state == "stopped"

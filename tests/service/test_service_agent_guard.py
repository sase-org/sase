"""Agents never start a service host that outlives them.

Regression coverage for the Nov 16 orphan: an agent-launched TUI under a
throwaway ``HOME`` auto-started a detached ``sase-service-*`` scope that no
sweep or status could see.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from sase.ace.tui.actions.axe import AxeMixin
from sase.main.service_handler import _handle_service_command
from sase.service.agent_guard import (
    SERVICE_AGENT_BYPASS_ENV,
    service_agent_guard,
    service_auto_start_notice,
)
from sase.service.control import restart_service_host, start_service_host
from sase.service.platform_models import SERVICE_LIFECYCLE_TEST_OVERRIDE_ENV
from sase.service.state import ServiceHostRecord, record_service_host


@pytest.mark.parametrize("marker", ["SASE_AGENT", "SASE_AGENT_NAME", "SASE_MONITOR_ID"])
def test_any_agent_marker_refuses_without_a_bypass(marker: str) -> None:
    guard = service_agent_guard({marker: "x"})

    assert guard.refused is True
    assert guard.marker == marker


def test_no_marker_and_blank_bypass_reasons() -> None:
    assert service_agent_guard({}).refused is False
    blank = service_agent_guard({"SASE_AGENT": "1", SERVICE_AGENT_BYPASS_ENV: "  "})
    assert blank.refused is True
    bypassed = service_agent_guard(
        {"SASE_AGENT": "1", SERVICE_AGENT_BYPASS_ENV: "measure TUI"}
    )
    assert bypassed.refused is False
    assert bypassed.bypass_reason == "measure TUI"


def test_auto_start_notice_only_inside_an_unbypassed_agent() -> None:
    assert service_auto_start_notice({}) is None
    assert (
        service_auto_start_notice({"SASE_AGENT": "1", SERVICE_AGENT_BYPASS_ENV: "r"})
        is None
    )
    notice = service_auto_start_notice({"SASE_AGENT": "1"})
    assert notice is not None
    assert "\n" not in notice
    assert "--no-service" in notice


def _stub_native(monkeypatch: pytest.MonkeyPatch, result: object = None) -> list[str]:
    actions: list[str] = []

    def _native(action: str) -> object:
        actions.append(action)
        return result

    monkeypatch.setattr("sase.service.control._native_lifecycle_action", _native)
    return actions


def _forbid_popen(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fail_popen(argv: object, **kwargs: object) -> object:
        raise AssertionError("no detached host may be spawned inside an agent")

    monkeypatch.setattr("sase.service.control.subprocess.Popen", _fail_popen)


def test_detached_start_refuses_inside_an_agent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("SASE_AGENT", "1")
    monkeypatch.setenv(SERVICE_LIFECYCLE_TEST_OVERRIDE_ENV, "1")
    _stub_native(monkeypatch)
    _forbid_popen(monkeypatch)

    result = start_service_host(wait_seconds=0.1)

    assert result.ok is False
    assert result.changed is False
    assert SERVICE_AGENT_BYPASS_ENV in result.message
    assert "sase service stop" in result.message
    assert "systemctl --user stop" in result.message


def test_bypass_reaches_the_detached_spawn_and_names_the_stop(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("SASE_AGENT", "1")
    monkeypatch.setenv(SERVICE_AGENT_BYPASS_ENV, "measure the TUI")
    monkeypatch.setenv(SERVICE_LIFECYCLE_TEST_OVERRIDE_ENV, "1")
    _stub_native(monkeypatch)
    spawned: list[list[str]] = []

    def _fake_popen(argv: object, **kwargs: object) -> object:
        spawned.append([str(part) for part in argv])  # type: ignore[union-attr]
        now = time.time()
        record_service_host(
            ServiceHostRecord(
                pid=os.getpid(), started_at=now, heartbeat_at=now, mode="foreground"
            )
        )
        return SimpleNamespace(pid=os.getpid())

    monkeypatch.setattr("sase.service.control.subprocess.Popen", _fake_popen)

    result = start_service_host(wait_seconds=10)

    assert result.ok is True
    assert len(spawned) == 1
    assert "measure the TUI" in result.message
    assert "sase service stop" in result.message


def test_native_unit_start_keeps_its_single_home_behavior_for_callers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Library callers still reach an installed native unit inside an agent."""
    monkeypatch.setenv("SASE_AGENT", "1")
    native = SimpleNamespace(ok=True, changed=True, message="started sase.service")
    actions = _stub_native(monkeypatch, native)
    _forbid_popen(monkeypatch)

    assert start_service_host(wait_seconds=0.1) is native
    assert actions == ["start"]


def test_detached_restart_refuses_before_stopping_the_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_AGENT", "1")
    _stub_native(monkeypatch)

    def _no_stop(**_kwargs: object) -> object:
        raise AssertionError("an agent restart must not stop the host first")

    monkeypatch.setattr("sase.service.control.stop_service_host", _no_stop)

    result = restart_service_host()

    assert result.ok is False
    assert SERVICE_AGENT_BYPASS_ENV in result.message


def test_cli_start_refuses_inside_an_agent_even_with_a_native_unit(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("SASE_AGENT_NAME", "some-agent")
    actions = _stub_native(
        monkeypatch, SimpleNamespace(ok=True, changed=True, message="x")
    )

    code = _handle_service_command(
        argparse.Namespace(service_subcommand="start", json=True)
    )

    assert code == 1
    assert actions == []
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert "SASE_AGENT_NAME" in payload["message"]


def test_cli_start_with_bypass_reaches_the_native_unit(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("SASE_AGENT", "1")
    monkeypatch.setenv(SERVICE_AGENT_BYPASS_ENV, "rollout restart")
    native = SimpleNamespace(ok=True, changed=True, message="started", pid=None)
    actions = _stub_native(monkeypatch, native)

    code = _handle_service_command(
        argparse.Namespace(service_subcommand="start", json=False)
    )

    assert code == 0
    assert actions == ["start"]
    assert "started" in capsys.readouterr().out


class _StartupHarness(AxeMixin):
    """The TUI startup init, with the service host calls observed."""

    def __init__(self) -> None:
        self.axe_running = False
        self._restart_axe = False
        self._auto_start_axe = True
        self._axe_services_visited = False
        self.refreshes = 0
        self.notifies: list[tuple[str, str]] = []

    async def _load_axe_status_async(self, **_kwargs: object) -> None:  # type: ignore[override]
        return

    def _schedule_axe_async_refresh(self, **_kwargs: object) -> None:  # type: ignore[override]
        self.refreshes += 1

    def notify(self, message: str, severity: str = "information") -> None:
        self.notifies.append((message, severity))


@pytest.mark.asyncio
async def test_tui_auto_start_behaves_like_no_service_inside_an_agent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_AGENT", "1")
    starts: list[str] = []
    monkeypatch.setattr(
        "sase.service.control.start_service_host",
        lambda: starts.append("start"),
    )
    app = _StartupHarness()

    await app._run_axe_startup_init()
    await app._run_axe_startup_init()

    assert starts == []
    assert app._auto_start_axe is False
    assert len(app.notifies) == 1
    message, severity = app.notifies[0]
    assert severity == "warning"
    assert "SASE_AGENT" in message


@pytest.mark.asyncio
async def test_tui_auto_start_with_bypass_still_starts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_AGENT", "1")
    monkeypatch.setenv(SERVICE_AGENT_BYPASS_ENV, "drive the TUI with a host")
    starts: list[str] = []
    monkeypatch.setattr(
        "sase.service.control.start_service_host",
        lambda: starts.append("start"),
    )
    app = _StartupHarness()

    await app._run_axe_startup_init()

    assert starts == ["start"]
    assert app.notifies == []


def test_tui_start_key_refuses_inside_an_agent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SASE_MONITOR_ID", "m-1")
    notifies: list[tuple[str, str]] = []
    host = SimpleNamespace(
        _axe_worker=None,
        notify=lambda message, severity="information": notifies.append(
            (message, severity)
        ),
        _set_axe_starting=lambda _value: pytest.fail("must not enter starting"),
        run_worker=lambda *_a, **_k: pytest.fail("must not start a worker"),
    )

    AxeMixin._start_service_host(host)  # type: ignore[arg-type]

    assert len(notifies) == 1
    assert notifies[0][1] == "error"
    assert SERVICE_AGENT_BYPASS_ENV in notifies[0][0]

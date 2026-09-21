"""Guard detached ``sase service run`` spawns under pytest.

Regression coverage for the leaked-host fix: ``start_service_host`` must
refuse the detached ``Popen`` fallback while running under pytest unless
the isolated lifecycle override is set, and ``run_service_host`` must
refuse to run a real host from a test process.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from sase.service.control import start_service_host
from sase.service.host import run_service_host
from sase.service.platform_models import (
    SERVICE_LIFECYCLE_TEST_BLOCK_MESSAGE,
    SERVICE_LIFECYCLE_TEST_OVERRIDE_ENV,
)
from sase.service.state import ServiceHostRecord, record_service_host


def _stub_native_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "sase.service.control._native_lifecycle_action", lambda _action: None
    )


def test_start_service_host_refuses_detached_spawn_under_pytest(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Under pytest without the override, no host is spawned."""
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    monkeypatch.delenv(SERVICE_LIFECYCLE_TEST_OVERRIDE_ENV, raising=False)
    _stub_native_none(monkeypatch)

    def _fail_popen(argv: object, **kwargs: object) -> object:
        raise AssertionError("subprocess.Popen must not be called under pytest")

    monkeypatch.setattr("sase.service.control.subprocess.Popen", _fail_popen)

    result = start_service_host(wait_seconds=0.1)

    assert result.ok is False
    assert result.changed is False
    assert result.message == SERVICE_LIFECYCLE_TEST_BLOCK_MESSAGE
    assert result.pid is None


def test_start_service_host_override_reaches_detached_spawn(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """With the override, the detached fallback is reached (stubbed)."""
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    monkeypatch.setenv(SERVICE_LIFECYCLE_TEST_OVERRIDE_ENV, "1")
    _stub_native_none(monkeypatch)
    spawned: list[list[str]] = []

    def _fake_popen(argv: object, **kwargs: object) -> object:
        spawned.append([str(part) for part in argv])  # type: ignore[union-attr]
        now = time.time()
        record_service_host(
            ServiceHostRecord(
                pid=os.getpid(),
                started_at=now,
                heartbeat_at=now,
                mode="foreground",
            )
        )

        class _FakeChild:
            pid = os.getpid()

        return _FakeChild()

    monkeypatch.setattr("sase.service.control.subprocess.Popen", _fake_popen)

    result = start_service_host(wait_seconds=10)

    assert result.ok is True
    assert len(spawned) == 1
    assert spawned[0][-2:] == ["service", "run"]


def test_run_service_host_refuses_under_pytest(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``sase service run`` refuses to run a real host from a test process."""
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    monkeypatch.delenv(SERVICE_LIFECYCLE_TEST_OVERRIDE_ENV, raising=False)

    def _fail_host() -> object:
        raise AssertionError("_ServiceHost must not run under pytest")

    monkeypatch.setattr("sase.service.host._ServiceHost", _fail_host)

    code = run_service_host()

    assert code == 125
    captured = capsys.readouterr()
    assert SERVICE_LIFECYCLE_TEST_BLOCK_MESSAGE in captured.err

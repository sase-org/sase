"""ACE startup feature-flag cleanup scheduling tests."""

from __future__ import annotations

from typing import Any

import pytest

from sase.ace.tui.actions import _startup_feature_flags as startup_flags
from sase.ace.tui.actions._startup_feature_flags import (
    StartupFeatureFlagCleanupMixin,
)
from sase.feature_flags.snapshot import FeatureFlagCleanupNotice


class _App(StartupFeatureFlagCleanupMixin):
    def __init__(self) -> None:
        self._feature_flag_cleanup_notice_scheduled = False
        self.notices: list[dict[str, Any]] = []

    def notify(self, message: str, **kwargs: Any) -> None:
        self.notices.append({"message": message, **kwargs})


def test_feature_flag_cleanup_startup_schedule_is_thin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _App()
    scheduled: list[tuple[str, str]] = []
    cleanup_calls = 0

    def fail_if_run() -> None:
        nonlocal cleanup_calls
        cleanup_calls += 1

    def spawn(owner: object, coro: object, *, name: str, registry_attr: str) -> object:
        close = getattr(coro, "close", None)
        if callable(close):
            close()
        scheduled.append((name, registry_attr))
        return object()

    monkeypatch.setattr(startup_flags, "has_pending_feature_flag_cleanup", lambda: True)
    monkeypatch.setattr(startup_flags, "run_pending_feature_flag_cleanup", fail_if_run)
    monkeypatch.setattr(startup_flags, "spawn_pump_free_task", spawn)

    app._schedule_feature_flag_cleanup_notice()
    app._schedule_feature_flag_cleanup_notice()

    assert app._feature_flag_cleanup_notice_scheduled is True
    assert scheduled == [("feature-flag-cleanup", "_feature_flag_cleanup_async_tasks")]
    assert cleanup_calls == 0
    assert app.notices == []


@pytest.mark.asyncio
async def test_feature_flag_cleanup_worker_delivers_notice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _App()
    notice = FeatureFlagCleanupNotice(
        title="Feature flags cleaned up",
        message="[bold green]AUTO-CLEANED[/]\nRemoved 1 unregistered saved flag: old",
        plain_message="AUTO-CLEANED\nRemoved 1 unregistered saved flag: old",
        severity="information",
        timeout=15.0,
    )
    monkeypatch.setattr(
        startup_flags,
        "run_pending_feature_flag_cleanup",
        lambda: notice,
    )

    await app._run_feature_flag_cleanup_notice()

    assert app.notices == [
        {
            "message": notice.message,
            "title": notice.title,
            "severity": notice.severity,
            "timeout": notice.timeout,
        }
    ]


def test_feature_flag_cleanup_scheduling_failure_toasts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _App()
    monkeypatch.setattr(startup_flags, "has_pending_feature_flag_cleanup", lambda: True)
    monkeypatch.setattr(
        startup_flags,
        "spawn_pump_free_task",
        lambda *_args, **_kwargs: None,
    )

    app._schedule_feature_flag_cleanup_notice()

    assert app._feature_flag_cleanup_notice_scheduled is False
    assert app.notices[0]["title"] == "Feature flag cleanup failed"
    assert app.notices[0]["severity"] == "warning"
    assert "Will retry on next startup" in app.notices[0]["message"]

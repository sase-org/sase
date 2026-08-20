"""Tests for the Open Launch Control notification action."""

from __future__ import annotations

from sase.ace.tui.actions.agents._notification_handlers import (
    handle_open_launch_control,
)
from sase.notifications.models import Notification


class _FakeApp:
    def __init__(self) -> None:
        self.opened = 0
        self.notifications: list[tuple[str, str]] = []

    def action_open_models_panel(self) -> None:
        self.opened += 1

    def notify(self, message: str, *, severity: str = "information") -> None:
        self.notifications.append((message, severity))


def _notification() -> Notification:
    return Notification(
        id="usage-1",
        timestamp="2026-08-20T12:00:00-04:00",
        sender="llm.usage_limit",
        action="OpenLaunchControl",
        action_data={"provider": "claude"},
    )


def test_handle_open_launch_control_uses_models_panel_action() -> None:
    app = _FakeApp()
    assert handle_open_launch_control(app, _notification()) is True
    assert app.opened == 1
    assert app.notifications == []


def test_handle_open_launch_control_warns_when_panel_is_unavailable() -> None:
    class _BareApp:
        def __init__(self) -> None:
            self.notifications: list[tuple[str, str]] = []

        def notify(self, message: str, *, severity: str = "information") -> None:
            self.notifications.append((message, severity))

    app = _BareApp()
    assert handle_open_launch_control(app, _notification()) is False
    assert app.notifications == [("Launch Control is unavailable", "warning")]

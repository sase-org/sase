"""TUI confirm/cancel coverage for the ExpireWaiters notification action."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock

from sase.ace.tui.actions.agents._notification_expire_waiters import (
    handle_expire_waiters,
)
from sase.ace.tui.modals.confirm_action_modal import ConfirmActionModal
from sase.ace.tui.modals.confirm_dialog import ConfirmKind
from sase.ace.tui.modals.notification_modal_constants import (
    ACTION_BADGES,
    ACTION_ICONS,
)
from sase.agent.expire_blocked_waiters import (
    ExpireBlockedWaitersResult,
    WaiterExpireResult,
)
from sase.notifications import Notification
from sase.scripts._chop_wait_checks_root_notice import EXPIRE_WAITERS_ACTION


class _ExpireApp:
    def __init__(self) -> None:
        self.screen: object | None = None
        self.callback: Any = None
        self.notifies: list[tuple[str, str]] = []
        self.agent_refreshes: list[str] = []
        self.notification_refreshes = 0

    def push_screen(self, screen: object, callback: Any) -> None:
        self.screen = screen
        self.callback = callback

    def notify(self, message: str, severity: str = "information") -> None:
        self.notifies.append((message, severity))

    def _schedule_agents_async_refresh(self, source: str = "") -> None:
        self.agent_refreshes.append(source)

    def _refresh_notification_count(self) -> None:
        self.notification_refreshes += 1


def _notice(*, waiter_count: int = 2) -> Notification:
    waiters = [
        {
            "artifact_dir": f"/tmp/waiter-{index}",
            "name": f"waiter-{index}",
            "project": "proj",
        }
        for index in range(waiter_count)
    ]
    return Notification(
        id="n-expire",
        timestamp="2026-11-20T12:00:00+00:00",
        sender="wait_checks",
        action=EXPIRE_WAITERS_ACTION,
        action_data={
            "blocker_artifact_dir": "/tmp/blocker",
            "blocker_outcome": "failed",
            "blocker_dependency": "foo",
            "blocker_name": "foo",
            "waiter_count": str(waiter_count),
            "waiters": json.dumps(waiters, separators=(",", ":")),
        },
    )


def test_expire_waiters_badge_and_icon() -> None:
    assert ACTION_BADGES[EXPIRE_WAITERS_ACTION] == "[expire]"
    assert ACTION_ICONS[EXPIRE_WAITERS_ACTION] == "⌛"


def test_handle_expire_waiters_pushes_danger_confirm_named_with_count() -> None:
    app = _ExpireApp()
    assert handle_expire_waiters(app, _notice(waiter_count=2)) is True
    modal = app.screen
    assert isinstance(modal, ConfirmActionModal)
    assert modal._kind is ConfirmKind.DANGER
    assert modal._default == "cancel"
    assert modal._confirm_label == "Expire"
    assert modal._cancel_label == "Keep waiting"
    assert modal._title == "Expire blocked waiters"
    assert "Expire 2 waiters blocked on foo?" in modal._message
    assert "without launching" in modal._message


def test_confirmation_does_not_read_waiter_sidecar(monkeypatch: Any) -> None:
    app = _ExpireApp()
    notice = _notice(waiter_count=100)
    notice.action_data["waiters"] = "sase-notification-blob:v1:missing:20000"
    resolve = MagicMock(side_effect=AssertionError("disk read on UI thread"))
    monkeypatch.setattr(
        "sase.scripts._chop_wait_checks_root_notice.resolve_notification_value", resolve
    )

    assert handle_expire_waiters(app, notice) is True
    assert isinstance(app.screen, ConfirmActionModal)
    assert "Expire 100 waiters" in app.screen._message
    resolve.assert_not_called()


def test_confirming_expire_runs_operation_and_refreshes(
    monkeypatch: Any,
) -> None:
    app = _ExpireApp()
    notice = _notice()
    called: list[str] = []
    result = ExpireBlockedWaitersResult(
        results=(
            WaiterExpireResult(
                artifact_dir="/tmp/waiter-0",
                name="waiter-0",
                status="expired",
                message="cleaned up",
            ),
        ),
        notice_settled=True,
    )
    monkeypatch.setattr(
        "sase.ace.tui.actions.agents._notification_expire_waiters.expire_blocked_waiters",
        lambda notification: called.append(notification.id) or result,
    )

    handle_expire_waiters(app, notice)
    assert callable(app.callback)
    app.callback(True)

    assert called == [notice.id]
    assert app.notifies == [("Expired 1 waiter(s); notice settled", "information")]
    assert app.agent_refreshes == ["expire-blocked-waiters"]
    assert app.notification_refreshes == 1


def test_cancelling_expire_confirmation_does_nothing(monkeypatch: Any) -> None:
    app = _ExpireApp()
    expire = MagicMock()
    monkeypatch.setattr(
        "sase.ace.tui.actions.agents._notification_expire_waiters.expire_blocked_waiters",
        expire,
    )

    handle_expire_waiters(app, _notice())
    assert callable(app.callback)
    app.callback(False)
    app.callback(None)

    expire.assert_not_called()
    assert app.notifies == []
    assert app.agent_refreshes == []
    assert app.notification_refreshes == 0

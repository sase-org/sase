"""Phase 4 end-to-end behavior tests for Agents-tab completion dismissal.

These tests close the gaps the design called out: polling never silently
dismisses before user activity, the indicator refreshes only after a
real bulk-dismiss writes back, completion toasts still fire while the
user is on another tab, and unrelated priority notifications survive
the bulk action. The integration test exercises the real Rust-backed
notification store through ``temp_notifications_dir`` so the JumpToAgent
and ViewErrorReport completion shapes are confirmed end-to-end without
mocking the store API.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from sase.ace.tui.actions.agents._notifications import AgentNotificationMixin
from sase.notifications import (
    dismiss_agent_completion_notifications,
    load_notifications,
)
from sase.notifications.models import Notification
from sase.notifications.store import append_notification, mark_muted, mark_read


@pytest.fixture()
def temp_notifications_dir(tmp_path: Path) -> Iterator[Path]:
    """Local copy of the notification_store fixture so this file is self-contained."""
    notifications_dir = str(tmp_path / "notifications")
    notifications_file = str(tmp_path / "notifications" / "notifications.jsonl")
    with (
        patch("sase.notifications.store.NOTIFICATIONS_DIR", notifications_dir),
        patch("sase.notifications.store.NOTIFICATIONS_FILE", notifications_file),
    ):
        yield tmp_path


def _completion(
    *,
    action: str = "JumpToAgent",
    cl_name: str = "demo",
    n_id: str = "n1",
    raw_suffix: str = "20260507090000",
    read: bool = False,
    muted: bool = False,
) -> Notification:
    return Notification(
        id=n_id,
        timestamp="2026-05-11T12:00:00-04:00",
        sender="user-agent",
        action=action,
        action_data={"cl_name": cl_name, "raw_suffix": raw_suffix},
        read=read,
        muted=muted,
    )


class _PollApp(AgentNotificationMixin):
    """Stand-in app that mirrors the AceApp attributes ``_poll_agent_completions`` reads."""

    def __init__(self) -> None:
        self._last_unread_ids: set[str] = set()
        self._agents: list = []
        self._agent_status_overrides: dict = {}
        self._agent_pre_question_status: dict = {}
        self._agent_completion_dismiss_inflight = False
        self._agent_completion_ack_latch = False
        self._indicator = MagicMock()
        self.bell_rings = 0
        self.toast_calls: list[tuple[tuple, dict]] = []

    def _ring_tmux_bell(self) -> None:  # type: ignore[override]
        self.bell_rings += 1

    def notify(self, *args: object, **kwargs: object) -> None:
        self.toast_calls.append((args, kwargs))

    def query_one(self, _selector: object, _type: object = None) -> object:
        return self._indicator


@pytest.mark.asyncio
async def test_poll_observing_completion_does_not_silently_dismiss(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Polling must arm the latch and toast — never invoke the bulk dismiss itself.

    The dismissal trigger lives in the Agents-tab activity / entry helpers;
    the polling tick has no business writing to the notification store.
    """
    completion = _completion()
    snapshot = SimpleNamespace(
        notifications=[completion],
        expired_ids=[],
        counts=SimpleNamespace(priority=0, errors=0, rest=1, muted=0),
    )

    dismiss = MagicMock(return_value=99)
    monkeypatch.setattr(
        "sase.notifications.read_notification_snapshot", lambda *a, **k: snapshot
    )
    monkeypatch.setattr(
        "sase.notifications.dismiss_agent_completion_notifications", dismiss
    )

    app = _PollApp()
    await app._poll_agent_completions()

    dismiss.assert_not_called()
    assert app._agent_completion_ack_latch is True
    assert app.bell_rings == 1
    assert len(app.toast_calls) == 1


@pytest.mark.asyncio
async def test_poll_toasts_completion_while_user_is_on_other_tab(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A completion arriving while not on Agents must still toast + ring the bell.

    The new acknowledgement behavior should not suppress the initial
    notification when the user is elsewhere in the TUI.
    """
    completion = _completion(action="ViewErrorReport", n_id="err-1")
    snapshot = SimpleNamespace(
        notifications=[completion],
        expired_ids=[],
        counts=SimpleNamespace(priority=0, errors=1, rest=0, muted=0),
    )

    dismiss = MagicMock(return_value=0)
    monkeypatch.setattr(
        "sase.notifications.read_notification_snapshot", lambda *a, **k: snapshot
    )
    monkeypatch.setattr(
        "sase.notifications.dismiss_agent_completion_notifications", dismiss
    )

    app = _PollApp()
    await app._poll_agent_completions()

    assert app.bell_rings == 1
    assert len(app.toast_calls) == 1
    # Latch armed; dismissal will happen when the user enters Agents or
    # takes any action there — but not yet.
    assert app._agent_completion_ack_latch is True
    dismiss.assert_not_called()


@pytest.mark.asyncio
async def test_indicator_only_refreshes_when_bulk_dismiss_changed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The notification indicator must refresh once after a non-zero dismissal,
    and not when nothing changed."""
    dismiss = MagicMock(return_value=0)
    monkeypatch.setattr(
        "sase.notifications.dismiss_agent_completion_notifications", dismiss
    )

    refresh_calls = 0

    class _App(AgentNotificationMixin):
        def __init__(self) -> None:
            self._agent_completion_dismiss_inflight = False
            self._agent_completion_ack_latch = True

        async def _refresh_notification_count_async(self) -> None:  # type: ignore[override]
            nonlocal refresh_calls
            refresh_calls += 1

    app = _App()

    # Zero changed → no refresh.
    await app._dismiss_agent_completion_notifications_for_agents_tab(force=True)
    assert refresh_calls == 0

    # Now simulate a meaningful dismissal.
    dismiss.return_value = 4
    app._agent_completion_ack_latch = True
    await app._dismiss_agent_completion_notifications_for_agents_tab()
    assert refresh_calls == 1


class TestBulkDismissCoversAllCompletionStates:
    """Confirms the bulk primitive covers read and muted completions too.

    The design spec explicitly calls for dismissing *all* outstanding
    completion notifications, not just unread ones — muted/snoozed and
    read-but-not-dismissed completion rows must both go.
    """

    def test_dismisses_read_but_not_dismissed_completions(
        self, temp_notifications_dir: Path
    ) -> None:
        append_notification(_completion(n_id="read-jump"))
        mark_read("read-jump")

        count = dismiss_agent_completion_notifications()

        by_id = {n.id: n for n in load_notifications(include_dismissed=True)}
        assert count == 1
        assert by_id["read-jump"].dismissed is True
        assert by_id["read-jump"].read is True

    def test_dismisses_muted_completions(self, temp_notifications_dir: Path) -> None:
        append_notification(_completion(n_id="muted-jump"))
        mark_muted("muted-jump", True)

        count = dismiss_agent_completion_notifications()

        by_id = {n.id: n for n in load_notifications(include_dismissed=True)}
        assert count == 1
        assert by_id["muted-jump"].dismissed is True

    def test_dismisses_muted_view_error_report_completions(
        self, temp_notifications_dir: Path
    ) -> None:
        append_notification(
            _completion(action="ViewErrorReport", n_id="muted-err", cl_name="x")
        )
        mark_muted("muted-err", True)

        count = dismiss_agent_completion_notifications()

        by_id = {n.id: n for n in load_notifications(include_dismissed=True)}
        assert count == 1
        assert by_id["muted-err"].dismissed is True


class TestBulkDismissLeavesUnrelatedAlone:
    """Unrelated notifications must survive an Agents-tab bulk dismiss."""

    def test_leaves_axe_view_error_report_and_changespec_and_mentor(
        self, temp_notifications_dir: Path
    ) -> None:
        from tests.notification_store.helpers import make_notification

        append_notification(_completion(n_id="completion"))
        append_notification(
            make_notification(
                id="axe-err",
                sender="axe",
                action="ViewErrorReport",
                action_data={"error_report_path": "/tmp/x"},
            )
        )
        append_notification(
            make_notification(
                id="crs-jump",
                sender="crs",
                action="JumpToChangeSpec",
                action_data={"cl_name": "c"},
            )
        )
        append_notification(
            make_notification(
                id="mentor",
                sender="user-agent",
                action="JumpToMentorReview",
                action_data={"cl_name": "m"},
            )
        )
        append_notification(
            make_notification(
                id="plan",
                sender="user-agent",
                action="PlanApproval",
                action_data={"agent_cl_name": "p"},
            )
        )
        append_notification(
            make_notification(
                id="question",
                sender="user-agent",
                action="UserQuestion",
                action_data={"agent_cl_name": "q"},
            )
        )

        count = dismiss_agent_completion_notifications()

        by_id = {n.id: n for n in load_notifications(include_dismissed=True)}
        assert count == 1
        assert by_id["completion"].dismissed is True
        for survivor in ("axe-err", "crs-jump", "mentor", "plan", "question"):
            assert by_id[survivor].dismissed is False, survivor


@pytest.mark.asyncio
async def test_agents_tab_entry_dismisses_jump_and_error_through_real_store(
    temp_notifications_dir: Path,
) -> None:
    """End-to-end: the Agents-tab entry helper routes through the real Rust store
    and dismisses both completion shapes while leaving interactive and external
    notifications untouched."""
    from tests.notification_store.helpers import make_notification

    # Two completion rows (one JumpToAgent, one ViewErrorReport from a
    # user-agent), plus interactive + unrelated rows that must survive.
    append_notification(_completion(n_id="jump-a", cl_name="a"))
    append_notification(
        _completion(action="ViewErrorReport", n_id="err-b", cl_name="b")
    )
    append_notification(
        make_notification(
            id="plan-c",
            sender="user-agent",
            action="PlanApproval",
            action_data={"agent_cl_name": "c"},
        )
    )
    append_notification(
        make_notification(
            id="axe-err",
            sender="axe",
            action="ViewErrorReport",
            action_data={"error_report_path": "/tmp/x"},
        )
    )

    refresh_calls = 0

    class _EntryApp(AgentNotificationMixin):
        def __init__(self) -> None:
            self._agent_completion_dismiss_inflight = False
            # Force=True path is used on Agents-tab entry, so the latch
            # state doesn't matter — leave it clear to confirm force still wins.
            self._agent_completion_ack_latch = False

        async def _refresh_notification_count_async(self) -> None:  # type: ignore[override]
            nonlocal refresh_calls
            refresh_calls += 1

    app = _EntryApp()
    await app._dismiss_agent_completion_notifications_for_agents_tab(force=True)

    by_id = {n.id: n for n in load_notifications(include_dismissed=True)}
    assert by_id["jump-a"].dismissed is True
    assert by_id["err-b"].dismissed is True
    assert by_id["plan-c"].dismissed is False
    assert by_id["axe-err"].dismissed is False
    # Two real changes → exactly one indicator refresh.
    assert refresh_calls == 1
    assert app._agent_completion_dismiss_inflight is False


@pytest.mark.asyncio
async def test_repeat_dismiss_after_clean_does_not_refresh(
    temp_notifications_dir: Path,
) -> None:
    """A second forced dismiss on an already-clean store must skip the indicator
    refresh — covers the j/k coalescing path where the latch is armed but the
    underlying store has nothing left to clear."""
    from tests.notification_store.helpers import make_notification

    append_notification(_completion(n_id="jump-a"))
    append_notification(
        make_notification(
            id="plan",
            sender="user-agent",
            action="PlanApproval",
            action_data={"agent_cl_name": "p"},
        )
    )

    refresh_calls = 0

    class _ActivityApp(AgentNotificationMixin):
        def __init__(self) -> None:
            self._agent_completion_dismiss_inflight = False
            self._agent_completion_ack_latch = True

        async def _refresh_notification_count_async(self) -> None:  # type: ignore[override]
            nonlocal refresh_calls
            refresh_calls += 1

    app = _ActivityApp()

    # First call dismisses the one completion → one refresh.
    await app._dismiss_agent_completion_notifications_for_agents_tab(force=True)
    assert refresh_calls == 1

    # Second call after the store is already clean → no further refresh.
    await app._dismiss_agent_completion_notifications_for_agents_tab(force=True)
    assert refresh_calls == 1

    # The PlanApproval row is still in the store.
    by_id = {n.id: n for n in load_notifications(include_dismissed=True)}
    assert by_id["plan"].dismissed is False


@pytest.mark.asyncio
async def test_already_read_completion_still_dismissed_on_entry(
    temp_notifications_dir: Path,
) -> None:
    """A completion the user previously read (e.g. from the notification modal)
    is still cleared when entering the Agents tab — the design requires *all*
    outstanding completion rows go, not just unread ones."""
    append_notification(_completion(n_id="seen-jump"))
    mark_read("seen-jump")

    class _EntryApp(AgentNotificationMixin):
        def __init__(self) -> None:
            self._agent_completion_dismiss_inflight = False
            self._agent_completion_ack_latch = False

        async def _refresh_notification_count_async(self) -> None:  # type: ignore[override]
            pass

    app = _EntryApp()
    await app._dismiss_agent_completion_notifications_for_agents_tab(force=True)

    loaded = {n.id: n for n in load_notifications(include_dismissed=True)}
    assert loaded["seen-jump"].dismissed is True

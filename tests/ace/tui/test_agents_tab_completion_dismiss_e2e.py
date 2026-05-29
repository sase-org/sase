"""End-to-end contract tests for one-to-one agent completion dismissal.

The product contract this guards is:

- Each completed Agents-tab row is unread iff its matching completion
  notification is still active (not dismissed).
- Reading a single row dismisses exactly that row's matching notification.
- Dismissing a notification through the notification API clears exactly
  that row on the next reconciliation pass.
- Entering / navigating the Agents tab alone never bulk-dismisses
  unrelated completion (or non-completion) notifications.

These tests drive the real Rust-backed notification store through
``temp_notifications_dir`` so the projection helpers, per-row dismiss
helper, and finalize sync pipeline are exercised end-to-end against
the actual persistence layer rather than mocks.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.ace.tui.actions.agents._core import AgentsMixinCore
from sase.ace.tui.actions.agents._loading_finalize import (
    _sync_unread_completed_agents,
)
from sase.ace.tui.modals.notification_modal import NotificationModal
from sase.ace.tui.models.agent import Agent, AgentType
from sase.notifications import (
    Notification,
    append_notification,
    load_notifications,
    mark_dismissed,
    read_notification_snapshot,
)

from ._agent_unread_helpers import make_agent


@pytest.fixture()
def temp_notifications_dir(tmp_path: Path) -> Iterator[Path]:
    """Patch NOTIFICATIONS_DIR/FILE so each test gets an isolated store."""
    notifications_dir = str(tmp_path / "notifications")
    notifications_file = str(tmp_path / "notifications" / "notifications.jsonl")
    with (
        patch("sase.notifications.store.NOTIFICATIONS_DIR", notifications_dir),
        patch("sase.notifications.store.NOTIFICATIONS_FILE", notifications_file),
    ):
        yield tmp_path


def _completion_notification(
    agent: Agent,
    *,
    n_id: str,
    action: str = "JumpToAgent",
    tags: list[str] | None = None,
) -> Notification:
    if tags is None:
        tags = ["done"] if action == "JumpToAgent" else []
    return Notification(
        id=n_id,
        timestamp="2026-05-11T12:00:00-04:00",
        sender="user-agent",
        tags=tags,
        action=action,
        action_data={
            "cl_name": agent.cl_name,
            "raw_suffix": agent.raw_suffix or "",
        },
    )


class _E2EApp(AgentsMixinCore):
    """Minimal stand-in app exercising the per-row helpers and finalize sync."""

    def __init__(self, agents: list[Agent]) -> None:
        self._agents = agents
        self.current_idx = 0
        self.current_tab = "agents"
        self._current_group_key: tuple[str, ...] | None = None
        self._unread_completed_agent_ids: set[tuple[AgentType, str, str | None]] = set()
        self._manual_unread_agent_ids: set[tuple[AgentType, str, str | None]] = set()
        self._agent_display_status_by_identity: dict[
            tuple[AgentType, str, str | None], str
        ] = {}
        self.refresh_count_calls = 0
        self.patch_calls: list[Agent] = []
        self.refresh_calls: list[dict[str, object]] = []

    def _refresh_notification_count(self) -> None:
        self.refresh_count_calls += 1

    def _try_patch_agent_row(self, agent: Agent) -> bool:
        self.patch_calls.append(agent)
        return True

    def _refresh_agents_display(self, **kwargs: object) -> None:
        self.refresh_calls.append(kwargs)


def _active_completion_ids() -> set[str]:
    """Return ids of completion notifications still active in the store."""
    return {
        n.id
        for n in load_notifications()
        if n.sender == "user-agent" and n.action in ("JumpToAgent", "ViewErrorReport")
    }


def _modal_visible_ids(modal: NotificationModal) -> list[str]:
    """Return notification ids in current modal visual order."""
    ids: list[str] = []
    for option in modal._create_sectioned_options():
        if option.disabled or option.id is None or str(option.id).startswith("hdr:"):
            continue
        ids.append(modal._notifications[int(str(option.id))].id)
    return ids


def _sync_from_store(app: _E2EApp, *, on_agents_tab: bool) -> None:
    """Refresh the notification cache and run the hot-path finalizer sync."""
    app._notification_snapshot_cache = read_notification_snapshot()
    _sync_unread_completed_agents(app, on_agents_tab=on_agents_tab)  # type: ignore[arg-type]


def test_two_completed_agents_with_two_notifications_start_unread(
    temp_notifications_dir: Path,
) -> None:
    """Both completion notifications project onto matching unread rows."""
    assert temp_notifications_dir.is_dir()
    first = make_agent(name="alpha", status="DONE", raw_suffix="20260507090000")
    second = make_agent(name="beta", status="FAILED", raw_suffix="20260507100000")
    app = _E2EApp([first, second])
    append_notification(_completion_notification(first, n_id="n-alpha"))
    append_notification(
        _completion_notification(second, n_id="n-beta", action="ViewErrorReport")
    )

    # Off-tab finalize so neither row is auto-cleared by being the selection.
    _sync_from_store(app, on_agents_tab=False)

    assert app._unread_completed_agent_ids == {first.identity, second.identity}


def test_done_tab_matches_successful_unread_completion_notifications(
    temp_notifications_dir: Path,
) -> None:
    """The done tab contains successful completions that project unread rows."""
    assert temp_notifications_dir.is_dir()
    first = make_agent(name="alpha", status="DONE", raw_suffix="20260507090000")
    second = make_agent(name="beta", status="DONE", raw_suffix="20260507100000")
    failed = make_agent(name="gamma", status="FAILED", raw_suffix="20260507110000")
    app = _E2EApp([first, second, failed])
    append_notification(_completion_notification(first, n_id="n-alpha"))
    append_notification(_completion_notification(second, n_id="n-beta"))
    append_notification(
        _completion_notification(failed, n_id="n-failure", action="ViewErrorReport")
    )

    _sync_from_store(app, on_agents_tab=False)

    assert app._unread_completed_agent_ids == {
        first.identity,
        second.identity,
        failed.identity,
    }
    modal = NotificationModal(load_notifications())
    assert [(tab.tag, tab.count) for tab in modal._tag_tabs()] == [
        ("errors", 1),
        ("done", 2),
    ]
    assert _modal_visible_ids(modal) == ["n-failure"]

    modal._active_notification_tag = "done"
    assert set(_modal_visible_ids(modal)) == {"n-alpha", "n-beta"}
    assert "n-failure" not in _modal_visible_ids(modal)

    modal._active_notification_tag = "errors"
    assert _modal_visible_ids(modal) == ["n-failure"]


def test_acknowledging_done_agent_removes_completion_from_done_not_general_tab(
    temp_notifications_dir: Path,
) -> None:
    """Reading one done row removes only its completion notification."""
    assert temp_notifications_dir.is_dir()
    first = make_agent(name="alpha", status="DONE", raw_suffix="20260507090000")
    second = make_agent(name="beta", status="DONE", raw_suffix="20260507100000")
    app = _E2EApp([first, second])
    append_notification(_completion_notification(first, n_id="n-alpha"))
    append_notification(_completion_notification(second, n_id="n-beta"))
    append_notification(
        Notification(
            id="n-plan",
            timestamp="2026-05-11T12:01:00-04:00",
            sender="plan",
            action="PlanApproval",
            action_data={
                "agent_cl_name": first.cl_name,
                "agent_timestamp": first.raw_suffix or "",
            },
        )
    )
    _sync_from_store(app, on_agents_tab=False)
    assert app._unread_completed_agent_ids == {first.identity, second.identity}

    modal = NotificationModal(load_notifications())
    assert _modal_visible_ids(modal) == ["n-plan"]
    modal._active_notification_tag = "done"
    assert set(_modal_visible_ids(modal)) == {"n-alpha", "n-beta"}

    assert app._clear_agent_unread_and_dismiss_notification(first)

    modal = NotificationModal(load_notifications())
    assert _modal_visible_ids(modal) == ["n-plan"]
    modal._active_notification_tag = "done"
    assert _modal_visible_ids(modal) == ["n-beta"]
    assert app._unread_completed_agent_ids == {second.identity}
    assert app.refresh_count_calls == 1


def test_reading_one_agent_dismisses_only_its_notification(
    temp_notifications_dir: Path,
) -> None:
    """The per-row helper dismisses exactly one notification and clears one row."""
    assert temp_notifications_dir.is_dir()
    first = make_agent(name="alpha", status="DONE", raw_suffix="20260507090000")
    second = make_agent(name="beta", status="DONE", raw_suffix="20260507100000")
    app = _E2EApp([first, second])
    append_notification(_completion_notification(first, n_id="n-alpha"))
    append_notification(_completion_notification(second, n_id="n-beta"))
    _sync_from_store(app, on_agents_tab=False)
    assert app._unread_completed_agent_ids == {first.identity, second.identity}

    assert app._clear_agent_unread_and_dismiss_notification(first)

    assert app._unread_completed_agent_ids == {second.identity}
    assert _active_completion_ids() == {"n-beta"}
    assert app.refresh_count_calls == 1


def test_dismissing_notification_clears_other_row_on_refresh(
    temp_notifications_dir: Path,
) -> None:
    """A notification dismissed via the API clears its row on next reconcile."""
    assert temp_notifications_dir.is_dir()
    first = make_agent(name="alpha", status="DONE", raw_suffix="20260507090000")
    second = make_agent(name="beta", status="DONE", raw_suffix="20260507100000")
    app = _E2EApp([first, second])
    append_notification(_completion_notification(first, n_id="n-alpha"))
    append_notification(_completion_notification(second, n_id="n-beta"))
    _sync_from_store(app, on_agents_tab=False)
    assert app._unread_completed_agent_ids == {first.identity, second.identity}

    # Dismiss the beta notification directly via the notification API
    # (mirrors the user dismissing it from the notification modal).
    assert mark_dismissed("n-beta")

    _sync_from_store(app, on_agents_tab=False)

    assert app._unread_completed_agent_ids == {first.identity}
    assert _active_completion_ids() == {"n-alpha"}


def test_entering_agents_tab_does_not_dismiss_selected_row(
    temp_notifications_dir: Path,
) -> None:
    """The finalize sync does not treat the selected row as read.

    Landing on the Agents tab must not silently dismiss active completion
    notifications. A focused unread row is acknowledged only when the user
    intentionally selects/navigates into that row again.
    """
    assert temp_notifications_dir.is_dir()
    first = make_agent(name="alpha", status="DONE", raw_suffix="20260507090000")
    second = make_agent(name="beta", status="DONE", raw_suffix="20260507100000")
    third = make_agent(name="gamma", status="DONE", raw_suffix="20260507110000")
    app = _E2EApp([first, second, third])
    app.current_idx = 0  # alpha is the selected row.
    append_notification(_completion_notification(first, n_id="n-alpha"))
    append_notification(_completion_notification(second, n_id="n-beta"))
    append_notification(_completion_notification(third, n_id="n-gamma"))

    # Seed the unread set the way a prior refresh tick would: every
    # completion notification has projected onto its row.
    app._unread_completed_agent_ids = {
        first.identity,
        second.identity,
        third.identity,
    }

    _sync_from_store(app, on_agents_tab=True)

    assert app._unread_completed_agent_ids == {
        first.identity,
        second.identity,
        third.identity,
    }
    assert _active_completion_ids() == {"n-alpha", "n-beta", "n-gamma"}


def test_navigating_within_agents_tab_does_not_bulk_dismiss(
    temp_notifications_dir: Path,
) -> None:
    """Repeated finalize ticks must not drain unrelated completion rows."""
    assert temp_notifications_dir.is_dir()
    selected = make_agent(name="focused", status="RUNNING", raw_suffix="focused")
    first = make_agent(name="alpha", status="DONE", raw_suffix="20260507090000")
    second = make_agent(name="beta", status="DONE", raw_suffix="20260507100000")
    app = _E2EApp([selected, first, second])
    app.current_idx = 0  # focus a still-running agent → no row to ack.
    append_notification(_completion_notification(first, n_id="n-alpha"))
    append_notification(_completion_notification(second, n_id="n-beta"))

    # Multiple finalize ticks (e.g. j/k navigation auto-refresh) must not
    # ever dismiss a notification whose row is not focused.
    for _ in range(3):
        _sync_from_store(app, on_agents_tab=True)

    assert app._unread_completed_agent_ids == {first.identity, second.identity}
    assert _active_completion_ids() == {"n-alpha", "n-beta"}


def test_unrelated_notifications_survive_agents_tab_activity(
    temp_notifications_dir: Path,
) -> None:
    """Unrelated plan/question/mentor/axe rows are untouched by finalize sync."""
    assert temp_notifications_dir.is_dir()
    agent = make_agent(name="alpha", status="DONE", raw_suffix="20260507090000")
    app = _E2EApp([agent])
    app.current_idx = 0
    append_notification(_completion_notification(agent, n_id="n-completion"))

    # Notifications for OTHER agents and from non-agent senders — none of
    # these should be touched when we ack alpha's completion row.
    append_notification(
        Notification(
            id="n-plan",
            timestamp="2026-05-11T12:01:00-04:00",
            sender="user-agent",
            action="PlanApproval",
            action_data={"agent_cl_name": "other"},
        )
    )
    append_notification(
        Notification(
            id="n-question",
            timestamp="2026-05-11T12:02:00-04:00",
            sender="user-agent",
            action="UserQuestion",
            action_data={"agent_cl_name": "other"},
        )
    )
    append_notification(
        Notification(
            id="n-mentor",
            timestamp="2026-05-11T12:03:00-04:00",
            sender="mentors",
            action="JumpToMentorReview",
            action_data={"cl_name": agent.cl_name},
        )
    )
    append_notification(
        Notification(
            id="n-axe",
            timestamp="2026-05-11T12:04:00-04:00",
            sender="axe",
            action="ViewErrorReport",
            action_data={"chop_id": "c1"},
        )
    )
    app._unread_completed_agent_ids = {agent.identity}

    _sync_from_store(app, on_agents_tab=True)

    # Finalize does not acknowledge the focused completion row. All
    # notifications must remain in the store.
    active_ids = {n.id for n in load_notifications()}
    assert active_ids == {
        "n-completion",
        "n-plan",
        "n-question",
        "n-mentor",
        "n-axe",
    }


def test_raw_suffix_disambiguates_same_cl_name(
    temp_notifications_dir: Path,
) -> None:
    """Two runs of the same agent get one-to-one mapping by raw_suffix."""
    assert temp_notifications_dir.is_dir()
    first_run = make_agent(name="alpha", status="DONE", raw_suffix="20260507090000")
    second_run = make_agent(name="alpha", status="DONE", raw_suffix="20260507100000")
    app = _E2EApp([first_run, second_run])
    append_notification(_completion_notification(first_run, n_id="n-first"))
    append_notification(_completion_notification(second_run, n_id="n-second"))
    _sync_from_store(app, on_agents_tab=False)
    assert app._unread_completed_agent_ids == {first_run.identity, second_run.identity}

    assert app._clear_agent_unread_and_dismiss_notification(second_run)

    assert app._unread_completed_agent_ids == {first_run.identity}
    assert _active_completion_ids() == {"n-first"}

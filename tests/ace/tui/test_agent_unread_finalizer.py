"""Unread agent finalization tests."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from sase.ace.tui.actions.agents._loading_finalize import (
    _sync_unread_completed_agents,
)
from sase.ace.tui.actions.agents._core import AgentsMixinCore
from sase.ace.tui.models._agent_tree import project_clan_tree
from sase.ace.tui.models.agent import Agent, AgentType

from ._agent_unread_helpers import make_agent

_SNAPSHOT_NOTIFICATIONS: list[object] = []


def _completion_notification(
    agent: Agent, *, dismissed: bool = False
) -> SimpleNamespace:
    """Build a minimal completion-notification stand-in for projection tests."""
    return SimpleNamespace(
        sender="user-agent",
        action="JumpToAgent",
        action_data={"cl_name": agent.cl_name, "raw_suffix": agent.raw_suffix},
        dismissed=dismissed,
    )


@pytest.fixture(autouse=True)
def notification_dismiss(monkeypatch: pytest.MonkeyPatch) -> Mock:
    dismiss = Mock(return_value=0)
    monkeypatch.setattr(
        "sase.notifications.dismiss_notifications_matching_agents", dismiss
    )
    return dismiss


@pytest.fixture(autouse=True)
def snapshot_notifications(monkeypatch: pytest.MonkeyPatch) -> list[object]:
    """Stub ``read_notification_snapshot`` and let tests append notifications."""
    notifications: list[object] = []
    global _SNAPSHOT_NOTIFICATIONS
    _SNAPSHOT_NOTIFICATIONS = notifications

    def _stub(*_args: object, **_kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(notifications=list(notifications), expired_ids=[])

    monkeypatch.setattr("sase.notifications.read_notification_snapshot", _stub)
    return notifications


class _UnreadFinalizeApp(AgentsMixinCore):
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
        self._notification_snapshot_cache = SimpleNamespace(
            notifications=_SNAPSHOT_NOTIFICATIONS
        )
        self.notification_count_refresh_calls = 0

    def _refresh_notification_count(self) -> None:
        self.notification_count_refresh_calls += 1


def test_finalizer_marks_terminal_agent_unread_when_notification_active(
    snapshot_notifications: list[object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = make_agent(status="DONE")
    app = _UnreadFinalizeApp([agent])
    snapshot_notifications.append(_completion_notification(agent))
    read_snapshot = Mock(side_effect=AssertionError("finalizer must use cache"))
    monkeypatch.setattr("sase.notifications.read_notification_snapshot", read_snapshot)

    _sync_unread_completed_agents(app, on_agents_tab=False)  # type: ignore[arg-type]

    assert app._unread_completed_agent_ids == {agent.identity}
    read_snapshot.assert_not_called()


def test_finalizer_marks_plan_done_agent_unread_when_notification_active(
    snapshot_notifications: list[object],
) -> None:
    agent = make_agent(status="PLAN DONE")
    app = _UnreadFinalizeApp([agent])
    snapshot_notifications.append(_completion_notification(agent))

    _sync_unread_completed_agents(app, on_agents_tab=False)  # type: ignore[arg-type]

    assert app._unread_completed_agent_ids == {agent.identity}


def test_finalizer_does_not_mark_terminal_agent_without_notification(
    snapshot_notifications: list[object],
) -> None:
    agent = make_agent(status="DONE")
    app = _UnreadFinalizeApp([agent])

    _sync_unread_completed_agents(app, on_agents_tab=False)  # type: ignore[arg-type]

    assert app._unread_completed_agent_ids == set()


def test_finalizer_marks_currently_selected_agent_unread_when_notification_active(
    snapshot_notifications: list[object],
) -> None:
    agent = make_agent(status="DONE")
    app = _UnreadFinalizeApp([agent])
    snapshot_notifications.append(_completion_notification(agent))

    _sync_unread_completed_agents(app, on_agents_tab=True)  # type: ignore[arg-type]

    assert app._unread_completed_agent_ids == {agent.identity}


def test_finalizer_clears_unread_when_selected_row_lacks_notification(
    snapshot_notifications: list[object],
) -> None:
    agent = make_agent(status="DONE")
    app = _UnreadFinalizeApp([agent])
    app._unread_completed_agent_ids.add(agent.identity)

    _sync_unread_completed_agents(app, on_agents_tab=True)  # type: ignore[arg-type]

    assert app._unread_completed_agent_ids == set()


def test_finalizer_does_not_ack_saved_selection_on_agents_tab(
    notification_dismiss: Mock,
    snapshot_notifications: list[object],
) -> None:
    notification_dismiss.return_value = 1
    agent = make_agent(status="DONE")
    app = _UnreadFinalizeApp([agent])
    snapshot_notifications.append(_completion_notification(agent))
    app._unread_completed_agent_ids.add(agent.identity)

    _sync_unread_completed_agents(app, on_agents_tab=True)  # type: ignore[arg-type]

    assert app._unread_completed_agent_ids == {agent.identity}
    notification_dismiss.assert_not_called()
    assert app.notification_count_refresh_calls == 0


def test_finalizer_preserves_selected_manually_unread_agent(
    snapshot_notifications: list[object],
) -> None:
    agent = make_agent(status="DONE")
    app = _UnreadFinalizeApp([agent])
    app._unread_completed_agent_ids.add(agent.identity)
    app._manual_unread_agent_ids.add(agent.identity)

    _sync_unread_completed_agents(app, on_agents_tab=True)  # type: ignore[arg-type]

    assert app._unread_completed_agent_ids == {agent.identity}
    assert app._manual_unread_agent_ids == {agent.identity}


def test_finalizer_clears_row_when_notification_dismissed(
    snapshot_notifications: list[object],
) -> None:
    """A row with no active completion notification drops out of unread."""
    agent = make_agent(status="DONE")
    app = _UnreadFinalizeApp([agent])
    app._unread_completed_agent_ids.add(agent.identity)

    _sync_unread_completed_agents(app, on_agents_tab=False)  # type: ignore[arg-type]

    assert app._unread_completed_agent_ids == set()


def test_finalizer_keeps_manual_unread_without_notification(
    snapshot_notifications: list[object],
) -> None:
    """Manual ``U`` keeps a row unread even when no notification exists."""
    agent = make_agent(status="DONE")
    app = _UnreadFinalizeApp([agent])
    app._unread_completed_agent_ids.add(agent.identity)
    app._manual_unread_agent_ids.add(agent.identity)

    _sync_unread_completed_agents(app, on_agents_tab=False)  # type: ignore[arg-type]

    assert app._unread_completed_agent_ids == {agent.identity}


def test_finalizer_ignores_dismissed_completion_notifications(
    snapshot_notifications: list[object],
) -> None:
    agent = make_agent(status="DONE")
    app = _UnreadFinalizeApp([agent])
    snapshot_notifications.append(_completion_notification(agent, dismissed=True))

    _sync_unread_completed_agents(app, on_agents_tab=False)  # type: ignore[arg-type]

    assert app._unread_completed_agent_ids == set()


def test_finalizer_raw_suffix_disambiguates_same_cl_name(
    snapshot_notifications: list[object],
) -> None:
    first = make_agent(name="demo", status="DONE", raw_suffix="20260507090000")
    second = make_agent(name="demo", status="DONE", raw_suffix="20260507100000")
    app = _UnreadFinalizeApp([first, second])
    snapshot_notifications.append(_completion_notification(second))

    _sync_unread_completed_agents(app, on_agents_tab=False)  # type: ignore[arg-type]

    assert app._unread_completed_agent_ids == {second.identity}


def test_finalizer_prunes_unread_identities_no_longer_visible(
    snapshot_notifications: list[object],
) -> None:
    visible = make_agent(name="visible", status="RUNNING", raw_suffix="visible")
    stale = make_agent(name="stale", status="DONE", raw_suffix="stale")
    app = _UnreadFinalizeApp([visible])
    app._unread_completed_agent_ids.add(stale.identity)

    _sync_unread_completed_agents(app, on_agents_tab=False)  # type: ignore[arg-type]

    assert app._unread_completed_agent_ids == set()


def test_finalizer_prunes_stale_manual_unread_identities(
    snapshot_notifications: list[object],
) -> None:
    visible = make_agent(name="visible", status="RUNNING", raw_suffix="visible")
    stale = make_agent(name="stale", status="DONE", raw_suffix="stale")
    app = _UnreadFinalizeApp([visible])
    app._unread_completed_agent_ids.add(stale.identity)
    app._manual_unread_agent_ids.add(stale.identity)

    _sync_unread_completed_agents(app, on_agents_tab=False)  # type: ignore[arg-type]

    assert app._unread_completed_agent_ids == set()
    assert app._manual_unread_agent_ids == set()


def test_finalizer_retains_member_hidden_by_collapsed_clan(
    snapshot_notifications: list[object],
) -> None:
    member = make_agent(name="research.done", status="DONE", raw_suffix="done")
    member.agent_clan = "research"
    member.agent_clan_generation = "generation"
    complete = project_clan_tree([member])
    container = complete[0]
    app = _UnreadFinalizeApp([container])
    app._agents_with_children = complete
    snapshot_notifications.append(_completion_notification(member))

    _sync_unread_completed_agents(app, on_agents_tab=True)  # type: ignore[arg-type]

    assert app._unread_completed_agent_ids == {member.identity}
    assert container.identity not in app._unread_completed_agent_ids

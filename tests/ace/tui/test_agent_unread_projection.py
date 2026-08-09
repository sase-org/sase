"""Tests for projecting active completion notifications onto unread rows."""

from __future__ import annotations

from types import SimpleNamespace

from sase.ace.tui.actions.agents._core import AgentsMixinCore
from sase.ace.tui.actions.agents._notifications import (
    _active_completion_agent_keys,
)
from sase.ace.tui.models._agent_tree import project_clan_tree
from sase.ace.tui.models.agent import Agent, AgentType
from sase.notifications import Notification

from ._agent_unread_helpers import make_agent


def _make_notification(
    *,
    sender: str = "user-agent",
    action: str | None = "JumpToAgent",
    cl_name: str | None = "demo",
    raw_suffix: str | None = "20260507090000",
    dismissed: bool = False,
    silent: bool = False,
    extra_data: dict[str, str] | None = None,
) -> Notification:
    action_data: dict[str, str] = {}
    if cl_name is not None:
        action_data["cl_name"] = cl_name
    if raw_suffix is not None:
        action_data["raw_suffix"] = raw_suffix
    if extra_data:
        action_data.update(extra_data)
    return Notification(
        id="test-id",
        timestamp="2026-05-07T09:00:00",
        sender=sender,
        action=action,
        action_data=action_data,
        dismissed=dismissed,
        silent=silent,
    )


class _ProjectionApp(AgentsMixinCore):
    def __init__(self, agents: list[Agent]) -> None:
        self._agents = agents
        self.current_idx = 0
        self.current_tab = "agents"
        self._current_group_key: tuple[str, ...] | None = None
        self._unread_completed_agent_ids: set[tuple[AgentType, str, str | None]] = set()
        self._manual_unread_agent_ids: set[tuple[AgentType, str, str | None]] = set()
        self._pending_bulk_read_agent_ids: (
            set[tuple[AgentType, str, str | None]] | None
        ) = None
        self._agent_info_metrics_cache: tuple[object, ...] | None = None
        self._notification_snapshot_cache = None
        self.patch_calls: list[Agent] = []
        self.refresh_calls: list[dict[str, object]] = []

    def _try_patch_agent_row(self, agent: Agent) -> bool:
        self.patch_calls.append(agent)
        return True

    def _refresh_agents_display(self, **kwargs: object) -> None:
        self.refresh_calls.append(kwargs)


def test__active_completion_agent_keys_picks_up_jump_to_agent() -> None:
    keys = _active_completion_agent_keys(  # type: ignore[arg-type]
        [_make_notification(cl_name="demo", raw_suffix="20260507090000")]
    )
    assert keys == {("demo", "20260507090000")}


def test__active_completion_agent_keys_picks_up_view_error_report() -> None:
    keys = _active_completion_agent_keys(  # type: ignore[arg-type]
        [
            _make_notification(
                action="ViewErrorReport", cl_name="demo", raw_suffix="20260507090000"
            )
        ]
    )
    assert keys == {("demo", "20260507090000")}


def test__active_completion_agent_keys_ignores_dismissed() -> None:
    keys = _active_completion_agent_keys(  # type: ignore[arg-type]
        [_make_notification(dismissed=True)]
    )
    assert keys == set()


def test__active_completion_agent_keys_keeps_silent_rows() -> None:
    """Silent rows still gate the agent-row unread marker."""
    keys = _active_completion_agent_keys(  # type: ignore[arg-type]
        [_make_notification(silent=True)]
    )
    assert keys == {("demo", "20260507090000")}


def test__active_completion_agent_keys_ignores_unrelated_actions() -> None:
    keys = _active_completion_agent_keys(  # type: ignore[arg-type]
        [
            _make_notification(action="PlanApproval"),
            _make_notification(action="UserQuestion"),
            _make_notification(action="JumpToPatch"),
            _make_notification(sender="fix-hook"),
            _make_notification(cl_name=None),
        ]
    )
    assert keys == set()


def test__active_completion_agent_keys_allows_missing_raw_suffix() -> None:
    keys = _active_completion_agent_keys(  # type: ignore[arg-type]
        [_make_notification(raw_suffix=None)]
    )
    assert keys == {("demo", None)}


def test_reconcile_marks_unread_when_notification_active() -> None:
    agent = make_agent(status="DONE")
    app = _ProjectionApp([agent])

    app._reconcile_unread_from_completion_notifications(
        [_make_notification(cl_name=agent.cl_name, raw_suffix=agent.raw_suffix)]
    )

    assert agent.identity in app._unread_completed_agent_ids


def test_reconcile_new_unread_invalidates_pending_bulk_read_undo() -> None:
    first = make_agent(name="first", status="DONE", raw_suffix="first")
    second = make_agent(name="second", status="DONE", raw_suffix="second")
    app = _ProjectionApp([first, second])
    app._pending_bulk_read_agent_ids = {first.identity}

    app._reconcile_unread_from_completion_notifications(
        [_make_notification(cl_name=second.cl_name, raw_suffix=second.raw_suffix)]
    )

    assert app._pending_bulk_read_agent_ids is None
    assert app._unread_completed_agent_ids == {second.identity}

    app._reconcile_unread_from_completion_notifications([])
    assert app._pending_bulk_read_agent_ids is None


def test_reconcile_preserving_or_removing_unread_keeps_pending_bulk_read_undo() -> None:
    agent = make_agent(status="DONE")
    saved = make_agent(name="saved", status="DONE", raw_suffix="saved")
    app = _ProjectionApp([agent])
    app._unread_completed_agent_ids.add(agent.identity)
    app._pending_bulk_read_agent_ids = {saved.identity}

    app._reconcile_unread_from_completion_notifications(
        [_make_notification(cl_name=agent.cl_name, raw_suffix=agent.raw_suffix)]
    )

    assert app._pending_bulk_read_agent_ids == {saved.identity}

    app._reconcile_unread_from_completion_notifications([])
    assert app._pending_bulk_read_agent_ids == {saved.identity}
    assert app._unread_completed_agent_ids == set()


def test_reconcile_clears_unread_when_notification_missing() -> None:
    agent = make_agent(status="DONE")
    app = _ProjectionApp([agent])
    app._unread_completed_agent_ids.add(agent.identity)

    app._reconcile_unread_from_completion_notifications([])

    assert agent.identity not in app._unread_completed_agent_ids


def test_cached_reconcile_marks_selected_agent_unread_and_patches_row() -> None:
    agent = make_agent(status="DONE")
    app = _ProjectionApp([agent])
    app.current_idx = 0
    app._notification_snapshot_cache = SimpleNamespace(
        notifications=[
            _make_notification(cl_name=agent.cl_name, raw_suffix=agent.raw_suffix)
        ]
    )

    app._reconcile_unread_from_cached_notifications()

    assert agent.identity in app._unread_completed_agent_ids
    assert app.patch_calls == [agent]
    assert app.refresh_calls == []


def test_reconcile_preserves_manual_unread_when_no_notification() -> None:
    agent = make_agent(status="DONE")
    app = _ProjectionApp([agent])
    app._unread_completed_agent_ids.add(agent.identity)
    app._manual_unread_agent_ids.add(agent.identity)

    app._reconcile_unread_from_completion_notifications([])

    assert agent.identity in app._unread_completed_agent_ids


def test_reconcile_does_not_re_add_manual_cleared_agent_with_notification() -> None:
    """A manual mark suppresses notification-driven re-add to avoid surprise."""
    agent = make_agent(status="DONE")
    app = _ProjectionApp([agent])
    app._manual_unread_agent_ids.add(agent.identity)

    app._reconcile_unread_from_completion_notifications(
        [_make_notification(cl_name=agent.cl_name, raw_suffix=agent.raw_suffix)]
    )

    assert agent.identity not in app._unread_completed_agent_ids


def test_reconcile_skips_running_agent_rows() -> None:
    agent = make_agent(status="RUNNING")
    app = _ProjectionApp([agent])

    app._reconcile_unread_from_completion_notifications(
        [_make_notification(cl_name=agent.cl_name, raw_suffix=agent.raw_suffix)]
    )

    assert agent.identity not in app._unread_completed_agent_ids


def test_reconcile_disambiguates_by_raw_suffix() -> None:
    first = make_agent(name="demo", status="DONE", raw_suffix="20260507090000")
    second = make_agent(name="demo", status="DONE", raw_suffix="20260507100000")
    app = _ProjectionApp([first, second])

    app._reconcile_unread_from_completion_notifications(
        [_make_notification(cl_name="demo", raw_suffix="20260507100000")]
    )

    assert first.identity not in app._unread_completed_agent_ids
    assert second.identity in app._unread_completed_agent_ids


def test_reconcile_unrelated_notification_does_not_affect_rows() -> None:
    agent = make_agent(status="DONE")
    app = _ProjectionApp([agent])

    app._reconcile_unread_from_completion_notifications(
        [_make_notification(action="PlanApproval")]
    )

    assert agent.identity not in app._unread_completed_agent_ids


def test_cached_reconcile_patches_collapsed_clan_ancestor_only() -> None:
    member = make_agent(name="research.done", status="DONE", raw_suffix="done")
    member.agent_clan = "research"
    member.agent_clan_generation = "generation"
    complete = project_clan_tree([member])
    container = complete[0]
    app = _ProjectionApp([container])
    app._agents_with_children = complete
    app._notification_snapshot_cache = SimpleNamespace(
        notifications=[
            _make_notification(cl_name=member.cl_name, raw_suffix=member.raw_suffix)
        ]
    )

    app._reconcile_unread_from_cached_notifications()

    assert app._unread_completed_agent_ids == {member.identity}
    assert app.patch_calls == [container]
    assert app.refresh_calls == []


def test_cached_reconcile_patches_expanded_member_and_clan_ancestor() -> None:
    member = make_agent(name="research.done", status="DONE", raw_suffix="done")
    member.agent_clan = "research"
    member.agent_clan_generation = "generation"
    complete = project_clan_tree([member])
    container = complete[0]
    app = _ProjectionApp(complete)
    app._agents_with_children = complete
    app._notification_snapshot_cache = SimpleNamespace(
        notifications=[
            _make_notification(cl_name=member.cl_name, raw_suffix=member.raw_suffix)
        ]
    )

    app._reconcile_unread_from_cached_notifications()

    assert app.patch_calls == [container, member]
    assert app.refresh_calls == []


def test_poll_reconcile_prunes_absent_identity_but_not_fold_hidden_member() -> None:
    member = make_agent(name="research.done", status="DONE", raw_suffix="done")
    member.agent_clan = "research"
    member.agent_clan_generation = "generation"
    stale = make_agent(name="stale", status="DONE", raw_suffix="stale")
    complete = project_clan_tree([member])
    app = _ProjectionApp([complete[0]])
    app._agents_with_children = complete
    app._unread_completed_agent_ids.update({member.identity, stale.identity})
    app._manual_unread_agent_ids.update({member.identity, stale.identity})

    app._reconcile_unread_from_completion_notifications([])

    assert app._unread_completed_agent_ids == {member.identity}
    assert app._manual_unread_agent_ids == {member.identity}

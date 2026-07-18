"""Unread completed-agent jump navigation tests."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from unittest.mock import Mock

import pytest

from ._agent_unread_helpers import make_agent
from ._agent_unread_navigation_helpers import LeaderUnreadJumpApp, UnreadJumpApp
from sase.ace.tui.models._agent_tree import project_clan_tree
from sase.ace.tui.models._fold_filter import filter_agents_by_fold_state
from sase.ace.tui.models.agent import Agent
from sase.ace.tui.models.agent_panels import AgentPanelGroup
from sase.ace.tui.models.fold_state import FoldStateManager


@pytest.fixture(autouse=True)
def notification_dismiss(monkeypatch: pytest.MonkeyPatch) -> Mock:
    dismiss = Mock(return_value=0)
    monkeypatch.setattr(
        "sase.notifications.dismiss_agent_completion_notifications_matching_agents",
        dismiss,
    )
    return dismiss


class _CollapsedClanUnreadJumpApp(UnreadJumpApp):
    def __init__(
        self,
        complete: list[Agent],
        *,
        current_identity: tuple[object, str, str | None] | None = None,
        collapsed_panels: set[str | None] | None = None,
    ) -> None:
        self._fold_manager = FoldStateManager()
        visible, self._fold_counts = filter_agents_by_fold_state(
            complete,
            self._fold_manager,
        )
        current_idx = next(
            (
                idx
                for idx, agent in enumerate(visible)
                if agent.identity == current_identity
            ),
            0,
        )
        super().__init__(
            visible,
            current_idx=current_idx,
            with_panels=True,
            collapsed_panels=collapsed_panels,
        )
        self._agents_with_children = complete
        self._agent_search_query = ""
        self.refilter_calls = 0
        self.stale_identity: tuple[object, str, str | None] | None = None

    def _refilter_agents(self, **_kwargs: Any) -> None:
        focused_key = self._panel_group.focused_key
        self._agents, self._fold_counts = filter_agents_by_fold_state(
            self._agents_with_children,
            self._fold_manager,
        )
        if self.stale_identity is not None:
            self._agents = [
                agent for agent in self._agents if agent.identity != self.stale_identity
            ]
            self._unread_completed_agent_ids.discard(self.stale_identity)  # type: ignore[arg-type]
        self._panel_group = AgentPanelGroup.from_agents(
            self._agents,
            focused_key,
            collapsed_panel_keys=self._collapsed_panel_keys,
        )
        self.refilter_calls += 1
        self._refresh_agents_display(list_changed=True, defer_detail=True)


def test_jump_to_next_unread_done_agent_uses_completion_recency_and_wraps() -> None:
    older = make_agent(
        name="older",
        status="DONE",
        raw_suffix="older",
        stop_time=datetime(2026, 5, 7, 10, 0, 0),
    )
    newest = make_agent(
        name="newest",
        status="DONE",
        raw_suffix="newest",
        stop_time=datetime(2026, 5, 7, 12, 0, 0),
    )
    running = make_agent(
        name="running",
        status="RUNNING",
        raw_suffix="running",
        stop_time=datetime(2026, 5, 7, 13, 0, 0),
    )
    middle = make_agent(
        name="middle",
        status="FAILED",
        raw_suffix="middle",
        stop_time=datetime(2026, 5, 7, 11, 0, 0),
    )
    app = UnreadJumpApp(
        [older, newest, running, middle],
        visible=[2, 0, 3, 1],
        current_idx=2,
    )
    app._unread_completed_agent_ids.update(
        {older.identity, newest.identity, running.identity, middle.identity}
    )

    assert app._jump_to_next_unread_done_agent()
    assert app.current_idx == 1
    assert newest.identity not in app._unread_completed_agent_ids

    assert app._jump_to_next_unread_done_agent()
    assert app.current_idx == 3
    assert middle.identity not in app._unread_completed_agent_ids

    assert app._jump_to_next_unread_done_agent()
    assert app.current_idx == 0
    assert older.identity not in app._unread_completed_agent_ids

    assert not app._jump_to_next_unread_done_agent()
    assert app.current_idx == 0


def test_repeated_leader_j_walks_unread_done_agents_by_recency(
    notification_dismiss: Mock,
) -> None:
    notification_dismiss.return_value = 1
    oldest = make_agent(
        name="oldest",
        status="DONE",
        raw_suffix="oldest",
        tag="zeta",
        stop_time=datetime(2026, 5, 7, 10, 0, 0),
    )
    newest = make_agent(
        name="newest",
        status="PLAN DONE",
        raw_suffix="newest",
        tag="alpha",
        stop_time=datetime(2026, 5, 7, 13, 0, 0),
    )
    running = make_agent(
        name="running",
        status="RUNNING",
        raw_suffix="running",
        stop_time=datetime(2026, 5, 7, 14, 0, 0),
    )
    middle = make_agent(
        name="middle",
        status="FAILED",
        raw_suffix="middle",
        tag="beta",
        stop_time=datetime(2026, 5, 7, 12, 0, 0),
    )
    app = LeaderUnreadJumpApp(
        [oldest, newest, running, middle],
        current_idx=2,
    )
    app._unread_completed_agent_ids.update(
        {oldest.identity, newest.identity, middle.identity}
    )

    assert app._handle_leader_key("j") is True
    assert app.current_idx == 1
    assert app._panel_group.focused_key == "alpha"
    assert app._entry_jump_agents_anchor_stack == [("agent", 2, None)]

    assert app._handle_leader_key("comma") is True
    assert app.current_idx == 3
    assert app._panel_group.focused_key == "beta"
    assert app._entry_jump_agents_anchor_stack == [
        ("agent", 2, None),
        ("agent", 1, "alpha"),
    ]

    assert app._handle_leader_key("comma") is True
    assert app.current_idx == 0
    assert app._panel_group.focused_key == "zeta"
    assert app._entry_jump_agents_anchor_stack == [
        ("agent", 2, None),
        ("agent", 1, "alpha"),
        ("agent", 3, "beta"),
    ]

    assert app._handle_leader_key("comma") is True
    assert app.current_idx == 0
    assert app._last_leader_key == "j"
    assert app._entry_jump_agents_anchor_stack == [
        ("agent", 2, None),
        ("agent", 1, "alpha"),
        ("agent", 3, "beta"),
    ]
    assert app._unread_completed_agent_ids == set()
    assert app.notifications == ["No unread completed agents"]
    assert app.current_tab_refresh_calls == 4
    assert app.refresh_calls == [
        {"list_changed": False, "defer_detail": True},
        {"list_changed": False, "defer_detail": True},
        {"list_changed": False, "defer_detail": True},
    ]
    assert app.patch_calls == [newest, middle, oldest]
    assert notification_dismiss.call_count == 3
    assert app.notification_count_refresh_calls == 3


def test_jump_to_next_unread_done_agent_wraps_from_oldest_to_newest() -> None:
    oldest = make_agent(
        name="oldest",
        status="DONE",
        raw_suffix="oldest",
        stop_time=datetime(2026, 5, 7, 10, 0, 0),
    )
    newest = make_agent(
        name="newest",
        status="DONE",
        raw_suffix="newest",
        stop_time=datetime(2026, 5, 7, 12, 0, 0),
    )
    app = UnreadJumpApp([oldest, newest], current_idx=0)
    app._unread_completed_agent_ids.update({oldest.identity, newest.identity})

    assert app._jump_to_next_unread_done_agent()

    assert app.current_idx == 1
    assert newest.identity not in app._unread_completed_agent_ids


def test_jump_to_next_unread_done_agent_ignores_running_and_read_done() -> None:
    running = make_agent(name="running", status="RUNNING", raw_suffix="running")
    read_done = make_agent(name="read", status="DONE", raw_suffix="read")
    unread_done = make_agent(name="unread", status="DONE", raw_suffix="unread")
    app = UnreadJumpApp([running, read_done, unread_done], current_idx=0)
    app._unread_completed_agent_ids.add(unread_done.identity)

    assert app._jump_to_next_unread_done_agent()
    assert app.current_idx == 2
    assert app.patch_calls == [unread_done]


def test_jump_to_next_unread_done_agent_uses_start_time_when_stop_time_missing() -> (
    None
):
    fallback_newest = make_agent(
        name="fallback",
        status="DONE",
        raw_suffix="fallback",
        start_time=datetime(2026, 5, 7, 12, 0, 0),
        stop_time=None,
    )
    stopped_older = make_agent(
        name="stopped",
        status="DONE",
        raw_suffix="stopped",
        start_time=datetime(2026, 5, 7, 8, 0, 0),
        stop_time=datetime(2026, 5, 7, 11, 0, 0),
    )
    missing_time = make_agent(
        name="missing",
        status="FAILED",
        raw_suffix="missing",
        start_time=None,
        stop_time=None,
    )
    app = UnreadJumpApp(
        [stopped_older, missing_time, fallback_newest],
        current_idx=99,
    )
    app._unread_completed_agent_ids.update(
        {fallback_newest.identity, stopped_older.identity, missing_time.identity}
    )

    assert app._jump_to_next_unread_done_agent()
    assert app.current_idx == 2
    assert fallback_newest.identity not in app._unread_completed_agent_ids

    assert app._jump_to_next_unread_done_agent()
    assert app.current_idx == 0
    assert stopped_older.identity not in app._unread_completed_agent_ids

    assert app._jump_to_next_unread_done_agent()
    assert app.current_idx == 1
    assert missing_time.identity not in app._unread_completed_agent_ids


def test_jump_to_next_unread_done_agent_acknowledges_target_unread_state(
    notification_dismiss: Mock,
) -> None:
    notification_dismiss.return_value = 1
    done = make_agent(name="done", status="PLAN DONE")
    app = UnreadJumpApp([done])
    app._unread_completed_agent_ids.add(done.identity)

    assert app._jump_to_next_unread_done_agent()

    assert done.identity not in app._unread_completed_agent_ids
    assert app.current_attempt_number is None
    assert app.patch_calls == [done]
    assert app.refresh_calls == []
    notification_dismiss.assert_called_once_with(
        [{"cl_name": done.cl_name, "raw_suffix": done.raw_suffix}]
    )
    assert app.notification_count_refresh_calls == 1


def test_jump_to_next_unread_done_agent_falls_back_to_full_refresh() -> None:
    done = make_agent(name="done", status="FAILED")
    app = UnreadJumpApp([done], patch_result=False)
    app._unread_completed_agent_ids.add(done.identity)

    assert app._jump_to_next_unread_done_agent()

    assert done.identity not in app._unread_completed_agent_ids
    assert app.refresh_calls == [{"list_changed": True, "defer_detail": True}]


def test_jump_to_next_unread_done_agent_clears_banner_focus_and_refreshes() -> None:
    done = make_agent(name="done", status="DONE")
    app = UnreadJumpApp(
        [done],
        current_idx=0,
        stops=[("banner", ("done",)), ("agent", 0)],
    )
    app._current_group_key = ("done",)
    app._unread_completed_agent_ids.add(done.identity)

    assert app._jump_to_next_unread_done_agent()

    assert app.current_idx == 0
    assert app._current_group_key is None
    assert app._entry_jump_agents_anchor_stack == [("banner", None, ("done",))]
    assert done.identity not in app._unread_completed_agent_ids
    assert app.patch_calls == [done]
    assert app.refresh_calls == [{"list_changed": False, "defer_detail": True}]


def test_jump_to_next_unread_done_agent_starts_at_newest_from_focused_banner() -> None:
    first = make_agent(
        name="first",
        status="DONE",
        raw_suffix="first",
        stop_time=datetime(2026, 5, 7, 10, 0, 0),
    )
    second = make_agent(
        name="second",
        status="DONE",
        raw_suffix="second",
        stop_time=datetime(2026, 5, 7, 12, 0, 0),
    )
    app = UnreadJumpApp(
        [first, second],
        visible=[0, 1],
        stops=[("banner", ("group",)), ("agent", 1), ("agent", 0)],
    )
    app._current_group_key = ("group",)
    app._unread_completed_agent_ids.update({first.identity, second.identity})

    assert app._jump_to_next_unread_done_agent()

    assert app.current_idx == 1
    assert app._current_group_key is None
    assert app._unread_completed_agent_ids == {first.identity}


def test_jump_to_next_unread_done_agent_finds_non_focused_panel_row() -> None:
    focused = make_agent(name="focused", status="RUNNING", raw_suffix="focused")
    target = make_agent(
        name="target",
        status="PLAN DONE",
        raw_suffix="target",
        tag="chop",
        stop_time=datetime(2026, 5, 7, 12, 0, 0),
    )
    app = UnreadJumpApp(
        [focused, target],
        current_idx=0,
        with_panels=True,
        focused_key=None,
    )
    assert app._panel_group.panel_keys == [None, "chop"]
    assert app._panel_group.focused_idx == 0
    app._unread_completed_agent_ids.add(target.identity)

    assert app._jump_to_next_unread_done_agent()

    assert app.current_idx == 1
    assert app._panel_group.focused_idx == 1
    assert target.identity not in app._unread_completed_agent_ids
    assert app.patch_calls == [target]
    assert app.refresh_calls == [{"list_changed": False, "defer_detail": True}]


def test_jump_to_next_unread_done_agent_back_jump_restores_origin() -> None:
    origin = make_agent(name="origin", status="RUNNING", raw_suffix="origin")
    target = make_agent(
        name="target",
        status="DONE",
        raw_suffix="target",
        tag="chop",
        stop_time=datetime(2026, 5, 7, 12, 0, 0),
    )
    app = UnreadJumpApp(
        [origin, target],
        current_idx=0,
        with_panels=True,
        focused_key=None,
    )
    app._unread_completed_agent_ids.add(target.identity)

    assert app._jump_to_next_unread_done_agent()
    assert app.current_idx == 1
    assert app._panel_group.focused_idx == 1
    assert app._entry_jump_agents_anchor_stack == [("agent", 0, None)]

    assert app._restore_agents_jump_anchor()
    assert app.current_idx == 0
    assert app._panel_group.focused_idx == 0
    assert app._current_group_key is None
    assert app._entry_jump_agents_anchor_stack == []


def test_unread_jump_expands_collapsed_panel_and_selects_exact_row(
    notification_dismiss: Mock,
) -> None:
    notification_dismiss.return_value = 1
    origin = make_agent(name="origin", status="RUNNING", raw_suffix="origin")
    first_alpha = make_agent(
        name="first-alpha",
        status="RUNNING",
        raw_suffix="first-alpha",
        tag="alpha",
    )
    target = make_agent(
        name="target",
        status="DONE",
        raw_suffix="target",
        tag="alpha",
        stop_time=datetime(2026, 7, 16, 15, 0, 0),
    )
    beta = make_agent(
        name="beta",
        status="RUNNING",
        raw_suffix="beta",
        tag="beta",
    )
    app = UnreadJumpApp(
        [origin, first_alpha, target, beta],
        current_idx=0,
        with_panels=True,
        focused_key=None,
        collapsed_panels={"alpha"},
    )
    app._unread_completed_agent_ids.add(target.identity)
    assert app._panel_group.panel_keys == [None, "beta", "alpha"]

    assert app._jump_to_next_unread_done_agent()

    assert app._collapsed_panel_keys == set()
    assert app._panel_group.panel_keys == [None, "alpha", "beta"]
    assert app._panel_group.focused_key == "alpha"
    assert app.current_idx == 2
    assert app._agents[app.current_idx] is target
    assert app.current_attempt_number is None
    assert target.identity not in app._unread_completed_agent_ids
    assert app.patch_calls == []
    assert app.refresh_calls == [{"list_changed": True, "defer_detail": True}]
    assert app._entry_jump_agents_anchor_stack == [("agent", 0, None)]
    intent = app._agents_fold_state_intents[-1]
    assert intent.panel_key == "alpha"
    assert intent.collapsed is False
    notification_dismiss.assert_called_once_with(
        [{"cl_name": target.cl_name, "raw_suffix": target.raw_suffix}]
    )
    assert app.notification_count_refresh_calls == 1


def test_unread_jump_expands_manually_guarded_target_without_acknowledging(
    notification_dismiss: Mock,
) -> None:
    origin = make_agent(name="origin", status="RUNNING", raw_suffix="origin")
    target = make_agent(
        name="target",
        status="DONE",
        raw_suffix="target",
        tag="alpha",
        stop_time=datetime(2026, 7, 16, 15, 0, 0),
    )
    app = UnreadJumpApp(
        [origin, target],
        with_panels=True,
        collapsed_panels={"alpha"},
    )
    app._unread_completed_agent_ids.add(target.identity)
    app._manual_unread_agent_ids.add(target.identity)

    assert app._jump_to_next_unread_done_agent()

    assert app._collapsed_panel_keys == set()
    assert app._panel_group.focused_key == "alpha"
    assert app.current_idx == 1
    assert target.identity in app._unread_completed_agent_ids
    assert target.identity in app._manual_unread_agent_ids
    assert app.patch_calls == []
    assert app.refresh_calls == [{"list_changed": True, "defer_detail": True}]
    notification_dismiss.assert_not_called()


def test_unread_jump_history_survives_panel_repartition_back_and_forward() -> None:
    target = make_agent(
        name="target",
        status="DONE",
        raw_suffix="target",
        tag="alpha",
        stop_time=datetime(2026, 7, 16, 15, 0, 0),
    )
    beta = make_agent(
        name="beta",
        status="RUNNING",
        raw_suffix="beta",
        tag="beta",
    )
    origin = make_agent(
        name="origin",
        status="RUNNING",
        raw_suffix="origin",
        tag="gamma",
    )
    app = UnreadJumpApp(
        [target, beta, origin],
        current_idx=2,
        with_panels=True,
        focused_key="gamma",
        collapsed_panels={"alpha"},
    )
    app._unread_completed_agent_ids.add(target.identity)
    assert app._panel_group.panel_keys == ["beta", "gamma", "alpha"]

    assert app._jump_to_next_unread_done_agent()
    assert app._panel_group.panel_keys == ["alpha", "beta", "gamma"]
    assert app._entry_jump_agents_anchor_stack == [("agent", 2, "gamma")]

    assert app._restore_agents_jump_anchor()
    assert app._panel_group.focused_key == "gamma"
    assert app.current_idx == 2

    app.action_jump_to_entry_forward()
    assert app._panel_group.focused_key == "alpha"
    assert app.current_idx == 0


def test_jump_to_next_unread_done_agent_returns_false_when_no_unread_panels() -> None:
    focused = make_agent(name="focused", status="RUNNING", raw_suffix="focused")
    done = make_agent(name="done", status="DONE", raw_suffix="done", tag="chop")
    app = UnreadJumpApp(
        [focused, done],
        current_idx=0,
        with_panels=True,
        focused_key=None,
    )

    assert not app._jump_to_next_unread_done_agent()

    assert app.current_idx == 0
    assert app._panel_group.focused_idx == 0
    assert app.patch_calls == []
    assert app.refresh_calls == []


def test_unread_jump_reveals_only_most_recent_target_clan() -> None:
    origin = make_agent(name="origin", status="RUNNING", raw_suffix="origin")
    newest = make_agent(
        name="alpha.done",
        status="DONE",
        raw_suffix="alpha",
        stop_time=datetime(2026, 7, 18, 12, 0, 0),
    )
    newest.agent_clan = "alpha"
    newest.agent_clan_generation = "generation-a"
    older = make_agent(
        name="beta.done",
        status="DONE",
        raw_suffix="beta",
        stop_time=datetime(2026, 7, 18, 11, 0, 0),
    )
    older.agent_clan = "beta"
    older.agent_clan_generation = "generation-b"
    complete = project_clan_tree([origin, newest, older])
    app = _CollapsedClanUnreadJumpApp(
        complete,
        current_identity=origin.identity,
    )
    app._unread_completed_agent_ids.update({newest.identity, older.identity})

    assert app._jump_to_next_unread_done_agent()

    containers = {
        agent.agent_clan: agent for agent in complete if agent.is_clan_container
    }
    from sase.ace.tui.models._agent_tree import agent_fold_key

    assert app._fold_manager.get(agent_fold_key(containers["alpha"])).name == "EXPANDED"
    assert app._fold_manager.get(agent_fold_key(containers["beta"])).name == "COLLAPSED"
    assert app._agents[app.current_idx].identity == newest.identity
    assert newest.identity not in app._unread_completed_agent_ids
    assert older.identity in app._unread_completed_agent_ids
    assert app.refilter_calls == 1
    assert app._entry_jump_agents_anchor_stack == [("agent", 0, None)]


def test_unread_jump_expands_exact_same_name_clan_generation() -> None:
    origin = make_agent(name="origin", status="RUNNING", raw_suffix="origin")
    old = make_agent(
        name="research.old",
        status="DONE",
        raw_suffix="old",
        stop_time=datetime(2026, 7, 18, 11, 0, 0),
    )
    old.agent_clan = "research"
    old.agent_clan_generation = "old-generation"
    new = make_agent(
        name="research.new",
        status="DONE",
        raw_suffix="new",
        stop_time=datetime(2026, 7, 18, 12, 0, 0),
    )
    new.agent_clan = "research"
    new.agent_clan_generation = "new-generation"
    complete = project_clan_tree([origin, old, new])
    app = _CollapsedClanUnreadJumpApp(
        complete,
        current_identity=origin.identity,
    )
    app._unread_completed_agent_ids.update({old.identity, new.identity})

    assert app._jump_to_next_unread_done_agent()

    from sase.ace.tui.models._agent_tree import agent_fold_key

    containers = [agent for agent in complete if agent.is_clan_container]
    levels = {
        container.agent_clan_generation: app._fold_manager.get(
            agent_fold_key(container)
        ).name
        for container in containers
    }
    assert levels == {
        "old-generation": "COLLAPSED",
        "new-generation": "EXPANDED",
    }
    assert app._agents[app.current_idx].identity == new.identity


def test_unread_jump_reveals_clan_and_collapsed_tag_panel() -> None:
    origin = make_agent(name="origin", status="RUNNING", raw_suffix="origin")
    target = make_agent(
        name="research.done",
        status="DONE",
        raw_suffix="target",
        tag="alpha",
        stop_time=datetime(2026, 7, 18, 12, 0, 0),
    )
    target.agent_clan = "research"
    target.agent_clan_generation = "generation"
    app = _CollapsedClanUnreadJumpApp(
        project_clan_tree([origin, target]),
        current_identity=origin.identity,
        collapsed_panels={"alpha"},
    )
    app._unread_completed_agent_ids.add(target.identity)

    assert app._jump_to_next_unread_done_agent()

    assert app._collapsed_panel_keys == set()
    assert app._panel_group.focused_key == "alpha"
    assert app._agents[app.current_idx].identity == target.identity
    assert app.refilter_calls == 1


def test_unread_jump_lands_on_direct_family_row_but_not_inner_child() -> None:
    family = make_agent(
        name="research.family--plan-0",
        status="DONE",
        raw_suffix="family",
        stop_time=datetime(2026, 7, 18, 12, 0, 0),
    )
    family.agent_name = "research.family--plan-0"
    family.agent_family = "research.family"
    family.agent_clan = "research"
    family.agent_clan_generation = "generation"
    child = make_agent(
        name="research.family--code",
        status="DONE",
        raw_suffix="child",
        stop_time=datetime(2026, 7, 18, 13, 0, 0),
    )
    child.agent_name = "research.family--code"
    child.agent_family = "research.family"
    child.parent_timestamp = family.raw_suffix
    family.runtime_children = [child]
    complete = project_clan_tree([family, child])
    app = _CollapsedClanUnreadJumpApp(complete)
    app._unread_completed_agent_ids.update({family.identity, child.identity})

    assert app._jump_to_next_unread_done_agent()

    assert app._agents[app.current_idx].identity == family.identity
    assert child.identity in app._unread_completed_agent_ids


def test_unread_jump_does_not_reveal_member_hidden_by_inner_family_fold() -> None:
    family = make_agent(
        name="research.family--plan-0",
        status="RUNNING",
        raw_suffix="family",
    )
    family.agent_name = "research.family--plan-0"
    family.agent_family = "research.family"
    family.agent_clan = "research"
    family.agent_clan_generation = "generation"
    child = make_agent(
        name="research.family--code",
        status="DONE",
        raw_suffix="child",
        stop_time=datetime(2026, 7, 18, 13, 0, 0),
    )
    child.agent_name = "research.family--code"
    child.agent_family = "research.family"
    child.parent_timestamp = family.raw_suffix
    family.runtime_children = [child]
    app = _CollapsedClanUnreadJumpApp(project_clan_tree([family, child]))
    app._unread_completed_agent_ids.add(child.identity)

    assert not app._has_unread_completed_agent()
    assert not app._jump_to_next_unread_done_agent()
    assert app.refilter_calls == 0


def test_unread_jump_respects_active_search_filter() -> None:
    target = make_agent(
        name="research.done",
        status="DONE",
        raw_suffix="target",
        stop_time=datetime(2026, 7, 18, 12, 0, 0),
    )
    target.agent_name = "research.done"
    target.agent_clan = "research"
    target.agent_clan_generation = "generation"
    app = _CollapsedClanUnreadJumpApp(project_clan_tree([target]))
    app._agent_search_query = "name:other"
    app._agent_query_cache = None
    app._agent_query_parse_error = None
    app._agent_content_search_index = None
    app._unread_completed_agent_ids.add(target.identity)

    assert not app._has_unread_completed_agent()
    assert not app._jump_to_next_unread_done_agent()
    assert app.refilter_calls == 0


def test_unread_jump_stale_reveal_target_does_not_acknowledge(
    notification_dismiss: Mock,
) -> None:
    target = make_agent(
        name="research.done",
        status="DONE",
        raw_suffix="target",
        stop_time=datetime(2026, 7, 18, 12, 0, 0),
    )
    target.agent_clan = "research"
    target.agent_clan_generation = "generation"
    app = _CollapsedClanUnreadJumpApp(project_clan_tree([target]))
    app._unread_completed_agent_ids.add(target.identity)
    app.stale_identity = target.identity

    assert not app._jump_to_next_unread_done_agent()

    assert app.refilter_calls == 1
    notification_dismiss.assert_not_called()


def test_unread_jump_reveals_manual_target_without_acknowledging(
    notification_dismiss: Mock,
) -> None:
    target = make_agent(
        name="research.done",
        status="DONE",
        raw_suffix="target",
        stop_time=datetime(2026, 7, 18, 12, 0, 0),
    )
    target.agent_clan = "research"
    target.agent_clan_generation = "generation"
    app = _CollapsedClanUnreadJumpApp(project_clan_tree([target]))
    app._unread_completed_agent_ids.add(target.identity)
    app._manual_unread_agent_ids.add(target.identity)

    assert app._jump_to_next_unread_done_agent()

    assert app._agents[app.current_idx].identity == target.identity
    assert target.identity in app._unread_completed_agent_ids
    assert target.identity in app._manual_unread_agent_ids
    notification_dismiss.assert_not_called()


def test_unread_footer_and_jump_share_cached_clan_projection() -> None:
    target = make_agent(
        name="research.done",
        status="DONE",
        raw_suffix="target",
        stop_time=datetime(2026, 7, 18, 12, 0, 0),
    )
    target.agent_clan = "research"
    target.agent_clan_generation = "generation"
    app = _CollapsedClanUnreadJumpApp(project_clan_tree([target]))
    app._unread_completed_agent_ids.add(target.identity)
    prospective = Mock(wraps=app._prospective_clan_member_panels)
    app._prospective_clan_member_panels = prospective  # type: ignore[method-assign]

    assert app._has_unread_completed_agent()
    assert app._has_unread_completed_agent()
    assert prospective.call_count == 1

    assert app._jump_to_next_unread_done_agent()
    assert prospective.call_count == 1

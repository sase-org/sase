"""Folded-tree unread completed-agent jump navigation tests."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from unittest.mock import Mock

import pytest

from ._agent_unread_helpers import make_agent
from ._agent_unread_navigation_helpers import UnreadJumpApp
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
        focused_key: str | None = None,
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
            focused_key=focused_key,
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


def test_unread_jump_reveals_clan_and_collapsed_tribe_panel() -> None:
    origin = make_agent(name="origin", status="RUNNING", raw_suffix="origin")
    target = make_agent(
        name="research.done",
        status="DONE",
        raw_suffix="target",
        tribe="alpha",
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


def test_unread_jump_reveals_clan_from_expanded_tribe_focus() -> None:
    origin = make_agent(name="origin", status="RUNNING", raw_suffix="origin")
    target = make_agent(
        name="research.done",
        status="DONE",
        raw_suffix="target",
        tribe="alpha",
        stop_time=datetime(2026, 7, 19, 12, 0, 0),
    )
    target.agent_clan = "research"
    target.agent_clan_generation = "generation"
    app = _CollapsedClanUnreadJumpApp(
        project_clan_tree([origin, target]),
        focused_key="alpha",
    )
    app._expanded_panel_focus = True
    app._unread_completed_agent_ids.add(target.identity)

    assert app._current_agents_jump_anchor() == ("panel", "alpha")
    assert app._jump_to_next_unread_done_agent()

    assert app._agents[app.current_idx].identity == target.identity
    assert app._resolve_focused_panel() is None
    assert app.current_attempt_number is None
    assert app.refilter_calls == 1
    assert app._entry_jump_agents_anchor_stack == [("panel", "alpha")]
    assert target.identity not in app._unread_completed_agent_ids

    assert app._restore_agents_jump_anchor() is True
    assert app._resolve_focused_panel() is not None
    assert app._panel_group.focused_key == "alpha"


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

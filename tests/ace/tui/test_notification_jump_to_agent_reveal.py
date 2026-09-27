"""Reveal coverage for JumpToAgent notification and runner jumps."""

from __future__ import annotations

from typing import Any

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.actions.agents._notification_dispatch import (
    open_notification_action,
)
from sase.ace.tui.actions.agents._notification_handlers import (
    handle_jump_to_agent,
)
from sase.ace.tui.actions.agents._notification_navigation import (
    navigate_to_agent_tab,
)
from sase.ace.tui.actions.navigation._agent_reveal import AgentRevealFailure
from sase.ace.tui.actions.navigation._node_jump import NodeJumpNavigationMixin
from sase.ace.tui.models._agent_tree import agent_fold_key, project_clan_tree
from sase.ace.tui.models.agent_groups import GroupingMode, build_agent_tree
from sase.ace.tui.models.group_fold import GroupFoldRegistry
from sase.notifications import Notification
from sase.project_display_names import humanize_cl_name
from tests.ace.tui.visual._ace_png_snapshot_startup import (
    patch_startup_loaders,
    wait_for_startup,
)

from ._member_jump_navigation_helpers import JumpHarness, make_agent, make_clan


class _Harness(NodeJumpNavigationMixin, JumpHarness):
    """Production-shaped harness with tab-switch and unread tracking."""

    def __init__(self, complete: list[Any], container: Any) -> None:
        super().__init__(complete, container)
        self._agent_search_query = ""
        self.hide_non_run_agents = False
        self._hideable_agents: list[Any] = []
        self.tab_save_calls = 0
        self.tab_switch_calls: list[str] = []
        self.saved_tab_positions: dict[str, int] = {}
        self.acknowledged: list[Any] = []
        self.armed: list[Any] = []
        self.jump_calls: list[tuple[Any, str, str]] = []

    def _save_current_tab_position(self) -> None:
        self.tab_save_calls += 1
        self.saved_tab_positions[self.current_tab] = self.current_idx

    def _switch_to_tab(self, tab: str) -> None:
        self.tab_switch_calls.append(tab)
        self.current_tab = tab
        if tab == "agents" and "agents" in self.saved_tab_positions:
            saved = self.saved_tab_positions["agents"]
            self.current_idx = max(0, min(saved, len(self._agents) - 1))

    def _acknowledge_agent_unread(self, agent: Any) -> bool:
        self.acknowledged.append(agent)
        return True

    def _arm_manual_unread_after_departure(self, agent: Any | None) -> None:
        self.armed.append(agent)


def _notification(
    cl_name: str,
    *,
    raw_suffix: str | None = None,
    agent_type: str | None = None,
) -> Notification:
    action_data: dict[str, str] = {"cl_name": cl_name}
    if raw_suffix is not None:
        action_data["raw_suffix"] = raw_suffix
    if agent_type is not None:
        action_data["agent_type"] = agent_type
    return Notification(
        id="n-jump",
        timestamp="2026-09-27T12:00:00+00:00",
        sender="user-agent",
        action="JumpToAgent",
        action_data=action_data,
    )


def _collapsed_clan() -> tuple[_Harness, Any, Any]:
    complete, container = make_clan(2)
    target = container.runtime_children[1]
    app = _Harness(complete, container)
    clan_key = agent_fold_key(container)
    assert clan_key is not None
    app._fold_manager.collapse(clan_key)
    app._refilter_agents()
    app.current_idx = next(
        index
        for index, agent in enumerate(app._agents)
        if agent.identity == container.identity
    )
    return app, container, target


def test_collapsed_clan_member_is_revealed() -> None:
    app, _container, target = _collapsed_clan()
    assert all(agent.identity != target.identity for agent in app._agents)

    notification = _notification(
        "jump-test",
        raw_suffix=target.raw_suffix,
        agent_type=target.agent_type.value,
    )
    assert handle_jump_to_agent(app, notification) is True
    assert app._agents[app.current_idx].identity == target.identity
    assert app.notifications == []
    assert app._entry_jump_agents_anchor_stack != []


def test_every_layer_at_once() -> None:
    complete, container = make_clan(2, mixed_tribes=True)
    members = list(container.runtime_children)
    target = members[1]
    app = _Harness(complete, container)
    clan_key = agent_fold_key(container)
    assert clan_key is not None

    app._fold_manager.expand(clan_key)
    app._refilter_agents()
    target_idx = next(
        index
        for index, agent in enumerate(app._agents)
        if agent.identity == target.identity
    )
    target_panel_key = app._panel_keys_per_agent()[target_idx]
    target_panel_agents = [
        agent
        for index, agent in enumerate(app._agents)
        if app._panel_keys_per_agent()[index] == target_panel_key
    ]
    local_target_idx = target_panel_agents.index(app._agents[target_idx])
    tree = build_agent_tree(
        target_panel_agents,
        fold_registry=GroupFoldRegistry(),
        mode=GroupingMode.STANDARD,
    )
    target_groups = [
        entry.group.group_key
        for entry in tree
        if entry.kind == "group"
        and entry.group is not None
        and local_target_idx in entry.group.agent_indices
    ]
    registry = app._group_fold_registry.for_panel(target_panel_key)
    registry.collapse_keys(target_groups)
    app._collapsed_panel_keys.add(target_panel_key)
    app._fold_manager.collapse(clan_key)
    app._refilter_agents()
    app.current_idx = next(
        index
        for index, agent in enumerate(app._agents)
        if agent.identity == container.identity
    )

    notification = _notification(
        "jump-test",
        raw_suffix=target.raw_suffix,
        agent_type=target.agent_type.value,
    )
    assert handle_jump_to_agent(app, notification) is True

    assert app._agents[app.current_idx].identity == target.identity
    assert target_panel_key not in app._collapsed_panel_keys
    assert all(not registry.is_collapsed(key) for key in target_groups)
    assert app.group_fold_changes == [
        (target_panel_key, key, False) for key in target_groups
    ]
    assert app.panel_fold_changes == [(target_panel_key, False)]


def test_jump_from_another_tab_restores_agents_index() -> None:
    app, container, target = _collapsed_clan()
    pre_jump_idx = app.current_idx
    pre_jump_identity = app._agents[pre_jump_idx].identity
    assert pre_jump_identity == container.identity

    app._save_current_tab_position()
    app.current_tab = "artifacts"
    app.current_idx = 99

    notification = _notification(
        "jump-test",
        raw_suffix=target.raw_suffix,
        agent_type=target.agent_type.value,
    )
    assert handle_jump_to_agent(app, notification) is True

    assert app.current_tab == "agents"
    assert app._agents[app.current_idx].identity == target.identity
    assert app.tab_save_calls >= 1
    assert app.tab_switch_calls and app.tab_switch_calls[-1] == "agents"
    anchor = app._entry_jump_agents_anchor_stack[-1]
    assert anchor[0] == "agent"
    assert app._agents[anchor[1]].identity == pre_jump_identity


def test_ambiguous_legacy_payload_selects_visible_row() -> None:
    visible = make_agent("visible-top")
    clan_raw = [make_agent("hidden-member", clan="research")]
    complete = project_clan_tree([visible, *clan_raw])
    container = next(agent for agent in complete if agent.is_clan_container)
    app = _Harness(complete, visible)
    clan_key = agent_fold_key(container)
    assert clan_key is not None
    app._fold_manager.collapse(clan_key)
    app._refilter_agents()
    hidden = container.runtime_children[0]
    assert all(agent.identity != hidden.identity for agent in app._agents)
    app.current_idx = next(
        index
        for index, agent in enumerate(app._agents)
        if agent.identity == visible.identity
    )

    assert handle_jump_to_agent(app, _notification("jump-test")) is True
    assert app._agents[app.current_idx].identity == visible.identity


def test_unloaded_agent_warns_not_found() -> None:
    app, _container, _target = _collapsed_clan()
    assert handle_jump_to_agent(app, _notification("missing-agent")) is False
    expected = f"Agent '{humanize_cl_name('missing-agent')}' not found"
    assert app.notifications == [expected]


def test_handler_routes_through_node_identity_with_agent_subject() -> None:
    app, _container, target = _collapsed_clan()
    seen: list[tuple[Any, str, str]] = []
    real_jump = app._jump_to_node_identity

    def _spy(identity: Any, *, name: str, subject: str = "Node") -> bool:
        seen.append((identity, name, subject))
        return bool(real_jump(identity, name=name, subject=subject))

    app._jump_to_node_identity = _spy  # type: ignore[method-assign]
    notification = _notification(
        "jump-test",
        raw_suffix=target.raw_suffix,
        agent_type=target.agent_type.value,
    )
    assert handle_jump_to_agent(app, notification) is True
    assert seen == [(target.identity, target.display_name, "Agent")]


def test_failed_reveal_toasts_agent_subject() -> None:
    app, _container, target = _collapsed_clan()

    def _stuck(_identity: Any) -> AgentRevealFailure | None:
        return AgentRevealFailure.TARGET_NOT_VISIBLE

    app._try_reveal_agent_row = _stuck  # type: ignore[method-assign]
    notification = _notification(
        "jump-test",
        raw_suffix=target.raw_suffix,
        agent_type=target.agent_type.value,
    )
    assert handle_jump_to_agent(app, notification) is False
    assert app.notifications == ["Agent is no longer visible"]


def test_navigate_to_agent_tab_prefers_pid_and_reveals() -> None:
    visible_raw = make_agent("visible-pid")
    visible_raw.cl_name = "wanted"
    visible_raw.pid = 111
    hidden_raw = make_agent("hidden-pid", clan="research")
    hidden_raw.cl_name = "other"
    hidden_raw.pid = 222
    other_raw = make_agent("other-visible", clan="research")
    other_raw.cl_name = "other-visible"
    other_raw.pid = 333
    complete = project_clan_tree([visible_raw, hidden_raw, other_raw])
    container = next(agent for agent in complete if agent.is_clan_container)
    visible = next(agent for agent in complete if getattr(agent, "pid", None) == 111)
    hidden = next(agent for agent in complete if getattr(agent, "pid", None) == 222)
    app = _Harness(complete, visible)
    clan_key = agent_fold_key(container)
    assert clan_key is not None
    app._fold_manager.collapse(clan_key)
    app._refilter_agents()
    app.current_idx = next(
        index
        for index, agent in enumerate(app._agents)
        if agent.identity == visible.identity
    )
    assert all(agent.identity != hidden.identity for agent in app._agents)

    assert navigate_to_agent_tab(app, "wanted", pid=222) is True
    assert app._agents[app.current_idx].identity == hidden.identity


async def test_real_app_notification_jump_expands_collapsed_clan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.ace.tui.models._agent_tree import agent_fold_key as _fold_key
    from sase.ace.tui.models.fold_state import FoldLevel

    first = make_agent("member-0", clan="research")
    second = make_agent("member-1", clan="research")
    patch_startup_loaders(monkeypatch, agents=[first, second])

    async with AcePage(initial_tab="agents") as page:
        await wait_for_startup(page)
        app = page.app
        target = next(
            agent
            for agent in app._agents_with_children
            if getattr(agent, "raw_suffix", None) == second.raw_suffix
        )
        container = next(
            agent
            for agent in app._agents_with_children
            if getattr(agent, "is_clan_container", False)
        )
        fold_key = _fold_key(container)
        assert fold_key is not None
        app._fold_manager.collapse(fold_key)
        app._refilter_agents()
        assert all(agent.identity != target.identity for agent in app._agents)

        app._save_current_tab_position()
        app._switch_to_tab("artifacts")

        notification = _notification(
            "jump-test",
            raw_suffix=target.raw_suffix,
            agent_type=target.agent_type.value,
        )
        assert open_notification_action(app, notification) is True
        await page.pause()

        assert app.current_tab == "agents"
        selected = app._agents[app.current_idx]
        assert selected.identity == target.identity
        assert app._fold_manager.get(fold_key) is not FoldLevel.COLLAPSED

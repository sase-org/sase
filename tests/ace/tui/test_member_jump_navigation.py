"""Digit-key navigation for numbered clan and family member rosters."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from typing import Any, cast

import pytest

from sase.ace.tui.actions._event_keyboard import EventKeyboardMixin
from sase.ace.tui.actions.navigation._entry_jump_agents import (
    EntryJumpAgentHistoryMixin,
)
from sase.ace.tui.actions.navigation._member_jump import MemberJumpNavigationMixin
from sase.ace.tui.models import filter_agents_by_fold_state
from sase.ace.tui.models._agent_tree import agent_fold_key, project_clan_tree
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_group_fold import AgentGroupFoldRegistry
from sase.ace.tui.models.agent_groups import GroupingMode, build_agent_tree
from sase.ace.tui.models.agent_panels import (
    AgentPanelGroup,
    panel_key_per_agent,
)
from sase.ace.tui.models.fold_state import FoldLevel, FoldStateManager
from sase.ace.tui.models.group_fold import GroupFoldRegistry
from sase.ace.tui.widgets.prompt_panel._member_roster import (
    MemberJumpMap,
)


def _agent(
    name: str,
    *,
    tag: str | None = None,
    clan: str | None = None,
    family: str | None = None,
    role: str | None = None,
) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name="jump-test",
        project_file="/repos/demo/project.sase",
        status="RUNNING",
        start_time=datetime(2026, 7, 18, 12, 0, 0),
        raw_suffix=f"ts-{name}",
        agent_name=name,
        tag=tag,
        agent_clan=clan,
        agent_family=family,
        agent_family_role=role,
        role_suffix=f"--{role}" if role else None,
        plan_chain_root=role == "plan",
    )


def _jump_map(container: Agent, members: list[Agent]) -> MemberJumpMap:
    width = 1 if len(members) <= 10 else 2
    return MemberJumpMap(
        container_identity=container.identity,
        targets=tuple(
            cast(
                Any,
                SimpleNamespace(
                    number=f"{index:0{width}d}",
                    member_identity=member.identity,
                    kind="agent",
                ),
            )
            for index, member in enumerate(members)
        ),
    )


class _JumpHarness(MemberJumpNavigationMixin, EntryJumpAgentHistoryMixin):
    """In-memory production-shaped harness for fold/reveal behavior."""

    def __init__(self, complete: list[Agent], container: Agent) -> None:
        self.current_tab = "agents"
        self.current_idx = 0
        self.current_attempt_number: int | None = None
        self._agents_with_children = complete
        self._agents: list[Agent] = []
        self._fold_manager = FoldStateManager()
        self._fold_counts: dict[str, tuple[int, int]] = {}
        self._group_fold_registry = AgentGroupFoldRegistry()
        self._grouping_mode = GroupingMode.STANDARD
        self._agent_panels_grouped = False
        self._panel_group = AgentPanelGroup.from_agents([])
        self._collapsed_panel_keys: set[str | None] = set()
        self._current_group_key: tuple[str, ...] | None = None
        self._member_jump_maps: dict[tuple[Any, ...], MemberJumpMap] = {}
        self._member_jump_pending_digit: str | None = None
        self._member_jump_pending_container_identity: tuple[Any, ...] | None = None
        self._entry_jump_agents_anchor_stack: list[Any] = []
        self._entry_jump_agents_forward_anchor_stack: list[Any] = []
        self.notifications: list[str] = []
        self.footer_digits: list[str] = []
        self.footer_refreshes = 0
        self.display_refreshes: list[bool] = []
        self.group_fold_changes: list[tuple[str | None, tuple[str, ...], bool]] = []
        self.panel_fold_changes: list[tuple[str | None, bool]] = []
        self.refilter_calls = 0
        self._refilter_agents()
        self.refilter_calls = 0
        self.current_idx = next(
            index
            for index, agent in enumerate(self._agents)
            if agent.identity == container.identity
        )

    def _refilter_agents(self, **_kwargs: Any) -> None:
        self.refilter_calls += 1
        focused_key = (
            self._panel_group.focused_key
            if getattr(self._panel_group, "panel_keys", None)
            else None
        )
        self._agents, self._fold_counts = filter_agents_by_fold_state(
            self._agents_with_children,
            self._fold_manager,
        )
        self._panel_group = AgentPanelGroup.from_agents(
            self._agents,
            focused_key,
            merge_tag_panels=self._agent_panels_grouped,
        )

    def _get_selected_agent(self) -> Agent | None:
        if self._current_group_key is not None:
            return None
        if not (0 <= self.current_idx < len(self._agents)):
            return None
        return self._agents[self.current_idx]

    def _panel_keys_per_agent(self) -> list[str | None]:
        return panel_key_per_agent(
            self._agents,
            merge_tag_panels=self._agent_panels_grouped,
        )

    def _expand_agent_panel(self, panel_key: str | None) -> bool:
        if panel_key not in self._collapsed_panel_keys:
            return False
        self._collapsed_panel_keys.discard(panel_key)
        self._persist_panel_fold_change(panel_key, collapsed=False)
        return True

    def _invalidate_agent_panel_cache(self) -> None:
        pass

    def _refresh_agents_display(
        self,
        *,
        list_changed: bool = False,
        defer_detail: bool = False,
    ) -> None:
        del defer_detail
        self.display_refreshes.append(list_changed)

    def _refresh_agent_footer_bindings_only(self) -> None:
        self.footer_refreshes += 1

    def _update_member_jump_footer(self, first_digit: str) -> None:
        self.footer_digits.append(first_digit)

    def _persist_group_fold_change(
        self,
        group_key: tuple[str, ...],
        *,
        collapsed: bool,
        panel_key: str | None = None,
    ) -> None:
        self.group_fold_changes.append((panel_key, group_key, collapsed))

    def _persist_panel_fold_change(
        self,
        panel_key: str | None,
        *,
        collapsed: bool,
    ) -> None:
        self.panel_fold_changes.append((panel_key, collapsed))

    def _guard_agent_navigation_for_artifact_file_viewer(self) -> bool:
        return False

    def notify(self, message: str, **_kwargs: Any) -> None:
        self.notifications.append(message)


class _KeyEvent:
    def __init__(self, key: str, character: str | None = None) -> None:
        self.key = key
        self.character = character
        self.prevented = False
        self.stopped = False

    def prevent_default(self) -> None:
        self.prevented = True

    def stop(self) -> None:
        self.stopped = True


class _PendingKeyboardHarness(EventKeyboardMixin, MemberJumpNavigationMixin):
    """Exercise forgiving pending-key dispatch through the app handler."""

    def __init__(self) -> None:
        self.current_tab = "agents"
        self._member_jump_pending_digit: str | None = "1"
        self._member_jump_pending_container_identity = None
        self._entry_jump_mode_active = False
        self._fold_mode_active = False
        self._checkout_mode_active = False
        self._copy_mode_active = False
        self._ancestor_mode_active = False
        self._child_mode_active = False
        self._sibling_mode_active = False
        self._leader_mode_active = False
        self._bang_mode_active = False
        self._custom_mode_active = None
        self._custom_mode_prefixes: dict[str, str] = {}
        self._last_input_action: str | None = None
        self.footer_refreshes = 0

    def _record_input_event(self) -> None:
        pass

    def _refresh_agent_footer_bindings_only(self) -> None:
        self.footer_refreshes += 1


def _clan(count: int, *, mixed_tags: bool = False) -> tuple[list[Agent], Agent]:
    members = [
        _agent(
            f"member-{index}",
            clan="research",
            tag=("alpha" if index % 2 == 0 else "beta") if mixed_tags else None,
        )
        for index in range(count)
    ]
    projected = project_clan_tree(members)
    container = projected[0]
    assert container.is_clan_container
    return projected, container


def _family(*, in_clan: bool) -> tuple[list[Agent], Agent, Agent]:
    clan = "research" if in_clan else None
    root = _agent(
        "alpha--plan",
        clan=clan,
        family="alpha",
        role="plan",
    )
    child = _agent(
        "alpha--code",
        clan=clan,
        family="alpha",
        role="code",
    )
    child.parent_timestamp = root.raw_suffix
    root.followup_agents = [child]
    assert root.is_family_container_row
    projected = project_clan_tree([root, child])
    projected_root = next(
        agent for agent in projected if agent.identity == root.identity
    )
    projected_child = next(
        agent for agent in projected if agent.identity == child.identity
    )
    return projected, projected_root, projected_child


def test_single_digit_reveals_collapsed_clan_and_back_restores_container() -> None:
    complete, container = _clan(3)
    members = list(container.runtime_children)
    app = _JumpHarness(complete, container)
    app._member_jump_maps[container.identity] = _jump_map(container, members)
    clan_key = agent_fold_key(container)
    assert clan_key is not None
    assert app._fold_manager.get(clan_key) is FoldLevel.COLLAPSED

    assert app._handle_member_jump_key("1") is True

    assert app._agents[app.current_idx].identity == members[1].identity
    assert app._fold_manager.get(clan_key) is FoldLevel.EXPANDED
    assert len(app._entry_jump_agents_anchor_stack) == 1
    assert app.refilter_calls == 1
    assert app.display_refreshes == [True]

    assert app._restore_agents_jump_anchor() is True
    assert app._agents[app.current_idx].identity == container.identity


@pytest.mark.parametrize("in_clan", [False, True])
def test_family_member_jump_reveals_standalone_and_nested_chains(
    in_clan: bool,
) -> None:
    complete, root, child = _family(in_clan=in_clan)
    app = _JumpHarness(complete, complete[0] if in_clan else root)
    if in_clan:
        clan_container = complete[0]
        clan_key = agent_fold_key(clan_container)
        assert clan_key is not None
        app._fold_manager.expand(clan_key)
        app._refilter_agents()
        app.current_idx = next(
            index
            for index, agent in enumerate(app._agents)
            if agent.identity == root.identity
        )
    app._member_jump_maps[root.identity] = _jump_map(root, [root, child])

    assert app._handle_member_jump_key("1") is True

    assert app._agents[app.current_idx].identity == child.identity
    assert app._fold_manager.get(root.raw_suffix or "") is FoldLevel.EXPANDED


def test_two_digit_buffer_completion_escape_and_other_key_cancellation() -> None:
    complete, container = _clan(11)
    members = list(container.runtime_children)
    app = _JumpHarness(complete, container)
    app._member_jump_maps[container.identity] = _jump_map(container, members)

    assert app._handle_member_jump_key("1") is True
    assert app._member_jump_pending_digit == "1"
    assert app.footer_digits == ["1"]
    assert app._handle_member_jump_key("0") is True
    assert app._member_jump_pending_digit is None
    assert app._agents[app.current_idx].identity == members[10].identity

    app.current_idx = next(
        index
        for index, agent in enumerate(app._agents)
        if agent.identity == container.identity
    )
    assert app._handle_member_jump_key("0") is True
    assert app._handle_member_jump_key("escape") is True
    assert app._member_jump_pending_digit is None

    assert app._handle_member_jump_key("0") is True
    assert app._handle_member_jump_key("j") is False
    assert app._member_jump_pending_digit is None


def test_pending_other_key_is_cancelled_then_processed_normally() -> None:
    app = _PendingKeyboardHarness()
    event = _KeyEvent("j", "j")

    app.on_key(cast(Any, event))

    assert app._member_jump_pending_digit is None
    assert app.footer_refreshes == 1
    assert event.prevented is False
    assert event.stopped is False


def test_stale_map_and_missing_digit_cancel_without_moving() -> None:
    complete, container = _clan(2)
    members = list(container.runtime_children)
    app = _JumpHarness(complete, container)
    app._member_jump_maps[container.identity] = _jump_map(container, members)
    original_idx = app.current_idx

    container.runtime_children.remove(members[1])
    assert app._handle_member_jump_key("1") is True
    assert app.current_idx == original_idx
    assert app.notifications[-1] == "Member roster changed; jump cancelled"

    assert app._handle_member_jump_key("8") is True
    assert app.current_idx == original_idx
    assert app.notifications[-1] == "No member 8"


def test_jump_expands_target_group_and_different_collapsed_panel() -> None:
    complete, container = _clan(2, mixed_tags=True)
    members = list(container.runtime_children)
    target = members[1]
    app = _JumpHarness(complete, container)
    app._member_jump_maps[container.identity] = _jump_map(container, members)
    clan_key = agent_fold_key(container)
    assert clan_key is not None

    # Prime the target's rendered panel/group context, collapse those layers,
    # then return to the clan container's collapsed outer fold.
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

    assert app._handle_member_jump_key("1") is True

    assert app._agents[app.current_idx].identity == target.identity
    assert target_panel_key not in app._collapsed_panel_keys
    assert all(not registry.is_collapsed(key) for key in target_groups)
    assert app.group_fold_changes == [
        (target_panel_key, key, False) for key in target_groups
    ]
    assert app.panel_fold_changes == [(target_panel_key, False)]
    assert app.display_refreshes == [True]


def test_visible_member_jump_skips_refilter_and_structural_refresh() -> None:
    complete, container = _clan(2)
    members = list(container.runtime_children)
    app = _JumpHarness(complete, container)
    app._member_jump_maps[container.identity] = _jump_map(container, members)
    clan_key = agent_fold_key(container)
    assert clan_key is not None
    app._fold_manager.expand(clan_key)
    app._refilter_agents()
    app.refilter_calls = 0
    app.display_refreshes.clear()
    app.current_idx = next(
        idx
        for idx, agent in enumerate(app._agents)
        if agent.identity == container.identity
    )

    assert app._handle_member_jump_key("1") is True

    assert app._agents[app.current_idx].identity == members[1].identity
    assert app.refilter_calls == 0
    assert app.display_refreshes == []


def test_member_reveal_does_not_retry_internal_refilter_type_error() -> None:
    complete, container = _clan(2)
    members = list(container.runtime_children)
    app = _JumpHarness(complete, container)
    app._member_jump_maps[container.identity] = _jump_map(container, members)
    calls: list[dict[str, object]] = []

    def fail_refilter(**kwargs: object) -> None:
        calls.append(dict(kwargs))
        raise TypeError("internal refilter failure")

    app._refilter_agents = fail_refilter  # type: ignore[method-assign]

    with pytest.raises(TypeError, match="internal refilter failure"):
        app._handle_member_jump_key("1")

    assert calls == [{"refresh_content_index": False, "refresh_display": False}]


def test_member_reveal_does_not_retry_internal_display_type_error() -> None:
    complete, container = _clan(2)
    members = list(container.runtime_children)
    app = _JumpHarness(complete, container)
    app._member_jump_maps[container.identity] = _jump_map(container, members)
    calls: list[dict[str, object]] = []

    def fail_refresh(**kwargs: object) -> None:
        calls.append(dict(kwargs))
        raise TypeError("internal display failure")

    app._refresh_agents_display = fail_refresh  # type: ignore[method-assign]

    with pytest.raises(TypeError, match="internal display failure"):
        app._handle_member_jump_key("1")

    assert calls == [{"list_changed": True, "defer_detail": True}]


def test_member_reveal_does_not_retry_internal_fold_persistence_type_error() -> None:
    complete, container = _clan(2)
    members = list(container.runtime_children)
    target = members[1]
    app = _JumpHarness(complete, container)
    app._member_jump_maps[container.identity] = _jump_map(container, members)
    clan_key = agent_fold_key(container)
    assert clan_key is not None
    app._fold_manager.expand(clan_key)
    app._refilter_agents()

    target_idx = next(
        idx
        for idx, agent in enumerate(app._agents)
        if agent.identity == target.identity
    )
    target_panel_key = app._panel_keys_per_agent()[target_idx]
    panel_agents = [
        agent
        for idx, agent in enumerate(app._agents)
        if app._panel_keys_per_agent()[idx] == target_panel_key
    ]
    local_target_idx = panel_agents.index(app._agents[target_idx])
    target_groups = [
        entry.group.group_key
        for entry in build_agent_tree(
            panel_agents,
            fold_registry=GroupFoldRegistry(),
            mode=GroupingMode.STANDARD,
        )
        if entry.kind == "group"
        and entry.group is not None
        and local_target_idx in entry.group.agent_indices
    ]
    assert target_groups
    app._group_fold_registry.for_panel(target_panel_key).collapse_keys(target_groups)
    app.current_idx = next(
        idx
        for idx, agent in enumerate(app._agents)
        if agent.identity == container.identity
    )
    calls: list[tuple[tuple[str, ...], dict[str, object]]] = []

    def fail_persist(group_key: tuple[str, ...], **kwargs: object) -> None:
        calls.append((group_key, dict(kwargs)))
        raise TypeError("internal persistence failure")

    app._persist_group_fold_change = fail_persist  # type: ignore[method-assign]

    with pytest.raises(TypeError, match="internal persistence failure"):
        app._handle_member_jump_key("1")

    assert calls == [
        (
            target_groups[0],
            {"collapsed": False, "panel_key": target_panel_key},
        )
    ]

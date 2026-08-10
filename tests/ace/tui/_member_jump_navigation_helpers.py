"""Shared harnesses and builders for member jump navigation tests."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from typing import Any, cast

from sase.ace.tui.actions._event_keyboard import EventKeyboardMixin
from sase.ace.tui.actions.navigation._entry_jump_agents import (
    EntryJumpAgentHistoryMixin,
)
from sase.ace.tui.actions.navigation._member_jump import MemberJumpNavigationMixin
from sase.ace.tui.models import filter_agents_by_fold_state
from sase.ace.tui.models._agent_tree import project_clan_tree
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_tribe_summary import CollapsedAgentPanelFocus
from sase.ace.tui.models.agent_group_fold import AgentGroupFoldRegistry
from sase.ace.tui.models.agent_groups import GroupingMode
from sase.ace.tui.models.agent_panels import (
    AgentPanelGroup,
    panel_key_per_agent,
)
from sase.ace.tui.models.fold_state import FoldStateManager
from sase.ace.tui.widgets.prompt_panel._member_roster import (
    MemberJumpMap,
)


def make_agent(
    name: str,
    *,
    tribe: str | None = None,
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
        tribe=tribe,
        agent_clan=clan,
        agent_family=family,
        agent_family_role=role,
        role_suffix=f"--{role}" if role else None,
        plan_chain_root=role == "plan",
    )


def make_jump_map(container: Agent, members: list[Agent]) -> MemberJumpMap:
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
                    role="member",
                ),
            )
            for index, member in enumerate(members)
        ),
    )


def make_role_jump_map(
    container: Agent,
    targets: list[tuple[Agent, str]],
) -> MemberJumpMap:
    return MemberJumpMap(
        container_identity=container.identity,
        targets=tuple(
            cast(
                Any,
                SimpleNamespace(
                    number=str(index),
                    member_identity=agent.identity,
                    kind="agent",
                    role=role,
                ),
            )
            for index, (agent, role) in enumerate(targets)
        ),
    )


class JumpHarness(MemberJumpNavigationMixin, EntryJumpAgentHistoryMixin):
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
        self._whole_panel_focus = False
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
        self._neighbor_targets: dict[tuple[Any, ...], set[tuple[Any, ...]]] = {}
        self._dismissed_agents: set[tuple[Any, ...]] = set()
        self._dismissed_agent_objects: list[Agent] = []
        self.revived_agents: list[Agent] = []
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
            merge_tribe_panels=self._agent_panels_grouped,
        )

    def _get_selected_agent(self) -> Agent | None:
        if self._current_group_key is not None:
            return None
        if not (0 <= self.current_idx < len(self._agents)):
            return None
        return self._agents[self.current_idx]

    def _resolve_focused_collapsed_panel(self) -> CollapsedAgentPanelFocus | None:
        if not self._whole_panel_focus:
            return None
        panel_key = self._panel_group.focused_key
        if panel_key not in self._collapsed_panel_keys:
            return None
        return CollapsedAgentPanelFocus(panel_key)

    def _agents_in_focused_panel(self) -> list[Agent]:
        focused_key = self._panel_group.focused_key
        keys = self._panel_keys_per_agent()
        return [
            agent
            for index, agent in enumerate(self._agents)
            if keys[index] == focused_key
        ]

    def _panel_keys_per_agent(self) -> list[str | None]:
        return panel_key_per_agent(
            self._agents,
            merge_tribe_panels=self._agent_panels_grouped,
        )

    def _expand_agent_panel(self, panel_key: str | None) -> bool:
        if panel_key not in self._collapsed_panel_keys:
            return False
        self._collapsed_panel_keys.discard(panel_key)
        self._note_panel_fold_change(panel_key, collapsed=False)
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

    def _note_panel_fold_change(
        self,
        panel_key: str | None,
        *,
        collapsed: bool,
    ) -> None:
        self.panel_fold_changes.append((panel_key, collapsed))

    def _guard_agent_navigation_for_artifact_file_viewer(self) -> bool:
        return False

    def _agent_neighbor_index(self) -> Any:
        targets = self._neighbor_targets

        class _Index:
            def related_target_identities_for(
                self,
                identity: tuple[Any, ...],
            ) -> frozenset[tuple[Any, ...]]:
                return frozenset(targets.get(identity, ()))

        return _Index()

    def _active_dismissed_agent_objects(self) -> tuple[Agent, ...]:
        return tuple(
            agent
            for agent in self._dismissed_agent_objects
            if agent.identity in self._dismissed_agents
        )

    def _dismissed_descendant_agents(self, selected: Agent) -> tuple[Agent, ...]:
        from sase.ace.tui.models.agent_hoods import is_agent_descendant

        return tuple(
            agent
            for agent in self._active_dismissed_agent_objects()
            if is_agent_descendant(
                agent.presented_identity_name,
                selected.presented_identity_name,
            )
        )

    def _do_revive_agent(self, agent: Agent) -> None:
        self.revived_agents.append(agent)

    def notify(self, message: str, **_kwargs: Any) -> None:
        self.notifications.append(message)


class KeyEvent:
    def __init__(self, key: str, character: str | None = None) -> None:
        self.key = key
        self.character = character
        self.prevented = False
        self.stopped = False

    def prevent_default(self) -> None:
        self.prevented = True

    def stop(self) -> None:
        self.stopped = True


class PendingKeyboardHarness(EventKeyboardMixin, MemberJumpNavigationMixin):
    """Exercise forgiving pending-key dispatch through the app handler."""

    def __init__(self) -> None:
        self.current_tab = "agents"
        self._member_jump_pending_digit: str | None = "1"
        self._member_jump_pending_container_identity = None
        self._entry_jump_mode_active = False
        self._fold_mode_active = False
        self._checkout_mode_active = False
        self._saved_query_mode_active = False
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


def make_clan(count: int, *, mixed_tribes: bool = False) -> tuple[list[Agent], Agent]:
    members = [
        make_agent(
            f"member-{index}",
            clan="research",
            tribe=("alpha" if index % 2 == 0 else "beta") if mixed_tribes else None,
        )
        for index in range(count)
    ]
    projected = project_clan_tree(members)
    container = projected[0]
    assert container.is_clan_container
    return projected, container


def make_large_family(count: int) -> tuple[list[Agent], Agent, list[Agent]]:
    root = make_agent("big--0", family="big", role="plan")
    children = [
        make_agent(f"big--{index}", family="big", role="code")
        for index in range(1, count)
    ]
    for child in children:
        child.parent_timestamp = root.raw_suffix
    root.followup_agents = list(children)
    for child in children:
        child.family_container = root
    assert root.is_family_container_row
    return [root, *children], root, children


def make_family(*, in_clan: bool) -> tuple[list[Agent], Agent, Agent]:
    clan = "research" if in_clan else None
    root = make_agent(
        "alpha--plan",
        clan=clan,
        family="alpha",
        role="plan",
    )
    child = make_agent(
        "alpha--code",
        clan=clan,
        family="alpha",
        role="code",
    )
    child.parent_timestamp = root.raw_suffix
    root.followup_agents = [child]
    # Production sets this in ``sort_and_reorder`` (``_attach_family_containers``).
    child.family_container = root
    assert root.is_family_container_row
    projected = project_clan_tree([root, child])
    projected_root = next(
        agent for agent in projected if agent.identity == root.identity
    )
    projected_child = next(
        agent for agent in projected if agent.identity == child.identity
    )
    return projected, projected_root, projected_child


def select_member(app: JumpHarness, root: Agent, member: Agent) -> None:
    """Expand the family fold so a folded member row becomes selectable."""
    app._fold_manager.expand(root.raw_suffix or "")
    app._refilter_agents()
    app.current_idx = next(
        index
        for index, agent in enumerate(app._agents)
        if agent.identity == member.identity
    )

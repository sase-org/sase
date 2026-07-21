"""Shared harnesses for agents-tab fold transition tests."""

from __future__ import annotations

from datetime import datetime

from sase.ace.tui.actions.agents._folding import AgentFoldingMixin
from sase.ace.tui.actions.navigation._entry_jump_agents import (
    EntryJumpAgentHistoryMixin,
)
from sase.ace.tui.models._agent_tree import project_clan_tree
from sase.ace.tui.models._fold_filter import filter_agents_by_fold_state
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_group_fold import AgentGroupFoldRegistry
from sase.ace.tui.models.agent_panels import AgentPanelGroup
from sase.ace.tui.models.agent_tribe_summary import AgentPanelFocus
from sase.ace.tui.models.fold_state import FoldStateManager


class StubFoldApp(EntryJumpAgentHistoryMixin, AgentFoldingMixin):
    """Minimal harness mounting the fold mixin in isolation."""

    def __init__(self, agents: list[Agent], current_idx: int = 0) -> None:
        self.current_tab = "agents"
        self.current_idx = current_idx
        self._agents = agents
        self._fold_manager = FoldStateManager()
        _, self._fold_counts = filter_agents_by_fold_state(agents, self._fold_manager)
        self._group_fold_registry = AgentGroupFoldRegistry()
        self._agent_panels_grouped = False
        self._panel_group = AgentPanelGroup.from_agents(agents)
        self._current_group_key: tuple[str, ...] | None = None
        self._expanded_panel_focus = False
        self._collapsed_panel_keys: set[str | None] = set()
        self._expanded_panel_keys: set[str | None] = set()
        self._panel_selection_memory: dict[
            str | None, tuple[str, int | tuple[str, ...]]
        ] = {}
        self._entry_jump_agents_anchor_stack = []
        self._entry_jump_agents_forward_anchor_stack = []
        self.current_attempt_number: int | None = None
        self.armed_departures: list[Agent] = []
        self.acknowledged: list[Agent] = []
        self.refilter_calls = 0
        self.focus_artifact_result = False
        self.focus_artifact_calls = 0
        self._detail = None
        self.footer_refresh_calls = 0
        self.fold_selector_calls = 0
        self.panel_focus_refresh_calls = 0

    # The mixin calls these via attribute lookups.
    def _refilter_agents(self, *, prior_pos: int | None = None) -> None:
        self.refilter_calls += 1

    def _focus_tracked_artifact_file_tmux_pane(self) -> bool:
        self.focus_artifact_calls += 1
        return self.focus_artifact_result

    def _get_selected_agent(self) -> Agent | None:
        if 0 <= self.current_idx < len(self._agents):
            return self._agents[self.current_idx]
        return None

    def query_one(self, selector: str, *_args: object) -> object:
        if selector == "#agent-detail-panel" and self._detail is not None:
            return self._detail
        raise KeyError(selector)

    def _refresh_agent_footer_bindings_only(self) -> None:
        self.footer_refresh_calls += 1

    def _panel_keys_per_agent(self) -> list[str | None]:
        from sase.ace.tui.models.agent_panels import panel_key_per_agent

        return panel_key_per_agent(self._agents)

    def _remember_focused_panel_selection(
        self,
        stop: tuple[str, int | tuple[str, ...]] | None = None,
    ) -> None:
        if stop is None:
            stop = (
                ("banner", self._current_group_key)
                if self._current_group_key is not None
                else ("agent", self.current_idx)
            )
        self._panel_selection_memory[self._panel_group.focused_key] = stop

    def _resolve_focused_panel(self) -> AgentPanelFocus | None:
        key = self._panel_group.focused_key
        collapsed = key in self._collapsed_panel_keys
        if not collapsed and not self._expanded_panel_focus:
            return None
        return AgentPanelFocus(key, collapsed)

    def _activate_focused_panel(self) -> bool:
        if self._agent_panels_grouped or self._resolve_focused_panel() is not None:
            return self._resolve_focused_panel() is not None
        self._remember_focused_panel_selection()
        self._expanded_panel_focus = True
        self._current_group_key = None
        self.current_attempt_number = None
        self.panel_focus_refresh_calls += 1
        return True

    def _arm_manual_unread_after_departure(self, agent: Agent | None) -> None:
        if agent is not None:
            self.armed_departures.append(agent)

    def _acknowledge_agent_unread(self, agent: Agent) -> bool:
        self.acknowledged.append(agent)
        return True

    def action_toggle_selected_agent_panels(self) -> None:
        self.fold_selector_calls += 1


def make_agent(
    *,
    cl_name: str = "demo",
    project: str = "proj",
    agent_name: str | None = None,
    raw_suffix: str | None = None,
    agent_type: AgentType = AgentType.RUNNING,
    status: str = "RUNNING",
    tribe: str | None = None,
) -> Agent:
    return Agent(
        agent_type=agent_type,
        cl_name=cl_name,
        project_file=f"/r/{project}/proj.sase",
        status=status,
        start_time=datetime(2026, 4, 25, 12, 0, 0),
        raw_suffix=raw_suffix,
        agent_name=agent_name,
        tribe=tribe,
    )


def make_loader_shaped_aliased_plan_family() -> tuple[
    list[Agent], Agent, Agent, Agent, Agent
]:
    """Build the workflow/family suffix shape emitted by the real loader."""
    root = make_agent(
        cl_name="he",
        agent_name="he",
        raw_suffix="20260720120000",
        agent_type=AgentType.WORKFLOW,
        status="PLAN APPROVED",
    )
    root.plan_chain_root = True
    root.agent_family = "he"
    root.agent_family_role = "root"

    main = make_agent(
        cl_name="main",
        agent_name="he--plan",
        raw_suffix=root.raw_suffix,
        agent_type=AgentType.WORKFLOW,
        status="DONE",
    )
    main.parent_timestamp = root.raw_suffix
    main.parent_workflow = "ace-run"
    main.step_type = "agent"

    script = make_agent(
        cl_name="resolve",
        raw_suffix=root.raw_suffix,
        agent_type=AgentType.WORKFLOW,
        status="DONE",
    )
    script.parent_timestamp = root.raw_suffix
    script.parent_workflow = "ace-run"
    script.step_type = "bash"
    script.is_hidden_step = True

    coder = make_agent(
        cl_name="he",
        agent_name="he--code",
        raw_suffix="20260720123000",
        status="RUNNING",
    )
    coder.parent_timestamp = root.raw_suffix
    coder.agent_family = "he"
    coder.agent_family_role = "code"

    root.followup_agents.append(coder)
    root.runtime_children.extend([main, coder, script])
    agents = [root, main, coder, script]
    return agents, root, main, coder, script


def make_sequential_family(
    *,
    clan: str | None = None,
    status: str = "RUNNING",
    tribe: str | None = None,
) -> tuple[list[Agent], Agent, Agent]:
    family = make_agent(raw_suffix="family", status=status, tribe=tribe)
    family.plan_chain_root = True
    family.agent_family = "family"
    member = make_agent(raw_suffix="member", status=status)
    member.parent_timestamp = family.raw_suffix
    member.agent_family = "family"
    member.agent_family_role = "code"
    family.followup_agents.append(member)
    family.runtime_children.append(member)
    if clan is not None:
        family.agent_clan = clan
        family.agent_clan_generation = "generation"
        projected = project_clan_tree([family, member])
    else:
        projected = [family, member]
    return projected, family, member

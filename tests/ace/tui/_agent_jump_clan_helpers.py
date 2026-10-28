"""Public harnesses for Agents-tab jumps that reveal collapsed clan members."""

from __future__ import annotations

from typing import Any

from sase.ace.tui.actions.navigation._node_jump import NodeJumpNavigationMixin
from sase.ace.tui.models._agent_tree import agent_fold_key, project_clan_tree
from sase.ace.tui.models.agent import Agent

from ._member_jump_navigation_helpers import JumpHarness, make_agent, make_clan

PROJECT_CL_NAME = "gh_sase-org__sase"
CLAN_NAME = "sase-1ou"


class ClanJumpHarness(NodeJumpNavigationMixin, JumpHarness):
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
        self._agents_last_idx = self.current_idx
        self._agents_last_identity = (
            self._agents[self.current_idx].identity if self._agents else None
        )
        self._expanded_panel_focus = False
        self._link_follow_agents_tab_filtered = False

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

    def _refresh_current_tab(self) -> None:
        pass

    def refresh_link_rail(self) -> None:
        pass


def collapsed_clan(
    *,
    harness_cls: type[ClanJumpHarness] = ClanJumpHarness,
    count: int = 2,
) -> tuple[ClanJumpHarness, Any, Any]:
    """Return a harness whose target member is hidden only by a clan fold."""
    complete, container = make_clan(count)
    target = container.runtime_children[1]
    app = harness_cls(complete, container)
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


def make_realistic_agent(
    name: str,
    *,
    clan: str | None = None,
    artifacts_dir: str | None = None,
    monitor_id: str | None = None,
    pid: int | None = None,
    raw_suffix: str | None = None,
) -> Agent:
    """Build a member whose project ``cl_name`` differs from ``agent_name``."""
    agent = make_agent(name, clan=clan)
    agent.cl_name = PROJECT_CL_NAME
    agent.agent_name = name
    if artifacts_dir is not None:
        agent.artifacts_dir = artifacts_dir
    if monitor_id is not None:
        agent.monitor_id = monitor_id
    if pid is not None:
        agent.pid = pid
    if raw_suffix is not None:
        agent.raw_suffix = raw_suffix
    return agent


def realistic_collapsed_clan(
    *,
    with_sibling: bool = False,
    duplicate_name: bool = False,
    harness_cls: type[ClanJumpHarness] = ClanJumpHarness,
) -> tuple[ClanJumpHarness, Any, Any, Agent | None]:
    """Collapsed ``sase-1ou`` clan with a land member and optional sibling.

    Returns ``(app, container, hidden_target, sibling_or_none)``.
    """
    land = make_realistic_agent(
        f"{CLAN_NAME}.land",
        clan=CLAN_NAME,
        artifacts_dir=f"/{CLAN_NAME}.land",
        pid=1001,
    )
    plan = make_realistic_agent(
        f"{CLAN_NAME}.plan",
        clan=CLAN_NAME,
        artifacts_dir=f"/{CLAN_NAME}.plan",
        pid=1002,
    )
    sibling: Agent | None = None
    rows: list[Agent] = [land, plan]
    if with_sibling:
        sibling_name = f"{CLAN_NAME}.land" if duplicate_name else f"{CLAN_NAME}.other"
        sibling = make_realistic_agent(
            sibling_name,
            artifacts_dir=f"/{CLAN_NAME}.other",
            pid=2000,
            raw_suffix="ts-sibling-land" if duplicate_name else None,
        )
        rows = [sibling, land, plan]
    complete = project_clan_tree(rows)
    container = next(agent for agent in complete if agent.is_clan_container)
    target = next(
        agent
        for agent in complete
        if getattr(agent, "artifacts_dir", None) == f"/{CLAN_NAME}.land"
    )
    visible = container
    if sibling is not None:
        visible = next(
            agent
            for agent in complete
            if getattr(agent, "artifacts_dir", None) == f"/{CLAN_NAME}.other"
        )
    app = harness_cls(complete, visible)
    clan_key = agent_fold_key(container)
    assert clan_key is not None
    app._fold_manager.collapse(clan_key)
    app._refilter_agents()
    app.current_idx = next(
        index
        for index, agent in enumerate(app._agents)
        if agent.identity == visible.identity
    )
    return app, container, target, sibling

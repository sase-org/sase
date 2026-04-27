"""Jump-hint order on the Agents tab follows tree-walk render order.

The single-key jump hints next to each agent must read top-to-bottom in
``JUMP_HINT_CHARS`` order. Storage order can differ from render order
because :func:`build_agent_tree` sorts by project / name-root, so the
hint-candidate indices must come from the same tree walk the renderer
uses.
"""

from __future__ import annotations

from datetime import datetime

from sase.ace.tui.actions.navigation._advanced import AdvancedNavigationMixin
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_group_fold import AgentGroupFoldRegistry
from sase.ace.tui.models.agent_groups import build_agent_tree


class _StubApp(AdvancedNavigationMixin):
    """Minimal harness exposing ``_jump_candidate_indices`` in isolation."""

    def __init__(
        self,
        agents: list[Agent],
        *,
        collapsed: list[tuple[str, ...]] | None = None,
    ) -> None:
        self.current_tab = "agents"
        self.current_idx = 0
        self._agents = agents
        self._group_fold_registry = AgentGroupFoldRegistry()
        for key in collapsed or []:
            self._group_fold_registry.collapse(key)

    def _panel_keys_per_agent(self) -> list:
        from sase.ace.tui.models.agent_panels import panel_key_per_agent

        return panel_key_per_agent(self._agents)


def _agent(*, project: str, cl: str, name: str) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name=cl,
        project_file=f"/r/{project}/proj.gp",
        status="RUNNING",
        start_time=datetime(2026, 4, 25, 12, 0, 0),
        agent_name=name,
    )


def test_jump_indices_follow_tree_walk_order_not_storage_order() -> None:
    """Storage order is scrambled; hint indices must match tree-walk order."""
    agents = [
        _agent(project="zeta", cl="z1", name="z1"),
        _agent(project="alpha", cl="a1", name="a1"),
        _agent(project="beta", cl="b1", name="b1"),
    ]
    app = _StubApp(agents)

    indices = app._jump_candidate_indices()

    expected = [
        e.agent_idx
        for e in build_agent_tree(agents, fold_registry=app._group_fold_registry)
        if e.kind == "agent" and e.agent_idx is not None
    ]
    assert indices == expected
    # Tree-walk order is alphabetical by project: alpha (1), beta (2), zeta (0).
    assert indices == [1, 2, 0]


def test_collapsed_l0_group_omits_its_agents_from_hints() -> None:
    """Agents inside a collapsed L0 group don't receive a hint."""
    agents = [
        _agent(project="alpha", cl="a1", name="a1"),
        _agent(project="beta", cl="b1", name="b1"),
        _agent(project="beta", cl="b1", name="b2"),
    ]
    app = _StubApp(agents, collapsed=[("beta", "b1")])

    indices = app._jump_candidate_indices()

    # Only the alpha agent (index 0) survives; both beta agents are hidden.
    assert indices == [0]

"""Phase-4 level transition table tests for the agents-tab fold mixin.

Covers the boundary between the global group fold (L0..L3) and the
existing per-workflow ``FoldStateManager``: `l` should always feel like
"show me one more level" — bumping the group fold up to L3 first, then
delegating to per-workflow expansion. ``h`` reverses, collapsing the
focused workflow before retreating up the group ladder. ``L``/``H`` jump
straight to the endpoints.
"""

from __future__ import annotations

from datetime import datetime

from sase.ace.tui.actions.agents._folding import AgentFoldingMixin
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_group_fold import AgentGroupFoldState
from sase.ace.tui.models.fold_state import FoldLevel, FoldStateManager


class _StubApp(AgentFoldingMixin):
    """Minimal harness mounting the fold mixin in isolation."""

    def __init__(self, agents: list[Agent], current_idx: int = 0) -> None:
        self.current_tab = "agents"
        self.current_idx = current_idx
        self._agents = agents
        self._fold_manager = FoldStateManager()
        self._fold_counts: dict[str, tuple[int, int]] = {
            a.raw_suffix: (1, 0) for a in agents if a.raw_suffix
        }
        self._group_fold_state = AgentGroupFoldState()
        self._current_group_key: tuple[str, ...] | None = None
        self.refilter_calls = 0

    # The mixin calls these via attribute lookups.
    def _refilter_agents(self, *, prior_pos: int | None = None) -> None:
        self.refilter_calls += 1

    def _get_selected_agent(self) -> Agent | None:
        if 0 <= self.current_idx < len(self._agents):
            return self._agents[self.current_idx]
        return None


def _agent(
    *, raw_suffix: str | None = None, agent_type: AgentType = AgentType.RUNNING
) -> Agent:
    return Agent(
        agent_type=agent_type,
        cl_name="demo",
        project_file="/r/proj.gp",
        status="RUNNING",
        start_time=datetime(2026, 4, 25, 12, 0, 0),
        raw_suffix=raw_suffix,
        tag="alpha",
    )


def test_l_steps_group_fold_when_below_l3() -> None:
    app = _StubApp([_agent()])
    app._group_fold_state.level = 0

    app.action_expand_or_layout()
    assert app._group_fold_state.level == 1
    app.action_expand_or_layout()
    assert app._group_fold_state.level == 2
    app.action_expand_or_layout()
    assert app._group_fold_state.level == 3
    # Past L3 the workflow fold logic kicks in but this agent isn't a
    # workflow — no further state change.
    app.action_expand_or_layout()
    assert app._group_fold_state.level == 3


def test_l_at_l3_advances_per_workflow_fold() -> None:
    parent = _agent(raw_suffix="ts1", agent_type=AgentType.WORKFLOW)
    app = _StubApp([parent])
    app._group_fold_state.level = 3

    assert app._fold_manager.get("ts1") == FoldLevel.COLLAPSED
    app.action_expand_or_layout()
    assert app._fold_manager.get("ts1") == FoldLevel.EXPANDED
    app.action_expand_or_layout()
    assert app._fold_manager.get("ts1") == FoldLevel.FULLY_EXPANDED
    # Group fold doesn't move in either case.
    assert app._group_fold_state.level == 3


def test_h_collapses_workflow_first_then_steps_group_down() -> None:
    parent = _agent(raw_suffix="ts1", agent_type=AgentType.WORKFLOW)
    app = _StubApp([parent])
    app._group_fold_state.level = 3
    app._fold_manager.expand("ts1")  # to EXPANDED

    # First `h` collapses the workflow (group level stays at 3).
    app.action_hooks_or_collapse()
    assert app._fold_manager.get("ts1") == FoldLevel.COLLAPSED
    assert app._group_fold_state.level == 3

    # Now `h` retreats one group level (no workflow expanded).
    app.action_hooks_or_collapse()
    assert app._group_fold_state.level == 2
    app.action_hooks_or_collapse()
    assert app._group_fold_state.level == 1
    app.action_hooks_or_collapse()
    assert app._group_fold_state.level == 0
    # Floor: no further change.
    app.action_hooks_or_collapse()
    assert app._group_fold_state.level == 0


def test_capital_l_jumps_to_full_expansion() -> None:
    parent = _agent(raw_suffix="ts1", agent_type=AgentType.WORKFLOW)
    app = _StubApp([parent])
    app._group_fold_state.level = 0

    app.action_expand_all_folds()
    assert app._group_fold_state.level == 3
    assert app._fold_manager.get("ts1") == FoldLevel.FULLY_EXPANDED


def test_capital_h_jumps_to_full_collapse() -> None:
    parent = _agent(raw_suffix="ts1", agent_type=AgentType.WORKFLOW)
    app = _StubApp([parent])
    app._group_fold_state.level = 3
    app._fold_manager.expand("ts1")
    app._fold_manager.expand("ts1")  # FULLY_EXPANDED

    app.action_hooks_or_collapse_all()
    assert app._group_fold_state.level == 0
    assert app._fold_manager.get("ts1") == FoldLevel.COLLAPSED


def test_group_fold_changes_snap_focus_to_ancestor_banner() -> None:
    """Below L3 the focused agent is hidden — snap to nearest visible banner."""
    app = _StubApp([_agent()])
    app._group_fold_state.level = 3
    app.current_idx = 0

    app.action_hooks_or_collapse()  # 3 -> 2
    assert app._group_fold_state.level == 2
    # At L2 the agent is hidden — snap-to-ancestor populated current_group_key.
    assert app._current_group_key is not None
    # Returning to L3 clears it again.
    app.action_expand_or_layout()
    assert app._group_fold_state.level == 3
    assert app._current_group_key is None

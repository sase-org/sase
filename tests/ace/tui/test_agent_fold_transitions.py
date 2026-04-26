"""Per-group transition tests for the agents-tab fold mixin.

Covers the boundary between the per-group :class:`AgentGroupFoldRegistry`
and the existing per-workflow :class:`FoldStateManager`: ``l`` expands
the focused group (or runs per-workflow expansion when an agent is
focused inside an already-expanded chain); ``h`` collapses the focused
workflow first, then the focused group; ``L``/``H`` jump straight to
"everything visible" / "every group collapsed".
"""

from __future__ import annotations

from datetime import datetime

from sase.ace.tui.actions.agents._folding import AgentFoldingMixin
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_group_fold import AgentGroupFoldRegistry
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
        self._group_fold_registry = AgentGroupFoldRegistry()
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
    *,
    cl_name: str = "demo",
    project: str = "proj",
    agent_name: str | None = None,
    raw_suffix: str | None = None,
    agent_type: AgentType = AgentType.RUNNING,
) -> Agent:
    return Agent(
        agent_type=agent_type,
        cl_name=cl_name,
        project_file=f"/r/{project}/proj.gp",
        status="RUNNING",
        start_time=datetime(2026, 4, 25, 12, 0, 0),
        raw_suffix=raw_suffix,
        agent_name=agent_name,
    )


def test_h_on_agent_collapses_only_its_group() -> None:
    """Two projects A + B; pressing `h` while focused in A leaves B untouched."""
    a = _agent(cl_name="cl-a", project="projA")
    b = _agent(cl_name="cl-b", project="projB")
    app = _StubApp([a, b], current_idx=0)

    app.action_hooks_or_collapse()  # focus is on agent in projA
    assert app._group_fold_registry.is_collapsed(("projA", "cl-a")) is True
    assert app._group_fold_registry.is_collapsed(("projB", "cl-b")) is False
    # Focus snapped onto the now-visible projA banner.
    assert app._current_group_key == ("projA", "cl-a")


def test_h_inside_l1_collapses_l1_then_parent_l0() -> None:
    """Focus inside an L1: first `h` collapses the L1, second collapses L0."""
    a = _agent(agent_name="coder.claude")
    b = _agent(agent_name="coder.codex")
    app = _StubApp([a, b], current_idx=0)
    l1 = ("proj", "demo", "coder")
    l0 = ("proj", "demo")

    app.action_hooks_or_collapse()
    assert app._group_fold_registry.is_collapsed(l1) is True
    assert app._group_fold_registry.is_collapsed(l0) is False
    assert app._current_group_key == l1

    app.action_hooks_or_collapse()
    assert app._group_fold_registry.is_collapsed(l0) is True
    assert app._current_group_key == l0


def test_l_on_collapsed_l1_banner_expands_only_that_l1() -> None:
    """`l` while focused on a collapsed L1 expands only that group."""
    a = _agent(agent_name="coder.claude")
    b = _agent(agent_name="coder.codex")
    c = _agent(agent_name="planner.claude")
    d = _agent(agent_name="planner.codex")
    app = _StubApp([a, b, c, d], current_idx=0)
    coder = ("proj", "demo", "coder")
    planner = ("proj", "demo", "planner")
    app._group_fold_registry.collapse(coder)
    app._group_fold_registry.collapse(planner)
    app._current_group_key = coder

    app.action_expand_or_layout()
    assert app._group_fold_registry.is_collapsed(coder) is False
    assert app._group_fold_registry.is_collapsed(planner) is True


def test_capital_l_expands_every_group() -> None:
    a = _agent(cl_name="cl-a", project="projA")
    b = _agent(cl_name="cl-b", project="projB")
    app = _StubApp([a, b])
    app._group_fold_registry.collapse(("projA", "cl-a"))
    app._group_fold_registry.collapse(("projB", "cl-b"))

    app.action_expand_all_folds()
    assert app._group_fold_registry.collapsed == set()
    assert app._current_group_key is None


def test_capital_h_collapses_every_group_and_workflow() -> None:
    parent = _agent(raw_suffix="ts1", agent_type=AgentType.WORKFLOW)
    app = _StubApp([parent])
    app._fold_manager.expand("ts1")
    app._fold_manager.expand("ts1")  # FULLY_EXPANDED

    app.action_hooks_or_collapse_all()
    assert app._fold_manager.get("ts1") == FoldLevel.COLLAPSED
    # Every project key the agent set produces is now collapsed.
    assert ("proj", "demo") in app._group_fold_registry.collapsed


def test_per_workflow_h_runs_before_group_collapse() -> None:
    """Per-workflow ``h`` beats group collapse for an expanded workflow."""
    parent = _agent(raw_suffix="ts1", agent_type=AgentType.WORKFLOW)
    app = _StubApp([parent])
    app._fold_manager.expand("ts1")  # EXPANDED

    app.action_hooks_or_collapse()
    # Workflow collapsed; group registry untouched.
    assert app._fold_manager.get("ts1") == FoldLevel.COLLAPSED
    assert app._group_fold_registry.collapsed == set()


def test_h_then_l_round_trip_clears_group_focus() -> None:
    """After `h` snaps to the banner, `l` re-expands and clears banner focus."""
    a = _agent(cl_name="cl-a", project="projA")
    app = _StubApp([a], current_idx=0)
    key = ("projA", "cl-a")

    app.action_hooks_or_collapse()
    assert app._current_group_key == key
    assert app._group_fold_registry.is_collapsed(key) is True

    app.action_expand_or_layout()
    assert app._group_fold_registry.is_collapsed(key) is False
    # Banner stopped being selectable — focus moved off it.
    assert app._current_group_key is None

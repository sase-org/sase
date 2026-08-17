"""Tests for filter_agents_by_fold_state and _compute_fold_annotation."""

from sase.ace.tui.actions.agents._loading_compute import (
    PreparedApplySelectionInputs,
    PreparedApplySnapshot,
    _filter_agents_by_fold_snapshot,
    prepare_loaded_agents_worker_boundary,
)
from sase.ace.tui.models._agent_tree import agent_fold_key, project_clan_tree
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models._fold_filter import filter_agents_by_fold_state
from sase.ace.tui.models.fold_state import FoldLevel, FoldStateManager
from sase.ace.tui.widgets.agent_list import _compute_fold_annotation


def _make_parent(raw_suffix: str, cl_name: str = "test_cl") -> Agent:
    """Create a workflow parent agent."""
    return Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name=cl_name,
        project_file="/tmp/test.sase",
        status="RUNNING",
        start_time=None,
        raw_suffix=raw_suffix,
    )


def _make_child(
    parent_timestamp: str,
    step_name: str = "step",
    is_hidden: bool = False,
) -> Agent:
    """Create a workflow child agent."""
    return Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name=step_name,
        project_file="/tmp/test.sase",
        status="DONE",
        start_time=None,
        parent_workflow="test-workflow",
        parent_timestamp=parent_timestamp,
        step_name=step_name,
        is_hidden_step=is_hidden,
        raw_suffix=parent_timestamp,
    )


def _make_appears_as_agent(raw_suffix: str) -> Agent:
    """Create a workflow that appears as a regular agent."""
    return Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="agent_workflow",
        project_file="/tmp/test.sase",
        status="RUNNING",
        start_time=None,
        raw_suffix=raw_suffix,
        appears_as_agent=True,
    )


def test_expanded_shows_non_hidden_children() -> None:
    """Test EXPANDED state shows non-hidden children only."""
    parent = _make_parent("ts1")
    child1 = _make_child("ts1", "step1")
    child2 = _make_child("ts1", "step2", is_hidden=True)
    agents = [parent, child1, child2]

    mgr = FoldStateManager()
    mgr.expand("ts1")  # COLLAPSED -> EXPANDED
    filtered, counts = filter_agents_by_fold_state(agents, mgr)

    assert len(filtered) == 2
    assert filtered[0] is parent
    assert filtered[1] is child1
    assert counts["ts1"] == (1, 1)  # 1 non-hidden, 1 hidden


# --- Tests for _compute_fold_annotation ---


def test_annotation_collapsed_hidden_children_only() -> None:
    """Test COLLAPSED annotation shows total step count when only hidden children exist."""
    parent = _make_parent("ts1")
    fold_counts = {"ts1": (0, 5)}
    result = _compute_fold_annotation(parent, fold_counts, set())
    assert result == " ×5"


def test_annotation_collapsed_shows_total() -> None:
    """Test COLLAPSED annotation shows total (non_hidden + hidden) step count."""
    parent = _make_parent("ts1")
    fold_counts = {"ts1": (2, 3)}
    result = _compute_fold_annotation(parent, fold_counts, set())
    assert result == " ×5"


def test_annotation_expanded_hidden_remaining() -> None:
    """Test EXPANDED annotation shows total and hidden count."""
    parent = _make_parent("ts1")
    fold_counts = {"ts1": (2, 3)}
    visible = {"ts1"}
    result = _compute_fold_annotation(parent, fold_counts, visible)
    assert result == " ×5 −3"


def test_annotation_expanded_no_hidden() -> None:
    """Test EXPANDED annotation is empty when no hidden children exist."""
    parent = _make_parent("ts1")
    fold_counts = {"ts1": (3, 0)}
    visible = {"ts1"}
    result = _compute_fold_annotation(parent, fold_counts, visible)
    assert result == ""


def test_annotation_fully_expanded_shows_hidden_count() -> None:
    """Test FULLY_EXPANDED annotation shows total and revealed hidden count."""
    parent = _make_parent("ts1")
    fold_counts = {"ts1": (2, 3)}
    visible = {"ts1"}
    fully_expanded = {"ts1"}
    result = _compute_fold_annotation(parent, fold_counts, visible, fully_expanded)
    assert result == " ×5 +3"


def test_annotation_no_fold_counts() -> None:
    """Test returns empty when fold_counts is None."""
    parent = _make_parent("ts1")
    result = _compute_fold_annotation(parent, None, set())
    assert result == ""


def test_annotation_zero_total_children() -> None:
    """Test returns empty when total children is zero."""
    parent = _make_parent("ts1")
    fold_counts = {"ts1": (0, 0)}
    result = _compute_fold_annotation(parent, fold_counts, set())
    assert result == ""


# --- Anonymous workflow fold annotation suppression tests ---


def _make_anonymous_parent(raw_suffix: str) -> Agent:
    """Create an anonymous workflow parent that appears as agent."""
    return Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="test_cl",
        project_file="/tmp/test.sase",
        status="RUNNING",
        start_time=None,
        raw_suffix=raw_suffix,
        appears_as_agent=True,
        is_anonymous=True,
    )


def test_hidden_only_children_hides_parent() -> None:
    """Test parent is filtered out when all children are hidden."""
    parent = _make_parent("ts1")
    child1 = _make_child("ts1", "step1", is_hidden=True)
    child2 = _make_child("ts1", "step2", is_hidden=True)
    agents = [parent, child1, child2]

    mgr = FoldStateManager()
    filtered, counts = filter_agents_by_fold_state(agents, mgr)

    # Both parent and children should be removed
    assert len(filtered) == 0
    assert counts["ts1"] == (0, 2)


def test_mixed_children_keeps_parent() -> None:
    """Test parent remains when at least one child is non-hidden."""
    parent = _make_parent("ts1")
    child1 = _make_child("ts1", "step1")
    child2 = _make_child("ts1", "step2", is_hidden=True)
    agents = [parent, child1, child2]

    mgr = FoldStateManager()
    filtered, counts = filter_agents_by_fold_state(agents, mgr)

    # Parent should remain (collapsed by default, children not shown)
    assert len(filtered) == 1
    assert filtered[0] is parent
    assert counts["ts1"] == (1, 1)


def test_orphan_workflow_child_is_dropped_even_when_expanded() -> None:
    """A stale fold state must not render a child whose parent is absent."""
    child = _make_child("missing-parent", "step1")
    agents = [child]

    mgr = FoldStateManager()
    mgr.expand("missing-parent")
    filtered, counts = filter_agents_by_fold_state(agents, mgr)

    assert filtered == []
    assert counts == {}


def test_fold_snapshot_matches_live_fold_manager() -> None:
    """The prepared boundary must not need a live mutable fold manager."""
    parent = _make_parent("ts1")
    child1 = _make_child("ts1", "step1")
    child2 = _make_child("ts1", "step2", is_hidden=True)
    agents = [parent, child1, child2]

    mgr = FoldStateManager()
    mgr.expand("ts1")

    expected_agents, expected_counts = filter_agents_by_fold_state(agents, mgr)
    snapshot_agents, snapshot_counts = _filter_agents_by_fold_snapshot(
        agents, mgr.snapshot()
    )

    assert snapshot_agents == expected_agents
    assert snapshot_counts == expected_counts


def _make_prepared_snapshot(
    fold_levels: dict[str, FoldLevel],
) -> PreparedApplySnapshot:
    return PreparedApplySnapshot(
        cached_agents_with_children=[],
        dismissed_agents=set(),
        agents_seen_complete_history=False,
        hide_non_run_agents=False,
        load_state=None,
        fold_levels=fold_levels,
        selection=PreparedApplySelectionInputs(
            on_agents_tab=False,
            selected_identity=None,
            prior_visual_row=None,
        ),
    )


def test_worker_boundary_fold_levels_match_live_fold_manager() -> None:
    """Worker-prepared fold filtering must match the live manager semantics."""
    for level in (
        FoldLevel.COLLAPSED,
        FoldLevel.EXPANDED,
        FoldLevel.FULLY_EXPANDED,
    ):
        parent = _make_parent(f"ts-{level.value}")
        assert parent.raw_suffix is not None
        child = _make_child(parent.raw_suffix, "step1")
        hidden_child = _make_child(parent.raw_suffix, "step2", is_hidden=True)
        agents = [parent, child, hidden_child]

        mgr = FoldStateManager()
        if level != FoldLevel.COLLAPSED:
            mgr.expand(parent.raw_suffix)
            if level == FoldLevel.FULLY_EXPANDED:
                mgr.expand(parent.raw_suffix)

        expected_agents, expected_counts = filter_agents_by_fold_state(agents, mgr)
        boundary = prepare_loaded_agents_worker_boundary(
            list(agents),
            [],
            set(),
            False,
            _make_prepared_snapshot(mgr.snapshot()),
        )

        assert boundary.fold.unfiltered_agents == agents
        assert boundary.fold.visible_agents == expected_agents
        assert boundary.fold.fold_counts == expected_counts


def test_worker_boundary_filters_orphans_and_hidden_only_parents() -> None:
    """Worker fold filtering must preserve edge-case filtering semantics."""
    hidden_only_parent = _make_parent("hidden-only")
    hidden_only_child = _make_child("hidden-only", "hidden", is_hidden=True)
    orphan = _make_child("missing-parent", "orphan")
    agents = [hidden_only_parent, hidden_only_child, orphan]

    mgr = FoldStateManager()
    mgr.expand("missing-parent")

    expected_agents, expected_counts = filter_agents_by_fold_state(agents, mgr)
    boundary = prepare_loaded_agents_worker_boundary(
        list(agents),
        [],
        set(),
        False,
        _make_prepared_snapshot(mgr.snapshot()),
    )

    assert boundary.fold.visible_agents == expected_agents
    assert boundary.fold.fold_counts == expected_counts


def _make_family_starter_monitor() -> tuple[Agent, Agent, Agent, Agent]:
    """Clan -> family root -> starter -> disk-shaped monitor."""
    family = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="fam",
        project_file="/tmp/test.sase",
        status="DONE",
        start_time=None,
        raw_suffix="family",
        agent_name="fam",
        agent_family="fam",
        agent_family_role="root",
        agent_clan="clan",
        agent_clan_generation="gen",
    )
    starter = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="fam--2",
        project_file="/tmp/test.sase",
        status="DONE",
        start_time=None,
        raw_suffix="starter",
        parent_timestamp=family.raw_suffix,
        agent_name="fam--2",
        agent_family="fam",
        agent_family_role="code",
        role_suffix="--2",
    )
    monitor = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="fam--mon-1",
        project_file="/tmp/test.sase",
        status="MONITORING",
        start_time=None,
        raw_suffix="monitor",
        parent_timestamp=starter.raw_suffix,
        agent_name="fam--mon-1",
        agent_family="fam",
        agent_family_role="monitor",
        role_suffix="--mon-1",
        monitor_id="m1",
        monitor_state="running",
    )
    projected = project_clan_tree([family, starter, monitor])
    return projected[0], family, starter, monitor


def test_monitor_is_visible_whenever_starter_is_visible() -> None:
    container, family, starter, monitor = _make_family_starter_monitor()
    clan_key = agent_fold_key(container)
    family_key = agent_fold_key(family)
    starter_key = agent_fold_key(starter)
    assert clan_key is not None
    assert family_key is not None
    assert starter_key is not None

    mgr = FoldStateManager()
    mgr.expand(clan_key)
    mgr.expand(family_key)

    visible, counts = filter_agents_by_fold_state(
        [container, family, starter, monitor], mgr
    )

    assert visible == [container, family, starter, monitor]
    assert starter_key not in counts
    assert counts[family_key] == (1, 0)


def test_monitor_hides_when_family_or_clan_is_collapsed() -> None:
    container, family, starter, monitor = _make_family_starter_monitor()
    clan_key = agent_fold_key(container)
    family_key = agent_fold_key(family)
    assert clan_key is not None
    assert family_key is not None

    mgr = FoldStateManager()
    collapsed_clan, _ = filter_agents_by_fold_state(
        [container, family, starter, monitor], mgr
    )
    assert collapsed_clan == [container]
    assert monitor not in collapsed_clan

    mgr.expand(clan_key)
    collapsed_family, _ = filter_agents_by_fold_state(
        [container, family, starter, monitor], mgr
    )
    assert collapsed_family == [container, family]
    assert monitor not in collapsed_family

    mgr.expand(family_key)
    expanded, _ = filter_agents_by_fold_state(
        [container, family, starter, monitor], mgr
    )
    assert monitor in expanded


def test_annotation_suppressed_anonymous_single_prompt() -> None:
    """Test annotation suppressed for collapsed anonymous single-prompt workflow."""
    parent = _make_anonymous_parent("ts1")
    fold_counts = {"ts1": (1, 0)}  # total == 1
    result = _compute_fold_annotation(parent, fold_counts, set())
    assert result == ""

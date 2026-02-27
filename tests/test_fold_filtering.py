"""Tests for filter_agents_by_fold_state and _compute_fold_annotation."""

from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_loader import filter_agents_by_fold_state
from sase.ace.tui.models.fold_state import FoldStateManager
from sase.ace.tui.widgets.agent_list import _compute_fold_annotation


def _make_parent(raw_suffix: str, cl_name: str = "test_cl") -> Agent:
    """Create a workflow parent agent."""
    return Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name=cl_name,
        project_file="/tmp/test.gp",
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
        project_file="/tmp/test.gp",
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
        project_file="/tmp/test.gp",
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
    """Test COLLAPSED annotation shows '(+N steps)' when only hidden children exist."""
    parent = _make_parent("ts1")
    fold_counts = {"ts1": (0, 5)}
    result = _compute_fold_annotation(parent, fold_counts, set())
    assert result == " (+5 steps)"


def test_annotation_expanded_hidden_remaining() -> None:
    """Test EXPANDED annotation shows '(+N hidden)' for remaining hidden children."""
    parent = _make_parent("ts1")
    fold_counts = {"ts1": (2, 3)}
    visible = {"ts1"}
    result = _compute_fold_annotation(parent, fold_counts, visible)
    assert result == " (+3 hidden)"


def test_annotation_expanded_no_hidden() -> None:
    """Test EXPANDED annotation is empty when no hidden children exist."""
    parent = _make_parent("ts1")
    fold_counts = {"ts1": (3, 0)}
    visible = {"ts1"}
    result = _compute_fold_annotation(parent, fold_counts, visible)
    assert result == ""


def test_annotation_fully_expanded_shows_hidden_count() -> None:
    """Test FULLY_EXPANDED annotation shows '(+N shown)' for hidden children."""
    parent = _make_parent("ts1")
    fold_counts = {"ts1": (2, 3)}
    visible = {"ts1"}
    fully_expanded = {"ts1"}
    result = _compute_fold_annotation(parent, fold_counts, visible, fully_expanded)
    assert result == " (+3 shown)"


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
        project_file="/tmp/test.gp",
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


def test_annotation_suppressed_anonymous_single_prompt() -> None:
    """Test annotation suppressed for collapsed anonymous single-prompt workflow."""
    parent = _make_anonymous_parent("ts1")
    fold_counts = {"ts1": (1, 0)}  # total == 1
    result = _compute_fold_annotation(parent, fold_counts, set())
    assert result == ""

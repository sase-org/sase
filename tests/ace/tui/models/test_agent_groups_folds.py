"""Per-group fold builds, key enumeration, summaries, and ancestor lookup."""

from __future__ import annotations

from sase.ace.tui.models.agent import Agent
from sase.ace.tui.models.agent_group_fold import AgentGroupFoldRegistry
from sase.ace.tui.models.agent_groups import (
    GroupRow,
    banner_summary_text,
    build_agent_tree,
    compute_banner_summary,
    enumerate_group_keys,
    find_visible_ancestor_banner,
)

from ._agent_groups_helpers import _agent, _kinds

# --- Per-group fold builds ---


def test_collapsed_l0_hides_descendants_but_emits_banner() -> None:
    """A collapsed L0 banner appears with `is_collapsed=True` and no children."""
    registry = AgentGroupFoldRegistry()
    registry.collapse(("projA",))
    entries = build_agent_tree(
        [
            _agent(cl_name="a", project_file="/r/projA/proj.gp"),
            _agent(cl_name="b", project_file="/r/projB/proj.gp"),
        ],
        fold_registry=registry,
    )
    proj_banners = [
        e
        for e in entries
        if e.kind == "group" and e.group.level == 0  # type: ignore[union-attr]
    ]
    assert len(proj_banners) == 2
    proj_a = proj_banners[0]
    assert proj_a.group is not None and proj_a.group.is_collapsed is True
    proj_b = proj_banners[1]
    assert proj_b.group is not None and proj_b.group.is_collapsed is False
    # No agent under projA, agent 1 under projB.
    agent_indices = [e.agent_idx for e in entries if e.kind == "agent"]
    assert agent_indices == [1]


def test_collapsed_changespec_hides_only_its_agents() -> None:
    """A collapsed L1 ChangeSpec banner suppresses only its own agents."""
    registry = AgentGroupFoldRegistry()
    registry.collapse(("proj", "fix-a"))
    entries = build_agent_tree(
        [
            _agent(cl_name="fix-a", project_file="/r/proj/proj.gp", agent_name="x"),
            _agent(cl_name="fix-b", project_file="/r/proj/proj.gp", agent_name="y"),
        ],
        fold_registry=registry,
    )
    agent_indices = [e.agent_idx for e in entries if e.kind == "agent"]
    assert agent_indices == [1]


def test_collapsed_name_root_at_level_two_hides_only_its_agents() -> None:
    """A collapsed L2 name-root banner suppresses only its own agents."""
    registry = AgentGroupFoldRegistry()
    registry.collapse(("proj", "demo", "coder"))
    entries = build_agent_tree(
        [
            _agent(
                cl_name="demo",
                project_file="/r/proj/proj.gp",
                agent_name="coder.claude",
            ),
            _agent(
                cl_name="demo", project_file="/r/proj/proj.gp", agent_name="coder.codex"
            ),
            _agent(
                cl_name="demo",
                project_file="/r/proj/proj.gp",
                agent_name="planner.claude",
            ),
            _agent(
                cl_name="demo",
                project_file="/r/proj/proj.gp",
                agent_name="planner.codex",
            ),
        ],
        fold_registry=registry,
    )
    levels = [e.group.level for e in entries if e.kind == "group"]  # type: ignore[union-attr]
    # L0 + L1 (demo) + collapsed coder L2 + planner L2.
    assert levels == [0, 1, 2, 2]
    agent_indices = [e.agent_idx for e in entries if e.kind == "agent"]
    # Only planner's agents appear.
    assert agent_indices == [2, 3]


def test_collapsed_name_prefix_hides_only_its_agents() -> None:
    """A collapsed prefix subgroup suppresses only that prefix's members."""
    registry = AgentGroupFoldRegistry()
    registry.collapse(("proj", "demo", "sase-42", "sase-42.2"))
    entries = build_agent_tree(
        [
            _agent(
                cl_name="demo",
                project_file="/r/proj/proj.gp",
                agent_name="sase-42.2",
            ),
            _agent(
                cl_name="demo",
                project_file="/r/proj/proj.gp",
                agent_name="sase-42.1.1",
            ),
            _agent(
                cl_name="demo",
                project_file="/r/proj/proj.gp",
                agent_name="sase-42.1.2",
            ),
            _agent(
                cl_name="demo",
                project_file="/r/proj/proj.gp",
                agent_name="sase-42.2.1",
            ),
            _agent(
                cl_name="demo",
                project_file="/r/proj/proj.gp",
                agent_name="sase-42.2.2",
            ),
        ],
        fold_registry=registry,
    )
    collapsed = [
        e.group  # type: ignore[union-attr]
        for e in entries
        if e.kind == "group"
        and e.group is not None
        and e.group.group_key == ("proj", "demo", "sase-42", "sase-42.2")
    ]
    assert len(collapsed) == 1
    assert collapsed[0].is_collapsed is True
    assert [e.agent_idx for e in entries if e.kind == "agent"] == [1, 2]


def test_singleton_name_root_still_suppresses_banner_in_three_level_mode() -> None:
    registry = AgentGroupFoldRegistry()
    registry.collapse(("proj", "demo", "solo"))
    entries = build_agent_tree(
        [
            _agent(
                cl_name="demo", project_file="/r/proj/proj.gp", agent_name="solo.claude"
            )
        ],
        fold_registry=registry,
    )
    levels = [e.group.level for e in entries if e.kind == "group"]  # type: ignore[union-attr]
    # L0 + L1, no L2 (singleton).
    assert levels == [0, 1]
    assert any(e.kind == "agent" for e in entries)


def test_default_registry_matches_no_registry() -> None:
    a = _agent(cl_name="demo", agent_name="coder.claude")
    entries_default = build_agent_tree([a])
    entries_empty = build_agent_tree([a], fold_registry=AgentGroupFoldRegistry())
    assert _kinds(entries_default) == _kinds(entries_empty)


# --- enumerate_group_keys ---


def test_enumerate_group_keys_three_level_mode() -> None:
    """Lists every L0/L1/L2 key once; singleton roots are omitted."""
    keys = enumerate_group_keys(
        [
            _agent(cl_name="a", project_file="/r/projA/proj.gp"),
            _agent(
                cl_name="demo",
                project_file="/r/projB/proj.gp",
                agent_name="coder.claude",
            ),
            _agent(
                cl_name="demo",
                project_file="/r/projB/proj.gp",
                agent_name="coder.codex",
            ),
            _agent(
                cl_name="demo",
                project_file="/r/projB/proj.gp",
                agent_name="solo.claude",
            ),
        ]
    )
    assert ("projA",) in keys
    assert ("projA", "a") in keys
    assert ("projB",) in keys
    assert ("projB", "demo") in keys
    assert ("projB", "demo", "coder") in keys
    assert ("projB", "demo", "solo") not in keys


def test_enumerate_group_keys_two_level_mode() -> None:
    """When no agent has a ChangeSpec only L0 + L1 (name-root) keys appear."""
    keys = enumerate_group_keys(
        [
            _agent(
                cl_name="", project_file="/r/proj/proj.gp", agent_name="coder.claude"
            ),
            _agent(
                cl_name="", project_file="/r/proj/proj.gp", agent_name="coder.codex"
            ),
        ]
    )
    assert ("proj",) in keys
    assert ("proj", "coder") in keys
    # No ChangeSpec key since panel is in 2-level mode.
    assert all(len(k) <= 2 for k in keys)


def test_enumerate_group_keys_includes_prefix_subgroups() -> None:
    keys = enumerate_group_keys(
        [
            _agent(cl_name="demo", agent_name="sase-42.2.1", status="DONE"),
            _agent(cl_name="demo", agent_name="sase-42.2.2", status="DONE"),
        ]
    )
    assert ("repo", "demo", "sase-42") in keys
    assert ("repo", "demo", "sase-42", "sase-42.2") in keys


def test_enumerate_group_keys_includes_direct_plus_child_prefix_group() -> None:
    keys = enumerate_group_keys(
        [
            _agent(cl_name="demo", agent_name="foo.bar", status="DONE"),
            _agent(cl_name="demo", agent_name="foo.bar.1", status="DONE"),
        ]
    )
    assert ("repo", "demo", "foo") in keys
    assert ("repo", "demo", "foo", "foo.bar") in keys


def test_enumerate_group_keys_per_panel_mode() -> None:
    """Each panel decides its own mode; keys from both shapes coexist."""
    keys = enumerate_group_keys(
        [
            # Panel A (tag=tag1) has a ChangeSpec → 3-level mode.
            _agent(cl_name="cs", project_file="/r/proj/proj.gp", tag="tag1"),
            # Panel B (tag=tag2) has no ChangeSpec → 2-level mode.
            _agent(cl_name="", project_file="/r/proj/proj.gp", tag="tag2"),
        ]
    )
    # Panel A emits a ChangeSpec key.
    assert ("proj", "cs") in keys
    # Panel B does NOT emit any (project, "") key — its mode is 2-level
    # and there's no name-root group to emit.
    assert ("proj", "") not in keys


# --- Banner summaries ---


def test_compute_banner_summary_counts_running_failed_awaiting() -> None:
    agents = [
        _agent(cl_name="a", status="RUNNING"),
        _agent(cl_name="b", status="FAILED (RETRIED)", retried_as_timestamp="ts-retry"),
        _agent(cl_name="c", status="QUESTION"),
        _agent(cl_name="d", status="DONE"),
    ]
    group = GroupRow(level=0, group_key=("proj",), agent_indices=(0, 1, 2, 3))
    summary = compute_banner_summary(group, agents)
    assert summary.count == 4
    assert summary.running == 1
    assert summary.failed == 1
    assert summary.awaiting == 1


def test_compute_banner_summary_counts_plan_approved_as_running() -> None:
    """PLAN APPROVED is an actively executing state and counts as running."""
    agents = [
        _agent(cl_name="a", status="RUNNING"),
        _agent(cl_name="b", status="PLAN APPROVED"),
    ]
    group = GroupRow(level=0, group_key=("proj",), agent_indices=(0, 1))
    summary = compute_banner_summary(group, agents)
    assert summary.count == 2
    assert summary.running == 2
    assert summary.awaiting == 0


def test_compute_banner_summary_excludes_workflow_children() -> None:
    parent = _agent(cl_name="parent", raw_suffix="ts1", status="RUNNING")
    child = _agent(
        cl_name="step",
        parent_workflow="parent",
        parent_timestamp="ts1",
        status="RUNNING",
    )
    group = GroupRow(level=0, group_key=("proj",), agent_indices=(0, 1))
    summary = compute_banner_summary(group, [parent, child])
    assert summary.count == 1
    assert summary.running == 1


def test_banner_summary_text_renders_chips_separated_by_dots() -> None:
    agents = [
        _agent(cl_name="a", status="RUNNING"),
        _agent(cl_name="b", status="FAILED (RETRIED)", retried_as_timestamp="ts-retry"),
    ]
    group = GroupRow(level=0, group_key=("proj",), agent_indices=(0, 1))
    summary = compute_banner_summary(group, agents)
    text = banner_summary_text(summary)
    assert "2 agents" in text
    assert "1 running" in text
    assert "1 failed" in text


def test_banner_summary_text_handles_failed_statuses() -> None:
    """Every displayed ``FAILED`` status counts toward the failed chip."""
    agents = [
        _agent(cl_name="a", status="FAILED"),
        _agent(cl_name="b", status="FAILED (RETRIED)", retried_as_timestamp="ts-retry"),
    ]
    group = GroupRow(level=0, group_key=("proj",), agent_indices=(0, 1))
    summary = compute_banner_summary(group, agents)
    assert summary.failed == 2
    assert summary.awaiting == 0


def test_banner_summary_text_empty_when_count_is_zero() -> None:
    agents: list[Agent] = []
    group = GroupRow(level=0, group_key=("proj",), agent_indices=())
    summary = compute_banner_summary(group, agents)
    assert banner_summary_text(summary) == ""


# --- Snap-to-ancestor helper ---


def test_find_visible_ancestor_banner_picks_deepest_match() -> None:
    """Snap-to-ancestor focuses the deepest banner containing the agent."""
    a = _agent(cl_name="demo", agent_name="coder.claude")
    b = _agent(cl_name="demo", agent_name="coder.codex")
    registry = AgentGroupFoldRegistry()
    registry.collapse(("proj", "demo", "coder"))
    entries = build_agent_tree([a, b], fold_registry=registry)
    ancestor = find_visible_ancestor_banner(entries, target_agent_idx=0)
    assert ancestor is not None
    assert ancestor.level == 2  # name-root banner is the deepest match


def test_find_visible_ancestor_banner_falls_back_to_higher_level() -> None:
    """When the deepest banner is suppressed, fall back to the higher one."""
    a = _agent(cl_name="demo", agent_name="coder.claude")
    registry = AgentGroupFoldRegistry()
    registry.collapse(("repo",))
    entries = build_agent_tree([a], fold_registry=registry)
    ancestor = find_visible_ancestor_banner(entries, target_agent_idx=0)
    assert ancestor is not None
    assert ancestor.level == 0


def test_find_visible_ancestor_banner_falls_back_when_root_singleton() -> None:
    """A singleton-root agent has no name-root banner."""
    a = _agent(cl_name="demo", agent_name="solo.claude")
    registry = AgentGroupFoldRegistry()
    registry.collapse(("repo",))
    entries = build_agent_tree([a], fold_registry=registry)
    ancestor = find_visible_ancestor_banner(entries, target_agent_idx=0)
    assert ancestor is not None
    # Project banner is the deepest match (collapsed L0 wins).
    assert ancestor.level == 0


def test_find_visible_ancestor_banner_returns_none_when_idx_unknown() -> None:
    a = _agent()
    registry = AgentGroupFoldRegistry()
    registry.collapse(("repo",))
    entries = build_agent_tree([a], fold_registry=registry)
    assert find_visible_ancestor_banner(entries, target_agent_idx=42) is None

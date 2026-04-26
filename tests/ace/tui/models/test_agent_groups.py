"""Tests for the two-level agent grouping tree (project → name-root)."""

from __future__ import annotations

from datetime import datetime

from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_group_fold import AgentGroupFoldRegistry
from sase.ace.tui.models.agent_groups import (
    GroupRow,
    TreeEntry,
    banner_label,
    banner_summary_text,
    build_agent_tree,
    compute_banner_summary,
    enumerate_group_keys,
    find_visible_ancestor_banner,
)


def _agent(
    *,
    cl_name: str = "demo",
    project_file: str = "/repo/proj.gp",
    tag: str | None = None,
    agent_name: str | None = None,
    raw_suffix: str | None = None,
    parent_workflow: str | None = None,
    parent_timestamp: str | None = None,
    status: str = "RUNNING",
) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name=cl_name,
        project_file=project_file,
        status=status,
        start_time=datetime(2026, 4, 25, 12, 0, 0),
        raw_suffix=raw_suffix,
        agent_name=agent_name,
        tag=tag,
        parent_workflow=parent_workflow,
        parent_timestamp=parent_timestamp,
    )


def _kinds(entries: list[TreeEntry]) -> list[tuple[str, int | None]]:
    """Reduce entries to (kind, level/agent_idx) pairs for readable assertions."""
    out: list[tuple[str, int | None]] = []
    for e in entries:
        if e.kind == "group":
            assert e.group is not None
            out.append(("group", e.group.level))
        else:
            out.append(("agent", e.agent_idx))
    return out


def test_single_agent_emits_project_banner_only() -> None:
    a = _agent(cl_name="demo", project_file="/repo/proj.gp")
    entries = build_agent_tree([a])
    assert _kinds(entries) == [("group", 0), ("agent", 0)]


def test_no_name_root_banner_for_single_dotted_agent() -> None:
    """A lone dotted-name agent skips the level-1 banner — it would be pure chrome."""
    a = _agent(cl_name="demo", agent_name="coder.claude")
    entries = build_agent_tree([a])
    assert _kinds(entries) == [
        ("group", 0),
        ("agent", 0),
    ]


def test_no_name_root_banner_when_name_has_no_dot() -> None:
    a = _agent(cl_name="demo", agent_name="solo")
    entries = build_agent_tree([a])
    assert _kinds(entries) == [("group", 0), ("agent", 0)]


def test_two_agents_sharing_name_root_share_one_name_root_banner() -> None:
    a = _agent(cl_name="demo", agent_name="coder.claude")
    b = _agent(cl_name="demo", agent_name="coder.codex")
    entries = build_agent_tree([a, b])
    # One project + one name-root banner, then both agents.
    assert _kinds(entries) == [
        ("group", 0),
        ("group", 1),
        ("agent", 0),
        ("agent", 1),
    ]


def test_distinct_projects_emit_separate_project_banners() -> None:
    a = _agent(cl_name="demo-a", project_file="/repo/proja/proj.gp")
    b = _agent(cl_name="demo-b", project_file="/repo/projb/proj.gp")
    entries = build_agent_tree([a, b])
    levels = [e.group.level for e in entries if e.kind == "group"]  # type: ignore[union-attr]
    assert levels == [0, 0]


def test_workflow_child_inherits_parent_grouping() -> None:
    parent = _agent(cl_name="demo", agent_name="coder.claude", raw_suffix="ts1")
    child = _agent(
        cl_name="step",
        agent_name="step.bash",
        parent_workflow="coder",
        parent_timestamp="ts1",
    )
    entries = build_agent_tree([parent, child])
    # Parent emits project + name-root banners; child reuses parent's keys
    # so no extra banners between them.
    assert _kinds(entries) == [
        ("group", 0),
        ("group", 1),
        ("agent", 0),
        ("agent", 1),
    ]


def test_group_row_carries_full_agent_indices() -> None:
    a = _agent(cl_name="demo")
    b = _agent(cl_name="demo")
    entries = build_agent_tree([a, b])
    project_banners = [
        e
        for e in entries
        if e.kind == "group" and e.group.level == 0  # type: ignore[union-attr]
    ]
    assert len(project_banners) == 1
    assert project_banners[0].group.agent_indices == (0, 1)  # type: ignore[union-attr]


def test_no_project_label_when_project_file_missing() -> None:
    a = _agent(cl_name="demo", project_file="")
    entries = build_agent_tree([a])
    project_banner = [e for e in entries if e.kind == "group" and e.group.level == 0][0]  # type: ignore[union-attr]
    assert banner_label(project_banner.group) == "(no project) / demo"  # type: ignore[arg-type]


def test_project_label_renders_project_and_changespec() -> None:
    g = GroupRow(
        level=0,
        group_key=("sase_100", "fix-bug-id"),
        agent_indices=(0,),
    )
    assert banner_label(g) == "sase_100 / fix-bug-id"


# --- Per-group fold builds ---


def test_collapsed_l0_hides_descendants_but_emits_banner() -> None:
    """A collapsed L0 banner appears with `is_collapsed=True` and no children."""
    registry = AgentGroupFoldRegistry()
    registry.collapse(("projA", "a"))
    entries = build_agent_tree(
        [
            _agent(cl_name="a", project_file="/r/projA/proj.gp"),
            _agent(cl_name="b", project_file="/r/projB/proj.gp"),
        ],
        fold_registry=registry,
    )
    # projA banner (collapsed, no children), then projB banner + agent.
    assert _kinds(entries) == [("group", 0), ("group", 0), ("agent", 1)]
    proj_a = entries[0]
    assert proj_a.group is not None and proj_a.group.is_collapsed is True
    proj_b = entries[1]
    assert proj_b.group is not None and proj_b.group.is_collapsed is False


def test_collapsing_one_l0_does_not_affect_sibling() -> None:
    """Collapsing one project leaves the other fully expanded."""
    registry = AgentGroupFoldRegistry()
    registry.collapse(("projA", "a"))
    entries = build_agent_tree(
        [
            _agent(cl_name="a", project_file="/r/projA/proj.gp", agent_name="x"),
            _agent(cl_name="a", project_file="/r/projA/proj.gp", agent_name="y"),
            _agent(cl_name="b", project_file="/r/projB/proj.gp", agent_name="z"),
        ],
        fold_registry=registry,
    )
    # projA: banner only.  projB: banner + its agent.
    kinds = _kinds(entries)
    assert kinds.count(("agent", 2)) == 1  # projB agent kept
    assert ("agent", 0) not in kinds and ("agent", 1) not in kinds


def test_collapsed_l1_hides_only_its_agents() -> None:
    """A collapsed L1 banner suppresses its own agents only."""
    registry = AgentGroupFoldRegistry()
    registry.collapse(("", "demo", "coder"))
    entries = build_agent_tree(
        [
            _agent(cl_name="demo", project_file="", agent_name="coder.claude"),
            _agent(cl_name="demo", project_file="", agent_name="coder.codex"),
            _agent(cl_name="demo", project_file="", agent_name="planner.claude"),
            _agent(cl_name="demo", project_file="", agent_name="planner.codex"),
        ],
        fold_registry=registry,
    )
    # L0 + collapsed coder L1 (no children) + planner L1 + 2 planner agents.
    levels = [e.group.level for e in entries if e.kind == "group"]  # type: ignore[union-attr]
    assert levels == [0, 1, 1]
    coder = next(
        e
        for e in entries
        if e.kind == "group" and e.group and e.group.group_key[-1] == "coder"  # type: ignore[union-attr]
    )
    planner = next(
        e
        for e in entries
        if e.kind == "group" and e.group and e.group.group_key[-1] == "planner"  # type: ignore[union-attr]
    )
    assert coder.group is not None and coder.group.is_collapsed is True
    assert planner.group is not None and planner.group.is_collapsed is False
    # Only planner's agents appear.
    agent_indices = [e.agent_idx for e in entries if e.kind == "agent"]
    assert agent_indices == [2, 3]


def test_singleton_name_root_still_suppresses_l1_banner_when_collapsed() -> None:
    """Singleton name-root produces no banner regardless of registry state."""
    registry = AgentGroupFoldRegistry()
    registry.collapse(("", "demo", "solo"))  # would-be L1 key
    entries = build_agent_tree(
        [_agent(cl_name="demo", project_file="", agent_name="solo.claude")],
        fold_registry=registry,
    )
    # No L1 banner — singleton suppression wins.
    levels = [e.group.level for e in entries if e.kind == "group"]  # type: ignore[union-attr]
    assert levels == [0]
    # Agent still emitted because the L0 is expanded.
    assert any(e.kind == "agent" for e in entries)


def test_default_registry_matches_no_registry() -> None:
    a = _agent(cl_name="demo", agent_name="coder.claude")
    entries_default = build_agent_tree([a])
    entries_empty = build_agent_tree([a], fold_registry=AgentGroupFoldRegistry())
    assert _kinds(entries_default) == _kinds(entries_empty)


def test_enumerate_group_keys_returns_l0_and_multi_l1() -> None:
    """``enumerate_group_keys`` lists every L0 + multi-entry L1 once."""
    keys = enumerate_group_keys(
        [
            _agent(cl_name="a", project_file="/r/projA/proj.gp"),
            _agent(cl_name="demo", project_file="", agent_name="coder.claude"),
            _agent(cl_name="demo", project_file="", agent_name="coder.codex"),
            _agent(cl_name="demo", project_file="", agent_name="solo.claude"),
        ]
    )
    # Two L0s + one L1 ("coder").  "solo" is a singleton root → no L1 key.
    assert ("projA", "a") in keys
    assert ("", "demo") in keys
    assert ("", "demo", "coder") in keys
    assert ("", "demo", "solo") not in keys


# --- Banner summaries ---


def test_compute_banner_summary_counts_running_failed_awaiting() -> None:
    agents = [
        _agent(cl_name="a", status="RUNNING"),
        _agent(cl_name="b", status="FAILED"),
        _agent(cl_name="c", status="QUESTION"),
        _agent(cl_name="d", status="DONE"),
    ]
    group = GroupRow(level=0, group_key=("proj", ""), agent_indices=(0, 1, 2, 3))
    summary = compute_banner_summary(group, agents)
    assert summary.count == 4
    assert summary.running == 1
    assert summary.failed == 1
    assert summary.awaiting == 1


def test_compute_banner_summary_excludes_workflow_children() -> None:
    parent = _agent(cl_name="parent", raw_suffix="ts1", status="RUNNING")
    child = _agent(
        cl_name="step",
        parent_workflow="parent",
        parent_timestamp="ts1",
        status="RUNNING",
    )
    group = GroupRow(level=0, group_key=("proj", ""), agent_indices=(0, 1))
    summary = compute_banner_summary(group, [parent, child])
    # Only the parent counts.
    assert summary.count == 1
    assert summary.running == 1


def test_banner_summary_text_renders_chips_separated_by_dots() -> None:
    agents = [
        _agent(cl_name="a", status="RUNNING"),
        _agent(cl_name="b", status="FAILED"),
    ]
    group = GroupRow(level=0, group_key=("proj", ""), agent_indices=(0, 1))
    summary = compute_banner_summary(group, agents)
    text = banner_summary_text(summary)
    assert "2 agents" in text
    assert "1 running" in text
    assert "1 failed" in text


def test_banner_summary_text_handles_failed_retried_status() -> None:
    """Both ``FAILED`` and ``FAILED (RETRIED)`` count toward the failed chip."""
    agents = [
        _agent(cl_name="a", status="FAILED"),
        _agent(cl_name="b", status="FAILED (RETRIED)"),
    ]
    group = GroupRow(level=0, group_key=("proj", ""), agent_indices=(0, 1))
    summary = compute_banner_summary(group, agents)
    assert summary.failed == 2


def test_banner_summary_text_empty_when_count_is_zero() -> None:
    agents: list[Agent] = []
    group = GroupRow(level=0, group_key=("proj", ""), agent_indices=())
    summary = compute_banner_summary(group, agents)
    assert banner_summary_text(summary) == ""


# --- Snap-to-ancestor helper ---


def test_find_visible_ancestor_banner_picks_deepest_match() -> None:
    """Snap-to-ancestor focuses the deepest banner containing the agent."""
    a = _agent(cl_name="demo", agent_name="coder.claude")
    b = _agent(cl_name="demo", agent_name="coder.codex")
    registry = AgentGroupFoldRegistry()
    registry.collapse(("", "demo", "coder"))
    entries = build_agent_tree([a, b], fold_registry=registry)
    ancestor = find_visible_ancestor_banner(entries, target_agent_idx=0)
    assert ancestor is not None
    assert ancestor.level == 1  # name-root banner is the deepest match


def test_find_visible_ancestor_banner_falls_back_to_higher_level() -> None:
    """When the deepest banner is suppressed, fall back to the higher one."""
    a = _agent(cl_name="demo", agent_name="coder.claude")
    registry = AgentGroupFoldRegistry()
    registry.collapse(("", "demo"))
    entries = build_agent_tree([a], fold_registry=registry)
    ancestor = find_visible_ancestor_banner(entries, target_agent_idx=0)
    assert ancestor is not None
    assert ancestor.level == 0


def test_find_visible_ancestor_banner_falls_back_when_root_singleton() -> None:
    """A singleton-root agent has no level-1 banner; falls back to project."""
    a = _agent(cl_name="demo", agent_name="solo.claude")
    registry = AgentGroupFoldRegistry()
    registry.collapse(("", "demo"))
    entries = build_agent_tree([a], fold_registry=registry)
    ancestor = find_visible_ancestor_banner(entries, target_agent_idx=0)
    assert ancestor is not None
    # No level-1 banner exists for this singleton root, so the project
    # banner is the deepest match.
    assert ancestor.level == 0


def test_find_visible_ancestor_banner_returns_none_when_idx_unknown() -> None:
    a = _agent()
    registry = AgentGroupFoldRegistry()
    registry.collapse(("", "demo"))
    entries = build_agent_tree([a], fold_registry=registry)
    assert find_visible_ancestor_banner(entries, target_agent_idx=42) is None


# --- Dedupe + deterministic group ordering ---


def _group_keys(entries: list[TreeEntry], level: int) -> list[tuple[str, ...]]:
    return [
        e.group.group_key  # type: ignore[union-attr]
        for e in entries
        if e.kind == "group" and e.group is not None and e.group.level == level
    ]


def test_full_tree_does_not_split_same_project_group() -> None:
    """Members of the same project interleaved with another project render once each."""
    a = _agent(cl_name="cl-a", project_file="/r/projA/proj.gp")
    b = _agent(cl_name="cl-b", project_file="/r/projB/proj.gp")
    c = _agent(cl_name="cl-a", project_file="/r/projA/proj.gp")
    entries = build_agent_tree([a, b, c])
    proj_keys = _group_keys(entries, level=0)
    # Two unique projects, each rendered once.
    assert len(proj_keys) == 2


def test_full_tree_sort_is_deterministic() -> None:
    """Same agents in different orders produce identical tree shapes."""
    a = _agent(cl_name="a", project_file="/r/projA/proj.gp")
    b = _agent(cl_name="b", project_file="/r/projB/proj.gp")
    c = _agent(cl_name="c", project_file="")

    order1 = build_agent_tree([a, b, c])
    order2 = build_agent_tree([c, b, a])
    order3 = build_agent_tree([b, c, a])

    def reduce_keys(entries: list[TreeEntry]) -> list[tuple[str, ...] | None]:
        out: list[tuple[str, ...] | None] = []
        for e in entries:
            if e.kind == "group":
                assert e.group is not None
                out.append(e.group.group_key)
            else:
                out.append(None)
        return out

    assert reduce_keys(order1) == reduce_keys(order2) == reduce_keys(order3)


def test_full_tree_named_projects_sort_before_unprojected() -> None:
    """Named projects sort lex; ``(no project)`` always sorts last."""
    entries = build_agent_tree(
        [
            _agent(cl_name="a", project_file="/r/beta/proj.gp"),
            _agent(cl_name="b", project_file=""),
            _agent(cl_name="c", project_file="/r/alpha/proj.gp"),
        ]
    )
    proj_keys = _group_keys(entries, level=0)
    assert [k[0] for k in proj_keys] == ["alpha", "beta", ""]


def test_full_tree_workflow_children_stay_with_parent_after_sort() -> None:
    """Workflow children keep parent-adjacent ordering even with an interloper."""
    parent = _agent(cl_name="demo", agent_name="solo", raw_suffix="ts1")
    child1 = _agent(
        cl_name="step1",
        agent_name="step1",
        parent_workflow="solo",
        parent_timestamp="ts1",
    )
    other = _agent(cl_name="other", agent_name="other")
    child2 = _agent(
        cl_name="step2",
        agent_name="step2",
        parent_workflow="solo",
        parent_timestamp="ts1",
    )
    # Input order interleaves the workflow steps with the other agent.
    entries = build_agent_tree([parent, child1, other, child2])

    agent_order = [e.agent_idx for e in entries if e.kind == "agent"]
    # demo (cl_name=demo) sorts before "other" within the same project.
    assert agent_order == [0, 1, 3, 2]


def test_full_tree_singleton_name_root_still_suppressed_after_sort() -> None:
    """Sort-driven walk doesn't regress the singleton name-root suppression."""
    entries = build_agent_tree(
        [
            _agent(cl_name="demo", agent_name="solo.gemini"),
            _agent(cl_name="demo", agent_name="coder.claude"),
            _agent(cl_name="demo", agent_name="coder.codex"),
        ]
    )
    name_root_banners = [
        e
        for e in entries
        if e.kind == "group" and e.group is not None and e.group.level == 1
    ]
    # Only the multi-entry "coder" root has a banner — solo.gemini stays bare.
    assert len(name_root_banners) == 1
    assert name_root_banners[0].group.group_key[-1] == "coder"  # type: ignore[union-attr]
    # And the bare singleton sorts above the level-2 group members.
    agent_order = [e.agent_idx for e in entries if e.kind == "agent"]
    assert agent_order == [0, 1, 2]


def test_singleton_dotted_agent_sorts_above_level_2_group() -> None:
    """A singleton dotted agent renders above the level-2 group banner."""
    entries = build_agent_tree(
        [
            _agent(cl_name="demo", agent_name="solo.gemini"),
            _agent(cl_name="demo", agent_name="coder.claude"),
            _agent(cl_name="demo", agent_name="coder.codex"),
        ]
    )
    # Tree-walk order: project banner, singleton agent, coder banner, coder members.
    assert _kinds(entries) == [
        ("group", 0),
        ("agent", 0),
        ("group", 1),
        ("agent", 1),
        ("agent", 2),
    ]


def test_dotless_and_singleton_agents_both_precede_level_2_group() -> None:
    """Dotless and singleton dotted agents both fall in the ungrouped bucket."""
    entries = build_agent_tree(
        [
            _agent(cl_name="demo", agent_name="bare"),
            _agent(cl_name="demo", agent_name="lone.x"),
            _agent(cl_name="demo", agent_name="grp.a"),
            _agent(cl_name="demo", agent_name="grp.b"),
        ]
    )
    # Project banner, then the two ungrouped agents (stable input order),
    # then the grp banner with its members.
    assert _kinds(entries) == [
        ("group", 0),
        ("agent", 0),
        ("agent", 1),
        ("group", 1),
        ("agent", 2),
        ("agent", 3),
    ]


def test_ungrouped_bucket_preserves_input_order() -> None:
    """Stable sort preserves input order within the ungrouped bucket."""
    perm_a = build_agent_tree(
        [
            _agent(cl_name="demo", agent_name="bare"),
            _agent(cl_name="demo", agent_name="lone.x"),
            _agent(cl_name="demo", agent_name="grp.a"),
            _agent(cl_name="demo", agent_name="grp.b"),
        ]
    )
    perm_b = build_agent_tree(
        [
            _agent(cl_name="demo", agent_name="lone.x"),
            _agent(cl_name="demo", agent_name="bare"),
            _agent(cl_name="demo", agent_name="grp.a"),
            _agent(cl_name="demo", agent_name="grp.b"),
        ]
    )
    order_a = [e.agent_idx for e in perm_a if e.kind == "agent"]
    order_b = [e.agent_idx for e in perm_b if e.kind == "agent"]
    # In each permutation the ungrouped pair (idx 0 then 1) precedes the
    # grouped pair, in their original input order.
    assert order_a == [0, 1, 2, 3]
    assert order_b == [0, 1, 2, 3]


def test_collapsed_tree_order_is_deterministic() -> None:
    """Banner emission order is stable when groups are collapsed."""
    a = _agent(cl_name="a", project_file="/r/projA/proj.gp")
    b = _agent(cl_name="b", project_file="/r/projB/proj.gp")
    c = _agent(cl_name="c", project_file="")
    registry = AgentGroupFoldRegistry()
    registry.collapse_keys([("projA", "a"), ("projB", "b"), ("", "c")])

    order1 = build_agent_tree([a, b, c], fold_registry=registry)
    order2 = build_agent_tree([c, a, b], fold_registry=registry)
    order3 = build_agent_tree([b, c, a], fold_registry=registry)

    def banner_keys(entries: list[TreeEntry]) -> list[tuple[int, tuple[str, ...]]]:
        return [
            (e.group.level, e.group.group_key)  # type: ignore[union-attr]
            for e in entries
            if e.kind == "group" and e.group is not None
        ]

    assert banner_keys(order1) == banner_keys(order2) == banner_keys(order3)

"""Tests for the project / ChangeSpec / name-root agent grouping tree."""

from __future__ import annotations

from datetime import datetime

from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_group_fold import AgentGroupFoldRegistry
from sase.ace.tui.models.agent_groups import (
    NO_CHANGESPEC_LABEL,
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


# --- Three-level layout (panel has at least one ChangeSpec) ---


def test_single_agent_emits_project_and_changespec_banner() -> None:
    a = _agent(cl_name="demo", project_file="/repo/proj.gp")
    entries = build_agent_tree([a])
    assert _kinds(entries) == [("group", 0), ("group", 1), ("agent", 0)]


def test_no_name_root_banner_for_single_dotted_agent() -> None:
    """A lone dotted-name agent skips the deepest banner — it would be pure chrome."""
    a = _agent(cl_name="demo", agent_name="coder.claude")
    entries = build_agent_tree([a])
    assert _kinds(entries) == [
        ("group", 0),
        ("group", 1),
        ("agent", 0),
    ]


def test_no_name_root_banner_when_name_has_no_dot() -> None:
    a = _agent(cl_name="demo", agent_name="solo")
    entries = build_agent_tree([a])
    assert _kinds(entries) == [("group", 0), ("group", 1), ("agent", 0)]


def test_two_agents_sharing_name_root_emit_three_banners() -> None:
    a = _agent(cl_name="demo", agent_name="coder.claude")
    b = _agent(cl_name="demo", agent_name="coder.codex")
    entries = build_agent_tree([a, b])
    # Project + ChangeSpec + name-root banners, then both agents.
    assert _kinds(entries) == [
        ("group", 0),
        ("group", 1),
        ("group", 2),
        ("agent", 0),
        ("agent", 1),
    ]


def test_distinct_projects_emit_separate_project_banners() -> None:
    a = _agent(cl_name="demo-a", project_file="/repo/proja/proj.gp")
    b = _agent(cl_name="demo-b", project_file="/repo/projb/proj.gp")
    entries = build_agent_tree([a, b])
    levels = [e.group.level for e in entries if e.kind == "group"]  # type: ignore[union-attr]
    assert levels == [0, 1, 0, 1]


def test_workflow_child_inherits_parent_grouping() -> None:
    parent = _agent(cl_name="demo", agent_name="coder.claude", raw_suffix="ts1")
    child = _agent(
        cl_name="step",
        agent_name="step.bash",
        parent_workflow="coder",
        parent_timestamp="ts1",
    )
    entries = build_agent_tree([parent, child])
    # Parent emits all banners; child reuses parent's keys with no extras.
    assert _kinds(entries) == [
        ("group", 0),
        ("group", 1),
        ("group", 2),
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


def test_no_project_label() -> None:
    a = _agent(cl_name="demo", project_file="")
    entries = build_agent_tree([a])
    project_banner = next(
        e
        for e in entries
        if e.kind == "group" and e.group.level == 0  # type: ignore[union-attr]
    )
    assert banner_label(project_banner.group) == "(no project)"  # type: ignore[arg-type]


def test_project_label_renders_just_project_name() -> None:
    g = GroupRow(level=0, group_key=("sase_100",), agent_indices=(0,))
    assert banner_label(g) == "sase_100"


def test_changespec_label_renders_changespec_name() -> None:
    g = GroupRow(level=1, group_key=("sase_100", "fix-bug-id"), agent_indices=(0,))
    assert banner_label(g) == "fix-bug-id"


def test_changespec_label_uses_synthetic_label_for_empty_bucket() -> None:
    g = GroupRow(level=1, group_key=("sase_100", ""), agent_indices=(0,))
    assert banner_label(g) == NO_CHANGESPEC_LABEL


def test_name_root_label_at_level_two() -> None:
    g = GroupRow(
        level=2, group_key=("sase_100", "fix-bug-id", "coder"), agent_indices=(0,)
    )
    assert banner_label(g) == "coder"


# --- Two-level fallback (no agent in the panel has a ChangeSpec) ---


def test_no_changespec_panel_drops_to_two_level_layout() -> None:
    """When no agent has a ChangeSpec the renderer matches the pre-split shape."""
    a = _agent(cl_name="", project_file="/r/projA/proj.gp")
    entries = build_agent_tree([a])
    # Just project banner + agent — no ChangeSpec banner inserted.
    assert _kinds(entries) == [("group", 0), ("agent", 0)]


def test_two_level_panel_keeps_name_root_at_level_one() -> None:
    a = _agent(cl_name="", project_file="/r/proj/proj.gp", agent_name="coder.claude")
    b = _agent(cl_name="", project_file="/r/proj/proj.gp", agent_name="coder.codex")
    entries = build_agent_tree([a, b])
    # project banner + name-root banner + agents — same shape as today.
    assert _kinds(entries) == [
        ("group", 0),
        ("group", 1),
        ("agent", 0),
        ("agent", 1),
    ]


def test_two_level_project_label_renders_just_project_name() -> None:
    a = _agent(cl_name="", project_file="/r/sase_100/proj.gp")
    entries = build_agent_tree([a])
    project_banner = next(
        e
        for e in entries
        if e.kind == "group" and e.group.level == 0  # type: ignore[union-attr]
    )
    assert banner_label(project_banner.group) == "sase_100"  # type: ignore[arg-type]


# --- Mixed-case bucket (some agents have ChangeSpec, some don't) ---


def test_mixed_panel_synthesizes_no_changespec_bucket() -> None:
    """Agents without a ChangeSpec collect under a synthetic bucket."""
    a = _agent(cl_name="fix-a", project_file="/r/proj/proj.gp")
    b = _agent(cl_name="", project_file="/r/proj/proj.gp")
    entries = build_agent_tree([a, b])
    # Two ChangeSpec banners under the same project.
    cs_banners = [
        e
        for e in entries
        if e.kind == "group" and e.group is not None and e.group.level == 1
    ]
    assert len(cs_banners) == 2
    suffixes = [b.group.group_key[-1] for b in cs_banners]  # type: ignore[union-attr]
    # Named ChangeSpec sorts before the synthetic bucket.
    assert suffixes == ["fix-a", ""]
    # And the synthetic bucket renders with the placeholder label.
    assert banner_label(cs_banners[1].group) == NO_CHANGESPEC_LABEL  # type: ignore[arg-type]


def test_mixed_panel_synthetic_bucket_is_independently_collapsible() -> None:
    """The synthetic bucket is keyed by ``(project, "")`` and folds normally."""
    registry = AgentGroupFoldRegistry()
    registry.collapse(("proj", ""))
    a = _agent(cl_name="fix-a", project_file="/r/proj/proj.gp")
    b = _agent(cl_name="", project_file="/r/proj/proj.gp")
    entries = build_agent_tree([a, b], fold_registry=registry)
    # The synthetic banner is collapsed (no agent under it); the named
    # ChangeSpec banner is still expanded.
    cs_banners = [
        e
        for e in entries
        if e.kind == "group" and e.group is not None and e.group.level == 1
    ]
    assert {(b.group.group_key, b.group.is_collapsed) for b in cs_banners} == {  # type: ignore[union-attr]
        (("proj", "fix-a"), False),
        (("proj", ""), True),
    }


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
        _agent(cl_name="b", status="FAILED"),
        _agent(cl_name="c", status="QUESTION"),
        _agent(cl_name="d", status="DONE"),
    ]
    group = GroupRow(level=0, group_key=("proj",), agent_indices=(0, 1, 2, 3))
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
    group = GroupRow(level=0, group_key=("proj",), agent_indices=(0, 1))
    summary = compute_banner_summary(group, [parent, child])
    assert summary.count == 1
    assert summary.running == 1


def test_banner_summary_text_renders_chips_separated_by_dots() -> None:
    agents = [
        _agent(cl_name="a", status="RUNNING"),
        _agent(cl_name="b", status="FAILED"),
    ]
    group = GroupRow(level=0, group_key=("proj",), agent_indices=(0, 1))
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
    group = GroupRow(level=0, group_key=("proj",), agent_indices=(0, 1))
    summary = compute_banner_summary(group, agents)
    assert summary.failed == 2


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
    deep_banners = [
        e
        for e in entries
        if e.kind == "group" and e.group is not None and e.group.level == 2
    ]
    assert len(deep_banners) == 1
    assert deep_banners[0].group.group_key[-1] == "coder"  # type: ignore[union-attr]
    agent_order = [e.agent_idx for e in entries if e.kind == "agent"]
    assert agent_order == [0, 1, 2]


def test_singleton_dotted_agent_sorts_above_grouped_name_root() -> None:
    """A singleton dotted agent renders above the deeper group banner."""
    entries = build_agent_tree(
        [
            _agent(cl_name="demo", agent_name="solo.gemini"),
            _agent(cl_name="demo", agent_name="coder.claude"),
            _agent(cl_name="demo", agent_name="coder.codex"),
        ]
    )
    # Project + ChangeSpec banners, the singleton, then the coder group.
    assert _kinds(entries) == [
        ("group", 0),
        ("group", 1),
        ("agent", 0),
        ("group", 2),
        ("agent", 1),
        ("agent", 2),
    ]


def test_dotless_and_singleton_agents_both_precede_grouped_name_root() -> None:
    entries = build_agent_tree(
        [
            _agent(cl_name="demo", agent_name="bare"),
            _agent(cl_name="demo", agent_name="lone.x"),
            _agent(cl_name="demo", agent_name="grp.a"),
            _agent(cl_name="demo", agent_name="grp.b"),
        ]
    )
    assert _kinds(entries) == [
        ("group", 0),
        ("group", 1),
        ("agent", 0),
        ("agent", 1),
        ("group", 2),
        ("agent", 2),
        ("agent", 3),
    ]


def test_ungrouped_bucket_preserves_input_order() -> None:
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
    assert order_a == [0, 1, 2, 3]
    assert order_b == [0, 1, 2, 3]


def test_collapsed_tree_order_is_deterministic() -> None:
    a = _agent(cl_name="a", project_file="/r/projA/proj.gp")
    b = _agent(cl_name="b", project_file="/r/projB/proj.gp")
    c = _agent(cl_name="c", project_file="")
    registry = AgentGroupFoldRegistry()
    registry.collapse_keys([("projA",), ("projB",), ("",)])

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

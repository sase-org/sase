"""Tests for the three-level agent grouping tree."""

from __future__ import annotations

from datetime import datetime

from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_groups import (
    GroupRow,
    TreeEntry,
    banner_label,
    banner_summary_text,
    build_agent_tree,
    compute_banner_summary,
    find_visible_ancestor_banner,
)


def _agent(
    *,
    cl_name: str = "demo",
    project_file: str = "/repo/proj.gp",
    tags: tuple[str, ...] = (),
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
        tags=tags,
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


def test_single_untagged_agent_emits_tag_and_project_banners() -> None:
    a = _agent(cl_name="demo", project_file="/repo/proj.gp")
    entries = build_agent_tree([a])
    assert _kinds(entries) == [("group", 0), ("group", 1), ("agent", 0)]


def test_no_name_root_banner_for_single_dotted_agent() -> None:
    """A lone dotted-name agent skips the level-2 banner — it would be pure chrome."""
    a = _agent(cl_name="demo", agent_name="coder.claude")
    entries = build_agent_tree([a])
    # Tag, project, agent — no level-2 banner for a singleton root.
    assert _kinds(entries) == [
        ("group", 0),
        ("group", 1),
        ("agent", 0),
    ]


def test_no_name_root_banner_when_name_has_no_dot() -> None:
    a = _agent(cl_name="demo", agent_name="solo")
    entries = build_agent_tree([a])
    assert _kinds(entries) == [("group", 0), ("group", 1), ("agent", 0)]


def test_two_agents_sharing_name_root_share_one_name_root_banner() -> None:
    a = _agent(cl_name="demo", agent_name="coder.claude")
    b = _agent(cl_name="demo", agent_name="coder.codex")
    entries = build_agent_tree([a, b])
    # One tag/project/root banner triple, then both agents.
    assert _kinds(entries) == [
        ("group", 0),
        ("group", 1),
        ("group", 2),
        ("agent", 0),
        ("agent", 1),
    ]


def test_tag_change_emits_new_tag_banner() -> None:
    a = _agent(cl_name="demo", tags=("alpha",))
    b = _agent(cl_name="demo", tags=("beta",))
    entries = build_agent_tree([a, b])
    levels = [e.group.level for e in entries if e.kind == "group"]  # type: ignore[union-attr]
    # Two tag banners (one per tag), each with its own project banner.
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
    # Parent emits tag+project+name-root banners; child reuses parent's keys
    # so no extra banners between them.
    assert _kinds(entries) == [
        ("group", 0),
        ("group", 1),
        ("group", 2),
        ("agent", 0),
        ("agent", 1),
    ]


def test_group_row_carries_full_agent_indices() -> None:
    a = _agent(tags=("alpha",))
    b = _agent(tags=("alpha",))
    entries = build_agent_tree([a, b])
    tag_banners = [e for e in entries if e.kind == "group" and e.group.level == 0]  # type: ignore[union-attr]
    assert len(tag_banners) == 1
    assert tag_banners[0].group.agent_indices == (0, 1)  # type: ignore[union-attr]


def test_no_project_label_when_project_file_missing() -> None:
    a = _agent(cl_name="demo", project_file="")
    entries = build_agent_tree([a])
    project_banner = [e for e in entries if e.kind == "group" and e.group.level == 1][0]  # type: ignore[union-attr]
    assert banner_label(project_banner.group) == "(no project) / demo"  # type: ignore[arg-type]


def test_untagged_label_when_no_tags() -> None:
    a = _agent(tags=())
    entries = build_agent_tree([a])
    tag_banner = [e for e in entries if e.kind == "group" and e.group.level == 0][0]  # type: ignore[union-attr]
    assert banner_label(tag_banner.group) == "(untagged)"  # type: ignore[arg-type]


def test_primary_tag_label_renders_with_at_prefix() -> None:
    g = GroupRow(level=0, group_key=("release-blockers",), agent_indices=(0,))
    assert banner_label(g) == "@release-blockers"


def test_project_label_renders_project_and_changespec() -> None:
    g = GroupRow(
        level=1,
        group_key=("alpha", "sase_100", "fix-bug-id"),
        agent_indices=(0,),
    )
    assert banner_label(g) == "sase_100 / fix-bug-id"


def test_non_contiguous_same_tag_emits_single_banner() -> None:
    """Interleaved members of the same tag collapse to one banner via sort.

    The walk is reordered by grouping key before emission, so every group
    key renders exactly once with all its members contiguous beneath it.
    """
    a = _agent(tags=("alpha",))
    b = _agent(tags=("beta",))
    c = _agent(tags=("alpha",))
    entries = build_agent_tree([a, b, c])
    alpha_banners = [
        e
        for e in entries
        if e.kind == "group"
        and e.group is not None
        and e.group.level == 0
        and e.group.group_key == ("alpha",)
    ]
    assert len(alpha_banners) == 1
    assert alpha_banners[0].group.agent_indices == (0, 2)  # type: ignore[union-attr]
    # The two alpha agents render contiguously, before the beta agent.
    agent_order = [e.agent_idx for e in entries if e.kind == "agent"]
    assert agent_order == [0, 2, 1]


# --- Phase 4: fold-level builds ---


def test_fold_level_0_emits_one_banner_per_unique_tag() -> None:
    """At L0 only L0 banners appear, one per unique tag, no agents."""
    entries = build_agent_tree(
        [
            _agent(tags=("alpha",)),
            _agent(tags=("beta",)),
            _agent(tags=("alpha",)),
            _agent(tags=()),
        ],
        group_fold_level=0,
    )
    assert _kinds(entries) == [("group", 0), ("group", 0), ("group", 0)]
    tags = [e.group.group_key for e in entries]  # type: ignore[union-attr]
    assert tags == [("alpha",), ("beta",), ("",)]


def test_fold_level_0_banner_carries_full_index_set_across_clusters() -> None:
    """Even at L0, banner indices reference every agent in the group."""
    entries = build_agent_tree(
        [
            _agent(tags=("alpha",)),
            _agent(tags=("beta",)),
            _agent(tags=("alpha",)),
        ],
        group_fold_level=0,
    )
    alpha = [
        e
        for e in entries
        if e.kind == "group" and e.group is not None and e.group.group_key == ("alpha",)
    ]
    assert len(alpha) == 1
    assert alpha[0].group.agent_indices == (0, 2)  # type: ignore[union-attr]


def test_fold_level_1_emits_tag_and_project_banners_only() -> None:
    entries = build_agent_tree(
        [
            _agent(cl_name="demo-a", project_file="/r/proj.gp", tags=("alpha",)),
            _agent(cl_name="demo-b", project_file="/r/proj.gp", tags=("alpha",)),
            _agent(cl_name="demo-a", project_file="/r/other.gp", tags=("beta",)),
        ],
        group_fold_level=1,
    )
    levels = [e.group.level for e in entries if e.kind == "group"]  # type: ignore[union-attr]
    # alpha: tag + 2 projects;  beta: tag + 1 project
    assert levels == [0, 1, 1, 0, 1]
    assert all(e.kind == "group" for e in entries)


def test_fold_level_2_emits_name_root_banners_but_no_agent_rows() -> None:
    entries = build_agent_tree(
        [
            _agent(cl_name="demo", agent_name="coder.claude", tags=("alpha",)),
            _agent(cl_name="demo", agent_name="coder.codex", tags=("alpha",)),
            _agent(cl_name="demo", agent_name="planner.claude", tags=("alpha",)),
        ],
        group_fold_level=2,
    )
    levels = [e.group.level for e in entries if e.kind == "group"]  # type: ignore[union-attr]
    # tag + project + only the multi-entry coder name-root.
    # The singleton planner root is suppressed.
    assert levels == [0, 1, 2]
    assert all(e.kind == "group" for e in entries)


def test_fold_level_2_emits_banner_for_each_multi_entry_name_root() -> None:
    """Two name-roots, each with two entries → two level-2 banners."""
    entries = build_agent_tree(
        [
            _agent(cl_name="demo", agent_name="coder.claude", tags=("alpha",)),
            _agent(cl_name="demo", agent_name="coder.codex", tags=("alpha",)),
            _agent(cl_name="demo", agent_name="planner.claude", tags=("alpha",)),
            _agent(cl_name="demo", agent_name="planner.codex", tags=("alpha",)),
        ],
        group_fold_level=2,
    )
    levels = [e.group.level for e in entries if e.kind == "group"]  # type: ignore[union-attr]
    assert levels == [0, 1, 2, 2]
    assert all(e.kind == "group" for e in entries)


def test_fold_level_2_skips_singleton_name_root_banner() -> None:
    """Collapsed-tree builder also suppresses singleton level-2 banners."""
    entries = build_agent_tree(
        [_agent(cl_name="demo", agent_name="solo.claude", tags=("alpha",))],
        group_fold_level=2,
    )
    # Tag + project banners only — no level-2 banner for the singleton root.
    levels = [e.group.level for e in entries if e.kind == "group"]  # type: ignore[union-attr]
    assert levels == [0, 1]


def test_singleton_name_root_emits_no_banner_among_other_roots() -> None:
    """Mixed scenario: multi-entry root keeps its banner, singleton root does not."""
    entries = build_agent_tree(
        [
            _agent(cl_name="demo", agent_name="coder.claude"),
            _agent(cl_name="demo", agent_name="coder.codex"),
            _agent(cl_name="demo", agent_name="solo.gemini"),
        ]
    )
    # tag + project + coder name-root + agent 0 + agent 1 + agent 2
    # (solo.gemini gets no level-2 banner because it's a singleton root).
    assert _kinds(entries) == [
        ("group", 0),
        ("group", 1),
        ("group", 2),
        ("agent", 0),
        ("agent", 1),
        ("agent", 2),
    ]
    name_root_banners = [
        e
        for e in entries
        if e.kind == "group" and e.group is not None and e.group.level == 2
    ]
    assert len(name_root_banners) == 1
    assert name_root_banners[0].group.group_key[-1] == "coder"  # type: ignore[union-attr]


def test_fold_level_3_matches_phase_3_behavior() -> None:
    a = _agent(cl_name="demo", agent_name="coder.claude")
    entries_default = build_agent_tree([a])
    entries_l3 = build_agent_tree([a], group_fold_level=3)
    assert _kinds(entries_default) == _kinds(entries_l3)


# --- Phase 4: banner summaries ---


def test_compute_banner_summary_counts_running_failed_awaiting() -> None:
    agents = [
        _agent(cl_name="a", status="RUNNING"),
        _agent(cl_name="b", status="FAILED"),
        _agent(cl_name="c", status="QUESTION"),
        _agent(cl_name="d", status="DONE"),
    ]
    group = GroupRow(level=0, group_key=("",), agent_indices=(0, 1, 2, 3))
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
    group = GroupRow(level=0, group_key=("",), agent_indices=(0, 1))
    summary = compute_banner_summary(group, [parent, child])
    # Only the parent counts.
    assert summary.count == 1
    assert summary.running == 1


def test_banner_summary_text_renders_chips_separated_by_dots() -> None:
    agents = [
        _agent(cl_name="a", status="RUNNING"),
        _agent(cl_name="b", status="FAILED"),
    ]
    group = GroupRow(level=0, group_key=("",), agent_indices=(0, 1))
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
    group = GroupRow(level=0, group_key=("",), agent_indices=(0, 1))
    summary = compute_banner_summary(group, agents)
    assert summary.failed == 2


def test_banner_summary_text_empty_when_count_is_zero() -> None:
    agents: list[Agent] = []
    group = GroupRow(level=0, group_key=("",), agent_indices=())
    summary = compute_banner_summary(group, agents)
    assert banner_summary_text(summary) == ""


# --- Phase 4: snap-to-ancestor helper ---


def test_find_visible_ancestor_banner_picks_deepest_match() -> None:
    """Snap-to-ancestor focuses the deepest banner containing the agent."""
    a = _agent(cl_name="demo", agent_name="coder.claude", tags=("alpha",))
    b = _agent(cl_name="demo", agent_name="coder.codex", tags=("alpha",))
    entries = build_agent_tree([a, b], group_fold_level=2)
    # At L2 we have tag, project, name-root banners; agents are hidden.
    ancestor = find_visible_ancestor_banner(entries, target_agent_idx=0)
    assert ancestor is not None
    assert ancestor.level == 2  # name-root banner is the deepest match


def test_find_visible_ancestor_banner_falls_back_to_higher_level() -> None:
    """When fold hides the deepest level, fall back to the highest visible."""
    a = _agent(cl_name="demo", agent_name="coder.claude", tags=("alpha",))
    entries = build_agent_tree([a], group_fold_level=0)
    ancestor = find_visible_ancestor_banner(entries, target_agent_idx=0)
    assert ancestor is not None
    assert ancestor.level == 0


def test_find_visible_ancestor_banner_falls_back_when_root_singleton() -> None:
    """A singleton-root agent has no level-2 banner; falls back to project."""
    a = _agent(cl_name="demo", agent_name="solo.claude", tags=("alpha",))
    entries = build_agent_tree([a], group_fold_level=2)
    ancestor = find_visible_ancestor_banner(entries, target_agent_idx=0)
    assert ancestor is not None
    # No level-2 banner exists for this singleton root, so the project
    # banner is the deepest match.
    assert ancestor.level == 1


def test_find_visible_ancestor_banner_returns_none_when_idx_unknown() -> None:
    a = _agent(tags=("alpha",))
    entries = build_agent_tree([a], group_fold_level=0)
    assert find_visible_ancestor_banner(entries, target_agent_idx=42) is None


# --- Dedupe + deterministic group ordering ---


def _group_keys(entries: list[TreeEntry], level: int) -> list[tuple[str, ...]]:
    return [
        e.group.group_key  # type: ignore[union-attr]
        for e in entries
        if e.kind == "group" and e.group is not None and e.group.level == level
    ]


def test_full_tree_does_not_split_untagged_group() -> None:
    """Members of ``(untagged)`` interleaved with a named tag render once."""
    a = _agent(tags=())
    b = _agent(tags=("x",))
    c = _agent(tags=())
    entries = build_agent_tree([a, b, c])
    tag_keys = _group_keys(entries, level=0)
    # Named tag first, untagged second — each appears once.
    assert tag_keys == [("x",), ("",)]
    untagged = [
        e
        for e in entries
        if e.kind == "group"
        and e.group is not None
        and e.group.level == 0
        and e.group.group_key == ("",)
    ]
    assert len(untagged) == 1
    assert untagged[0].group.agent_indices == (0, 2)  # type: ignore[union-attr]


def test_full_tree_sort_is_deterministic() -> None:
    """Same agents in different orders produce identical tree shapes."""
    a = _agent(cl_name="a", tags=("alpha",))
    b = _agent(cl_name="b", tags=("beta",))
    c = _agent(cl_name="c", tags=())

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


def test_full_tree_named_tags_sort_before_untagged() -> None:
    """Named tags sort lex; ``(untagged)`` always sorts last."""
    entries = build_agent_tree(
        [
            _agent(tags=("beta",)),
            _agent(tags=()),
            _agent(tags=("alpha",)),
        ]
    )
    assert _group_keys(entries, level=0) == [("alpha",), ("beta",), ("",)]


def test_full_tree_workflow_children_stay_with_parent_after_sort() -> None:
    """Workflow children keep parent-adjacent ordering even with an interloper."""
    parent = _agent(cl_name="demo", agent_name="solo", raw_suffix="ts1")
    child1 = _agent(
        cl_name="step1",
        agent_name="step1",
        parent_workflow="solo",
        parent_timestamp="ts1",
    )
    other = _agent(cl_name="other", agent_name="other", tags=("x",))
    child2 = _agent(
        cl_name="step2",
        agent_name="step2",
        parent_workflow="solo",
        parent_timestamp="ts1",
    )
    # Input order interleaves the workflow steps with the @x agent.
    entries = build_agent_tree([parent, child1, other, child2])

    agent_order = [e.agent_idx for e in entries if e.kind == "agent"]
    # @x sorts first (named tag), then untagged parent + both children.
    assert agent_order == [2, 0, 1, 3]

    # Both groups appear exactly once.
    assert _group_keys(entries, level=0) == [("x",), ("",)]


def test_full_tree_singleton_name_root_still_suppressed_after_sort() -> None:
    """Sort-driven walk doesn't regress the singleton name-root suppression."""
    # Two coder.* (multi-entry root) + one solo.gemini (singleton root),
    # input order interleaved to force the walk reorder.
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
        if e.kind == "group" and e.group is not None and e.group.level == 2
    ]
    # Only the multi-entry "coder" root has a banner — solo.gemini stays bare.
    assert len(name_root_banners) == 1
    assert name_root_banners[0].group.group_key[-1] == "coder"  # type: ignore[union-attr]


def test_full_tree_reproduces_user_snapshot_shape() -> None:
    """Roughly-19 untagged agents + 1 @name_level emit exactly one banner each.

    Mirrors the user-supplied snapshot where ``(untagged)`` was rendered
    twice, sandwiching the lone ``@name_level`` group.
    """
    name_roots = ["q", "p", "i", "j", "k", "l", "n", "o", "r"]
    untagged_agents = []
    # 9 dotted agents across distinct name roots + 10 dotless agents.
    for i, root in enumerate(name_roots):
        untagged_agents.append(_agent(cl_name=f"cl{i}", agent_name=f"{root}.plan"))
    for i in range(10):
        untagged_agents.append(_agent(cl_name=f"plain{i}", agent_name="solo"))
    tagged = _agent(cl_name="lonely", agent_name="lonely", tags=("name_level",))

    # Interleave the tagged agent into the middle of the untagged list to
    # mimic the snapshot's ordering.
    agents = untagged_agents[:5] + [tagged] + untagged_agents[5:]
    assert len(agents) == 20

    entries = build_agent_tree(agents)
    tag_banners = [
        e
        for e in entries
        if e.kind == "group" and e.group is not None and e.group.level == 0
    ]
    keys = [b.group.group_key for b in tag_banners]  # type: ignore[union-attr]
    assert keys.count(("name_level",)) == 1
    assert keys.count(("",)) == 1
    # Named tag sorts before (untagged).
    assert keys == [("name_level",), ("",)]


def test_collapsed_tree_order_is_deterministic() -> None:
    """Headers-only fold respects the same deterministic ordering."""
    a = _agent(cl_name="a", tags=("alpha",))
    b = _agent(cl_name="b", tags=("beta",))
    c = _agent(cl_name="c", tags=())

    order1 = build_agent_tree([a, b, c], group_fold_level=2)
    order2 = build_agent_tree([c, a, b], group_fold_level=2)
    order3 = build_agent_tree([b, c, a], group_fold_level=2)

    def banner_keys(entries: list[TreeEntry]) -> list[tuple[int, tuple[str, ...]]]:
        return [
            (e.group.level, e.group.group_key)  # type: ignore[union-attr]
            for e in entries
            if e.kind == "group" and e.group is not None
        ]

    assert banner_keys(order1) == banner_keys(order2) == banner_keys(order3)

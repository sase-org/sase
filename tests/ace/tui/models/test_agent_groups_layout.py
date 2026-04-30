"""Tree layout shape: project / ChangeSpec / name-root banners."""

from __future__ import annotations

from sase.ace.tui.models.agent_group_fold import AgentGroupFoldRegistry
from sase.ace.tui.models.agent_groups import (
    NO_CHANGESPEC_LABEL,
    GroupRow,
    banner_label,
    build_agent_tree,
)

from ._agent_groups_helpers import _agent, _group_keys, _kinds

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


def test_dotless_parent_groups_with_dotted_resume_child() -> None:
    a = _agent(cl_name="demo", agent_name="foo")
    b = _agent(cl_name="demo", agent_name="foo.r1")
    entries = build_agent_tree([a, b])
    assert _kinds(entries) == [
        ("group", 0),
        ("group", 1),
        ("group", 2),
        ("agent", 0),
        ("agent", 1),
    ]
    assert _group_keys(entries, level=2) == [("repo", "demo", "foo")]


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


def test_project_scoped_agent_does_not_emit_duplicate_changespec_banner() -> None:
    """Project agents have a display cl_name but no real ChangeSpec bucket."""
    a = _agent(cl_name="home", project_file="/r/home/home.gp")
    entries = build_agent_tree([a])
    assert _kinds(entries) == [("group", 0), ("agent", 0)]
    assert _group_keys(entries, level=0) == [("home",)]
    assert _group_keys(entries, level=1) == []


def test_project_scoped_panel_keeps_name_root_at_level_one() -> None:
    a = _agent(
        cl_name="home", project_file="/r/home/home.gp", agent_name="coder.claude"
    )
    b = _agent(cl_name="home", project_file="/r/home/home.gp", agent_name="coder.codex")
    entries = build_agent_tree([a, b])
    assert _kinds(entries) == [
        ("group", 0),
        ("group", 1),
        ("agent", 0),
        ("agent", 1),
    ]
    assert _group_keys(entries, level=1) == [("home", "coder")]


def test_project_scoped_workflow_child_does_not_force_changespec_level() -> None:
    parent = _agent(
        cl_name="home",
        project_file="/r/home/home.gp",
        agent_name="coder.claude",
        raw_suffix="ts1",
    )
    child = _agent(
        cl_name="step",
        project_file="/r/home/home.gp",
        agent_name="step.bash",
        parent_workflow="coder",
        parent_timestamp="ts1",
    )
    entries = build_agent_tree([parent, child])
    assert _kinds(entries) == [("group", 0), ("group", 1), ("agent", 0), ("agent", 1)]
    assert _group_keys(entries, level=1) == [("home", "coder")]


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


def test_mixed_panel_puts_project_scoped_agent_in_synthetic_bucket() -> None:
    a = _agent(cl_name="fix-a", project_file="/r/home/home.gp")
    b = _agent(cl_name="home", project_file="/r/home/home.gp")
    entries = build_agent_tree([a, b])
    assert _group_keys(entries, level=1) == [("home", "fix-a"), ("home", "")]
    assert ("home", "home") not in _group_keys(entries, level=1)


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

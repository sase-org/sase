"""Tests for the three-level agent grouping tree."""

from __future__ import annotations

from datetime import datetime

from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_groups import (
    GroupRow,
    TreeEntry,
    banner_label,
    build_agent_tree,
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
) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name=cl_name,
        project_file=project_file,
        status="RUNNING",
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


def test_named_agent_emits_name_root_banner_when_name_has_dot() -> None:
    a = _agent(cl_name="demo", agent_name="coder.claude")
    entries = build_agent_tree([a])
    # Tag, project, name-root, agent.
    assert _kinds(entries) == [
        ("group", 0),
        ("group", 1),
        ("group", 2),
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


def test_non_contiguous_same_tag_emits_repeated_banners() -> None:
    """Same primary tag interleaved with another tag produces repeated banners.

    The repeated banners still reference the *full* agent index set so that
    Phase 4's group selection can target every member regardless of layout.
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
    assert len(alpha_banners) == 2
    for b_entry in alpha_banners:
        assert b_entry.group.agent_indices == (0, 2)  # type: ignore[union-attr]

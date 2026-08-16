"""Agent-row coverage for compact clan member count chips."""

from __future__ import annotations

from datetime import datetime

from sase.ace.tui.models._agent_clan import ClanStatusCounts
from sase.ace.tui.models._agent_tree import project_clan_tree
from sase.ace.tui.models.agent import Agent, AgentType, AttemptRecord
from sase.ace.tui.widgets._agent_list_rendering import format_agent_option
from sase.ace.tui.widgets.agent_list import _compute_fold_annotation


def _agent(*, suffix: str, status: str = "RUNNING") -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name="family",
        project_file="/tmp/family.sase",
        status=status,
        start_time=datetime(2026, 7, 17, 12, 0, 0),
        raw_suffix=suffix,
    )


def _family_root() -> Agent:
    root = _agent(suffix="root", status="WAITING")
    root.agent_family_parallel = True
    statuses = ("QUESTION", "RUNNING", "STARTING", "QUEUED", "FAILED", "DONE")
    for index, status in enumerate(statuses):
        member = _agent(suffix=f"member-{index}", status=status)
        member.agent_family_parallel = True
        member.parent_timestamp = root.raw_suffix
        if status == "QUEUED":
            member.pid = 100
            member.wait_runners = 9
            member.slot_requested_at = "2026-07-17T12:00:00Z"
        root.runtime_children.append(member)

    # Serial children and the root itself are not members of the count bundle.
    root.runtime_children.append(_agent(suffix="serial", status="DONE"))
    return root


def _attempt() -> AttemptRecord:
    return AttemptRecord(
        attempt_number=1,
        status="failed",
        start_epoch=1.0,
        end_epoch=2.0,
        model=None,
        used_fallback=False,
        error_snippet="boom",
        error_full="boom",
        live_reply_path="/nonexistent/live_reply.md",
        timestamps_path="/nonexistent/live_reply_timestamps.jsonl",
    )


def _clan_container() -> Agent:
    clan = _agent(suffix="clan", status="RUNNING")
    clan.cl_name = "research"
    clan.agent_name = "research"
    clan.is_clan_container = True
    clan.agent_clan = "research"
    clan.agent_clan_generation = "gen"
    statuses = ("QUESTION", "RUNNING", "STARTING", "QUEUED", "FAILED", "DONE")
    for index, status in enumerate(statuses):
        member = _agent(suffix=f"member-{index}", status=status)
        member.cl_name = f"research.member-{index}"
        member.agent_name = f"research.member-{index}"
        member.agent_clan = "research"
        member.agent_clan_generation = "gen"
        if status == "QUEUED":
            member.pid = 100
            member.wait_runners = 9
            member.slot_requested_at = "2026-07-17T12:00:00Z"
        clan.runtime_children.append(member)
    return clan


def test_collapsed_family_row_keeps_fold_retry_annotation_without_chip() -> None:
    root = _family_root()
    root.attempt_history.append(_attempt())
    annotation = _compute_fold_annotation(
        root,
        {root.raw_suffix: (7, 2)},
        set(),
        set(),
    )

    left, _, _ = format_agent_option(
        root,
        0,
        is_selected=False,
        fold_annotation=annotation,
    )

    assert annotation == " ×9 ↻1"
    assert " ×9 ↻1" in left.plain
    assert "[S1 R2 Q1 F1 D1]" not in left.plain
    assert " running" not in left.plain
    assert " done" not in left.plain
    assert " · " not in left.plain


def test_expanded_family_row_keeps_hidden_child_annotation_without_chip() -> None:
    root = _family_root()
    annotation = _compute_fold_annotation(
        root,
        {root.raw_suffix: (7, 2)},
        {root.raw_suffix},
        {root.raw_suffix},
    )

    left, _, _ = format_agent_option(
        root,
        0,
        is_selected=False,
        fold_annotation=annotation,
        is_expanded=True,
    )

    assert annotation == " ×9 +2"
    assert " ×9 +2" in left.plain
    assert "[S1 R2 Q1 F1 D1]" not in left.plain


def test_expanded_family_row_without_structural_annotation_omits_chip() -> None:
    root = _family_root()
    annotation = _compute_fold_annotation(
        root,
        {root.raw_suffix: (7, 0)},
        {root.raw_suffix},
        set(),
    )

    left, _, _ = format_agent_option(
        root,
        0,
        is_selected=False,
        fold_annotation=annotation,
        is_expanded=True,
    )

    assert annotation == ""
    assert "[S1 R2 Q1 F1 D1]" not in left.plain


def test_clan_row_renders_direct_member_count_chip() -> None:
    clan = _clan_container()

    left, _, _ = format_agent_option(
        clan,
        0,
        is_selected=False,
        unread_agent_ids={clan.runtime_children[-1].identity},
    )

    assert "[S1 R2 Q1 F1 U1]" in left.plain


def test_family_inside_clan_omits_chip_and_member_unread_suffix() -> None:
    family = _agent(suffix="family", status="DONE")
    family.cl_name = "research.writer"
    family.agent_name = "research.writer"
    family.agent_family = "research.writer"
    family.agent_family_role = "root"
    family.agent_clan = "research"
    family.agent_clan_generation = "gen"
    member = _agent(suffix="member", status="DONE")
    member.cl_name = "research.writer--code"
    member.agent_name = "research.writer--code"
    member.agent_family = "research.writer"
    member.agent_family_role = "code"
    member.parent_timestamp = family.raw_suffix
    member.agent_clan = "research"
    member.agent_clan_generation = "gen"
    family.runtime_children = [member]
    family.followup_agents = [member]
    _clan, projected_family, projected_member = project_clan_tree([family, member])

    family_left, family_suffix, _ = format_agent_option(
        projected_family,
        0,
        is_selected=False,
        unread_agent_ids={projected_member.identity},
    )
    member_left, member_suffix, _ = format_agent_option(
        projected_member,
        1,
        is_selected=False,
        is_unread=True,
    )

    assert "[U1]" not in family_left.plain
    assert "✅" not in family_suffix.plain
    assert "❌" not in family_suffix.plain
    assert "✅" not in member_left.plain
    assert "✅" not in member_suffix.plain
    assert "❌" not in member_suffix.plain


def test_non_family_and_zero_bucket_rows_omit_count_chip() -> None:
    non_family = _agent(suffix="plain")
    zero_count_root = _agent(suffix="zero-count")

    non_family_left, _, _ = format_agent_option(non_family, 0, is_selected=False)
    zero_count_left, _, _ = format_agent_option(
        zero_count_root,
        1,
        is_selected=False,
        clan_counts=ClanStatusCounts(),
    )

    assert "[S" not in non_family_left.plain
    assert "[R" not in non_family_left.plain
    assert "[D" not in non_family_left.plain
    assert "[S" not in zero_count_left.plain
    assert "[R" not in zero_count_left.plain
    assert "[D" not in zero_count_left.plain


def test_slot_queued_leaf_row_omits_count_chip() -> None:
    leaf = _agent(suffix="queued", status="QUEUED")
    leaf.pid = 100
    leaf.wait_runners = 9
    leaf.wait_runners_explicit = True
    leaf.slot_requested_at = "2026-07-17T12:00:00Z"

    left, _, _ = format_agent_option(
        leaf,
        0,
        is_selected=False,
        now=datetime(2026, 7, 17, 12, 1, 0),
    )

    assert "[Q" not in left.plain

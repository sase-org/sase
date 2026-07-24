"""Agent-row coverage for compact parallel-family member count chips."""

from __future__ import annotations

from datetime import datetime

from sase.ace.tui.models._agent_parallel_family import ParallelFamilyStatusCounts
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
    statuses = ("QUESTION", "RUNNING", "STARTING", "WAITING", "FAILED", "DONE")
    for index, status in enumerate(statuses):
        member = _agent(suffix=f"member-{index}", status=status)
        member.agent_family_parallel = True
        member.parent_timestamp = root.raw_suffix
        if status == "WAITING":
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


def test_collapsed_family_row_combines_fold_retry_annotation_and_chip() -> None:
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
    assert " ×9 ↻1 [S1 R2 Q1 W1 F1 D1]" in left.plain
    assert " running" not in left.plain
    assert " done" not in left.plain
    assert " · " not in left.plain


def test_expanded_family_row_keeps_chip_with_hidden_child_annotation() -> None:
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
    assert " ×9 +2 [S1 R2 Q1 W1 F1 D1]" in left.plain


def test_expanded_family_row_without_structural_annotation_keeps_chip() -> None:
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
    assert "[S1 R2 Q1 W1 F1 D1]" in left.plain


def test_non_family_and_zero_bucket_rows_omit_count_chip() -> None:
    non_family = _agent(suffix="plain")
    zero_count_root = _agent(suffix="zero-count")

    non_family_left, _, _ = format_agent_option(non_family, 0, is_selected=False)
    zero_count_left, _, _ = format_agent_option(
        zero_count_root,
        1,
        is_selected=False,
        parallel_family_counts=ParallelFamilyStatusCounts(),
    )

    assert "[S" not in non_family_left.plain
    assert "[R" not in non_family_left.plain
    assert "[D" not in non_family_left.plain
    assert "[S" not in zero_count_left.plain
    assert "[R" not in zero_count_left.plain
    assert "[D" not in zero_count_left.plain

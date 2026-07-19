"""Fold-aware tribe document rendering tests."""

from __future__ import annotations

from datetime import datetime

import pytest

from sase.ace.tui.models._agent_clan_sections import ClanTextEntry
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_tribe_summary import (
    build_agent_tribe_summary_snapshot,
)
from sase.ace.tui.models.fold_state import FoldLevel
from sase.ace.tui.widgets.prompt_panel._agent_display_tribe import (
    build_tribe_detail_text,
    tribe_enrichment_sections_for_fold_state,
)
from sase.ace.tui.widgets.prompt_panel._agent_tribe_aggregation import (
    TribeRuntimeStatistics,
    TribeSectionSnapshot,
    TribeTextEntry,
    _TribeDiskSnapshot,
)
from sase.ace.tui.widgets.prompt_panel._member_roster import MemberJumpMap
from sase.ace.tui.widgets.prompt_panel._section_navigation import (
    SECTION_MARKER_META_KEY,
)

_NOW = datetime(2026, 7, 18, 15, 0, 0)


def _agent(
    name: str,
    status: str,
    *,
    suffix: str,
    family: str | None = None,
    role: str | None = None,
    parent: str | None = None,
) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name=name,
        project_file="/tmp/demo.sase",
        status=status,
        start_time=datetime(2026, 7, 18, 14, 0, 0),
        run_start_time=datetime(2026, 7, 18, 14, 0, 0),
        stop_time=_NOW if status == "FAILED" else None,
        raw_suffix=suffix,
        agent_name=name,
        agent_family=family,
        agent_family_role="root" if role == "plan" else role,
        role_suffix=f"--{role}" if role else None,
        plan_chain_root=role == "plan",
        parent_timestamp=parent,
        model="gpt-5",
    )


def _snapshot():  # type: ignore[no-untyped-def]
    root = _agent(
        "build--plan",
        "RUNNING",
        suffix="root",
        family="build",
        role="plan",
    )
    child = _agent(
        "build--code",
        "WAITING",
        suffix="child",
        family="build",
        role="code",
        parent="root",
    )
    child.activity = "writing tests"
    child.workspace_num = 8
    root.followup_agents = [child]
    failed = _agent("failed", "FAILED", suffix="failed")
    failed.error_message = "Build failed\nSecond error detail"
    failed.error_traceback = "Traceback line one\nValueError: broken"
    failed.output_variables = {"report": "summary line\nfull report detail"}
    failed.step_output = {"meta_release_notes": "ready\nrelease detail"}
    return build_agent_tribe_summary_snapshot(
        "epic",
        [root, child, failed],
        panel_collapsed=True,
        marked_ids={child.identity},
        now=_NOW,
    )


def test_tribe_levels_have_distinct_glance_triage_inspect_and_forensics_jobs() -> None:
    snapshot = _snapshot()
    published: list[MemberJumpMap] = []

    pulse = build_tribe_detail_text(
        snapshot,
        fold_level=FoldLevel.COLLAPSED,
        member_jump_map_publisher=published.append,
    ).plain
    roster = build_tribe_detail_text(
        snapshot,
        fold_level=FoldLevel.EXPANDED,
        member_jump_map_publisher=published.append,
    ).plain
    members = build_tribe_detail_text(
        snapshot,
        fold_level=FoldLevel.FULLY_EXPANDED,
    ).plain
    forensics = build_tribe_detail_text(
        snapshot,
        fold_level=FoldLevel.EXHAUSTIVE,
    ).plain

    assert pulse.startswith(
        "TRIBE\nName: @epic\nStatus: FAILED [R1 F1]\n"
        "Composition: 1 family · 3 agents · 1 nested\n"
        "Runtime: 1h\nFold: 1/4\n"
    )
    assert "▸ NEEDS ATTENTION · 1\n• failed · FAILED · Build failed" in pulse
    assert "▸ ❖ TRIBE MEMBERS · 2\n" in pulse
    assert " 0  [✓] build · family" in pulse
    assert " 1  failed · agent" in pulse
    assert published[0].targets

    assert "Fold: 2/4\n" in roster
    assert " 0  [✓] build · family" in roster
    assert " 1  failed · agent" in roster
    assert "--code" not in roster
    assert "• failed · Build failed" in roster
    assert published[1].container_identity == ("panel", "epic")
    assert [target.member_identity for target in published[1].targets] == [
        snapshot.units[0].identity,
        snapshot.units[1].identity,
    ]

    assert "Fold: 3/4\n" in members
    assert "└─ [✓] --code" in members
    assert "writing tests" in members
    assert "ws 8" not in members
    assert "Second error detail" in members
    assert "ValueError: broken" not in members
    assert "full report detail" in members
    assert "release detail" in members

    assert "Fold: 4/4\n" in forensics
    assert "ws 8" in forensics
    assert "ValueError: broken" in forensics
    assert pulse != roster != members != forensics


def test_tribe_section_overrides_are_scoped_and_publish_anchors() -> None:
    detail = build_tribe_detail_text(
        _snapshot(),
        fold_level=FoldLevel.COLLAPSED,
        section_fold_overrides={
            "tribe:members": FoldLevel.EXPANDED,
            "tribe:errors": FoldLevel.EXHAUSTIVE,
        },
    )

    assert "▾ ❖ TRIBE MEMBERS · 2" in detail.plain
    assert " 0  [✓] build · family" in detail.plain
    assert "Second error detail" in detail.plain
    anchors = [
        span.style.meta[SECTION_MARKER_META_KEY]
        for span in detail.spans
        if getattr(span.style, "meta", None)
        and SECTION_MARKER_META_KEY in span.style.meta
    ]
    assert anchors == [
        "tribe:needs-attention",
        "tribe:members",
        "tribe:member:build",
        "tribe:member:failed",
        "tribe:errors",
        "tribe:output-variables",
        "tribe:workflow-variables",
    ]


def test_cheap_tribe_paint_is_header_only() -> None:
    detail = build_tribe_detail_text(
        _snapshot(),
        fold_level=FoldLevel.EXHAUSTIVE,
        cheap=True,
    ).plain

    assert "Fold: 4/4" in detail
    assert "NEEDS ATTENTION" not in detail
    assert "TRIBE MEMBERS" not in detail


def test_every_level_requests_disk_presence_and_forensics_adds_statistics() -> None:
    assert tribe_enrichment_sections_for_fold_state(FoldLevel.COLLAPSED) == frozenset(
        {"replies", "slow-tool-calls"}
    )
    assert tribe_enrichment_sections_for_fold_state(FoldLevel.EXPANDED) == frozenset(
        {"replies", "slow-tool-calls"}
    )
    assert tribe_enrichment_sections_for_fold_state(
        FoldLevel.FULLY_EXPANDED
    ) == frozenset({"replies", "slow-tool-calls"})
    assert tribe_enrichment_sections_for_fold_state(FoldLevel.EXHAUSTIVE) == frozenset(
        {"replies", "slow-tool-calls", "runtime-statistics"}
    )


def test_unknown_sections_render_one_scanning_tail_without_placeholder_headings() -> (
    None
):
    snapshot = _snapshot()
    sections = TribeSectionSnapshot(
        panel_identity=snapshot.container_identity,
        source_signature=(),
        loading_sections=frozenset({"replies", "slow-tool-calls"}),
    )

    pulse = build_tribe_detail_text(
        snapshot,
        section_snapshot=sections,
        fold_level=FoldLevel.COLLAPSED,
    ).plain
    members = build_tribe_detail_text(
        snapshot,
        section_snapshot=sections,
        fold_level=FoldLevel.FULLY_EXPANDED,
    ).plain

    for rendered in (pulse, members):
        assert "REPLIES" not in rendered
        assert "SLOW TOOL CALLS" not in rendered
        assert "loading…" not in rendered
        assert rendered.count("⋯ scanning member data…") == 1


def test_empty_sections_are_omitted_at_every_level() -> None:
    snapshot = build_agent_tribe_summary_snapshot(
        "empty",
        [],
        panel_collapsed=True,
        now=_NOW,
    )
    sections = TribeSectionSnapshot(
        panel_identity=snapshot.container_identity,
        source_signature=(),
        disk=_TribeDiskSnapshot(
            loaded_sections=frozenset({"replies", "slow-tool-calls"}),
            replies=(),
            slow_tool_calls=(),
        ),
        runtime_statistics_loaded=True,
    )

    for level in FoldLevel:
        rendered = build_tribe_detail_text(
            snapshot,
            section_snapshot=sections,
            fold_level=level,
        ).plain

        assert "Composition: 0 agents" in rendered
        assert "NEEDS ATTENTION" not in rendered
        assert "TRIBE MEMBERS" not in rendered
        assert "ERRORS" not in rendered
        assert "OUTPUT VARIABLES" not in rendered
        assert "WORKFLOW VARIABLES" not in rendered
        assert "REPLIES" not in rendered
        assert "SLOW TOOL CALLS" not in rendered
        assert "RUNTIME STATISTICS" not in rendered
        assert "⋯ scanning member data…" not in rendered


def test_loaded_replies_follow_the_four_level_content_ladder() -> None:
    snapshot = _snapshot()
    unit = snapshot.units[0]
    replies = tuple(
        TribeTextEntry(
            unit_identity=unit.identity,
            unit_label=unit.label,
            entry=ClanTextEntry(
                member_identity=unit.identity,
                member_label=f"member-{index}",
                kind="response",
                preview=f"preview-{index}",
                body=f"preview-{index}\nfull-{index}",
            ),
        )
        for index in range(9)
    )
    sections = TribeSectionSnapshot(
        panel_identity=snapshot.container_identity,
        source_signature=(),
        disk=_TribeDiskSnapshot(
            loaded_sections=frozenset({"replies", "slow-tool-calls"}),
            replies=replies,
            slow_tool_calls=(),
        ),
        runtime_statistics_loaded=True,
    )
    rendered = {
        level: build_tribe_detail_text(
            snapshot,
            section_snapshot=sections,
            fold_level=level,
        ).plain
        for level in FoldLevel
    }

    glance = rendered[FoldLevel.COLLAPSED]
    triage = rendered[FoldLevel.EXPANDED]
    inspect = rendered[FoldLevel.FULLY_EXPANDED]
    forensics = rendered[FoldLevel.EXHAUSTIVE]
    assert "▸ REPLIES · 9" in glance
    assert "preview-0" not in glance
    assert "preview-0" in triage and "preview-7" in triage
    assert "preview-8" not in triage and "  +1 more" in triage
    assert "full-0" not in triage
    assert f"{unit.label}\n  member-0" in inspect
    assert "full-0" in inspect and "full-8" not in inspect
    assert "  +1 more" in inspect
    assert "full-8" in forensics
    assert "  +1 more" not in forensics


def test_forensics_runtime_statistics_render_values_and_omit_no_runs() -> None:
    snapshot = _snapshot()
    populated = TribeSectionSnapshot(
        panel_identity=snapshot.container_identity,
        source_signature=(),
        runtime_statistics_loaded=True,
        runtime_statistics=TribeRuntimeStatistics(
            runs=4,
            total_seconds=600.0,
            mean_seconds=150.0,
            p50_seconds=120.0,
            p95_seconds=260.0,
            max_seconds=300.0,
            share=0.25,
        ),
    )
    empty = TribeSectionSnapshot(
        panel_identity=snapshot.container_identity,
        source_signature=(),
        runtime_statistics_loaded=True,
    )

    rendered = build_tribe_detail_text(
        snapshot,
        section_snapshot=populated,
        fold_level=FoldLevel.EXHAUSTIVE,
    ).plain
    no_runs = build_tribe_detail_text(
        snapshot,
        section_snapshot=empty,
        fold_level=FoldLevel.EXHAUSTIVE,
    ).plain

    assert "◆ RUNTIME STATISTICS" in rendered
    assert "Runs: 4 · Share: 25.0%" in rendered
    assert "Total: 10m00s · Mean: 2m30s · p50: 2m00s" in rendered
    assert "p95: 4m20s · Max: 5m00s" in rendered
    assert "RUNTIME STATISTICS" not in no_runs

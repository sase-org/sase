"""Fold-aware tribe document rendering tests."""

from __future__ import annotations

from datetime import datetime

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


def test_tribe_levels_have_distinct_pulse_roster_members_and_forensics_jobs() -> None:
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
        "Composition: 0 clans · 1 family · 3 agents · 1 nested\n"
        "Runtime: 1h\nPanel: collapsed\nFold: 1/4\n"
    )
    assert "▸ NEEDS ATTENTION · 1\n• failed · FAILED · Build failed" in pulse
    assert "▸ ❖ TRIBE MEMBERS · 2\n" in pulse
    assert " 0  build" not in pulse
    assert published[0].targets == ()

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
    assert "Second error detail" not in members

    assert "Fold: 4/4\n" in forensics
    assert "ws 8" in forensics
    assert "Second error detail" in forensics
    assert "ValueError: broken" in forensics
    assert "full report detail" in forensics
    assert "release detail" in forensics


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
        "tribe:replies",
        "tribe:slow-tool-calls",
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


def test_pulse_and_roster_do_not_request_disk_or_statistics() -> None:
    assert tribe_enrichment_sections_for_fold_state(FoldLevel.COLLAPSED) == frozenset()
    assert tribe_enrichment_sections_for_fold_state(FoldLevel.EXPANDED) == frozenset()
    assert tribe_enrichment_sections_for_fold_state(
        FoldLevel.FULLY_EXPANDED
    ) == frozenset({"replies", "slow-tool-calls"})
    assert tribe_enrichment_sections_for_fold_state(FoldLevel.EXHAUSTIVE) == frozenset(
        {"replies", "slow-tool-calls", "runtime-statistics"}
    )


def test_members_render_loading_states_without_render_path_io() -> None:
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

    assert "▸ REPLIES · loading…" in pulse
    assert "▸ SLOW TOOL CALLS · loading…" in pulse
    assert "▼ REPLIES · loading…\n  loading…" in members
    assert "▼ SLOW TOOL CALLS · loading…\n  loading…" in members


def test_forensics_runtime_statistics_render_values_and_no_runs_dash() -> None:
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
    assert "◆ RUNTIME STATISTICS\n  —" in no_runs

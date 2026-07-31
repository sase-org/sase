"""Fold-aware tribe document rendering tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime

import pytest

from sase.ace.tui.models._agent_clan_sections import ClanTextEntry
from sase.ace.tui.models._agent_tree import project_clan_tree
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_tribe_summary import (
    TribeEntryTarget,
    build_agent_tribe_summary_snapshot,
)
from sase.ace.tui.models.fold_state import FoldLevel
import sase.ace.tui.models.tribe_display as tribe_display
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
from sase.ace.tui.widgets.prompt_panel._member_roster import (
    MEMBER_ENTRY_CURSOR_GLYPH,
    MEMBER_ENTRY_CURSOR_STYLE,
    MEMBER_ROSTER_LIMIT,
    MemberJumpMap,
)
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
    failed.output_variables = {
        "report": {
            "findings": [{"file": "src/a.py", "severity": "high"}],
            "passed": True,
            "ratio": 2.5,
            "summary": "summary line",
        }
    }
    failed.step_output = {"meta_release_notes": "ready\nrelease detail"}
    return build_agent_tribe_summary_snapshot(
        "epic",
        [root, child, failed],
        panel_collapsed=True,
        marked_ids={child.identity},
        now=_NOW,
    )


def test_tribe_header_colors_only_the_structured_name_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        tribe_display,
        "load_merged_config",
        lambda: {
            "ace": {
                "tribes": {
                    "epic": {"icon": "▲", "color": "#123456"},
                }
            }
        },
    )
    monkeypatch.setattr(
        tribe_display,
        "current_config_token",
        lambda: ("tribe-header-color",),
    )
    tribe_display._tribe_displays_for_token.cache_clear()

    detail = build_tribe_detail_text(_snapshot())
    name_start = detail.plain.index("▲ @epic")

    assert any(
        span.start <= name_start < span.end and str(span.style) == "bold #123456"
        for span in detail.spans
    )
    assert any(
        span.start <= detail.plain.index("TRIBE") < span.end
        and str(span.style) == "bold #FFD75F underline"
        for span in detail.spans
    )


def test_tribe_description_line_renders_under_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        tribe_display,
        "load_merged_config",
        lambda: {"ace": {"tribes": {"epic": {"description": "Epic phase workers."}}}},
    )
    monkeypatch.setattr(
        tribe_display,
        "current_config_token",
        lambda: ("tribe-description-line",),
    )
    tribe_display._tribe_displays_for_token.cache_clear()

    detail = build_tribe_detail_text(_snapshot())
    description_start = detail.plain.index("Epic phase workers.")

    assert any(
        span.start <= description_start < span.end
        and str(span.style) == "italic #B0B0B0"
        for span in detail.spans
    )


def test_tribe_missing_description_hint_names_the_config_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        tribe_display,
        "load_merged_config",
        lambda: {"ace": {"tribes": {"epic": {"icon": "▲"}}}},
    )
    monkeypatch.setattr(
        tribe_display,
        "current_config_token",
        lambda: ("tribe-description-missing",),
    )
    tribe_display._tribe_displays_for_token.cache_clear()

    detail = build_tribe_detail_text(_snapshot())
    hint = "no description - set ace.tribes.epic.description"
    hint_start = detail.plain.index(hint)

    assert any(
        span.start <= hint_start < span.end and str(span.style) == "italic #D7AF87"
        for span in detail.spans
    )


def test_tribe_missing_description_hint_maps_none_panel_to_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        tribe_display,
        "load_merged_config",
        lambda: {"ace": {"tribes": {"default": {"icon": "⌂"}}}},
    )
    monkeypatch.setattr(
        tribe_display,
        "current_config_token",
        lambda: ("tribe-description-missing-default",),
    )
    tribe_display._tribe_displays_for_token.cache_clear()

    snapshot = build_agent_tribe_summary_snapshot(
        None, [], panel_collapsed=True, now=_NOW
    )
    detail = build_tribe_detail_text(snapshot)

    assert "no description - set ace.tribes.default.description" in detail.plain


def test_tribe_description_with_markup_characters_renders_literally(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        tribe_display,
        "load_merged_config",
        lambda: {"ace": {"tribes": {"epic": {"description": "Has [bold] brackets."}}}},
    )
    monkeypatch.setattr(
        tribe_display,
        "current_config_token",
        lambda: ("tribe-description-markup",),
    )
    tribe_display._tribe_displays_for_token.cache_clear()

    detail = build_tribe_detail_text(_snapshot())

    assert "Has [bold] brackets." in detail.plain


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
        "TRIBE\nName: ▲ @epic\n"
        "  Epic phase-worker clans from sase bead work, one member per phase of an "
        "approved plan.\n"
        "Status: FAILED [R1 F1]\n"
        "Composition: 1 family · 2 lanes · 1 nested\n"
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
    assert "    findings:\n      - file: src/a.py\n        severity: high\n" in members
    assert "    passed: true\n" in members
    assert "    ratio: 2.5\n" in members
    assert "    summary: summary line\n" in members
    assert "release detail" in members

    assert "Fold: 4/4\n" in forensics
    assert "ws 8" in forensics
    assert "ValueError: broken" in forensics
    assert pulse != roster != members != forensics


def test_tribe_structured_variable_lines_have_per_kind_styles() -> None:
    detail = build_tribe_detail_text(
        _snapshot(),
        fold_level=FoldLevel.FULLY_EXPANDED,
    )

    def style_at(needle: str) -> str | None:
        position = detail.plain.index(needle)
        for span in reversed(detail.spans):
            if span.start <= position < span.end:
                return str(span.style)
        return str(detail.style) if detail.style else None

    assert style_at("true") == "italic #AFAFAF"
    assert style_at("2.5") == "#FFAF5F"
    assert style_at("summary line") == "#5FD75F"


def test_expanded_panel_roster_has_fixed_gutter_and_one_target_row() -> None:
    base = _snapshot()
    snapshot = replace(
        base,
        panel_collapsed=False,
        entry_target=TribeEntryTarget(
            unit_identity=base.units[0].identity,
            label="build › --code",
            kind="member",
        ),
    )

    detail = build_tribe_detail_text(
        snapshot,
        fold_level=FoldLevel.FULLY_EXPANDED,
    )
    lines = detail.plain.splitlines()
    target_line = next(line for line in lines if "build · family" in line)
    other_line = next(line for line in lines if "failed · agent" in line)
    child_line = next(line for line in lines if "└─ [✓] --code" in line)
    cursor_lines = [
        line for line in lines if line.startswith(MEMBER_ENTRY_CURSOR_GLYPH)
    ]

    assert "TRIBE MEMBERS · 2 · l ❯ build › --code" in detail.plain
    assert cursor_lines == [target_line]
    assert target_line.startswith("❯  0 ")
    assert other_line.startswith("   1 ")
    assert target_line.index("0") == other_line.index("1")
    assert child_line.startswith("      └─ ")
    cursor_start = detail.plain.index("\n" + target_line) + 1
    assert any(
        span.start <= cursor_start < span.end
        and str(span.style) == MEMBER_ENTRY_CURSOR_STYLE
        for span in detail.spans
    )


@pytest.mark.parametrize(
    ("target", "expected_suffix", "has_row_cursor"),
    [
        (
            "unit",
            " · l ❯ build",
            True,
        ),
        (
            "member",
            " · l ❯ build › --code",
            True,
        ),
        (
            "group",
            " · l ❯ Done (group)",
            False,
        ),
        (
            None,
            None,
            False,
        ),
    ],
)
def test_entry_heading_covers_every_destination_kind(
    target: str | None,
    expected_suffix: str | None,
    has_row_cursor: bool,
) -> None:
    base = _snapshot()
    entry_target = {
        "unit": TribeEntryTarget(base.units[0].identity, "build", "unit"),
        "member": TribeEntryTarget(
            base.units[0].identity,
            "build › --code",
            "member",
        ),
        "group": TribeEntryTarget(None, "Done (group)", "group"),
        None: None,
    }[target]
    snapshot = replace(
        base,
        panel_collapsed=False,
        entry_target=entry_target,
    )

    rendered = build_tribe_detail_text(snapshot).plain
    heading = next(line for line in rendered.splitlines() if "TRIBE MEMBERS" in line)
    cursor_lines = [
        line
        for line in rendered.splitlines()
        if line.startswith(MEMBER_ENTRY_CURSOR_GLYPH)
    ]

    if expected_suffix is None:
        assert " ❯ " not in heading
    else:
        assert expected_suffix in heading
    assert bool(cursor_lines) is has_row_cursor
    assert all(
        line.startswith(("❯ ", "  "))
        for line in rendered.splitlines()
        if " · family · " in line or "failed · agent" in line
    )


def test_collapsed_panel_omits_entry_heading_cursor_and_gutter() -> None:
    base = _snapshot()
    snapshot = replace(
        base,
        entry_target=TribeEntryTarget(
            base.units[0].identity,
            "build",
            "unit",
        ),
    )

    rendered = build_tribe_detail_text(snapshot).plain
    heading = next(line for line in rendered.splitlines() if "TRIBE MEMBERS" in line)
    build_line = next(
        line for line in rendered.splitlines() if "build · family" in line
    )

    assert " ❯ " not in heading
    assert MEMBER_ENTRY_CURSOR_GLYPH not in rendered
    assert build_line.startswith(" 0 ")


def test_hidden_tail_target_keeps_heading_clause_without_a_row_cursor() -> None:
    agents = [
        _agent(
            f"member-{index}",
            "RUNNING",
            suffix=f"member-{index}",
        )
        for index in range(MEMBER_ROSTER_LIMIT + 1)
    ]
    target = agents[-1]
    snapshot = build_agent_tribe_summary_snapshot(
        "epic",
        agents,
        panel_collapsed=False,
        now=_NOW,
        entry_target=TribeEntryTarget(
            target.identity,
            target.agent_name or "",
            "unit",
        ),
    )

    rendered = build_tribe_detail_text(snapshot).plain

    assert f" · l ❯ {target.agent_name}" in rendered
    assert [
        line
        for line in rendered.splitlines()
        if line.startswith(MEMBER_ENTRY_CURSOR_GLYPH)
    ] == []
    assert rendered.count(MEMBER_ENTRY_CURSOR_GLYPH) == 1
    assert "… +1 more members (not numbered)" in rendered


def test_tribe_family_children_use_effective_status_glyphs() -> None:
    root = _agent(
        "build--plan",
        "WORKING TALE",
        suffix="root",
        family="build",
        role="plan",
    )
    planner = _agent(
        "build--plan-step",
        "TALE APPROVED",
        suffix="planner",
        family="build",
        role="plan",
        parent="root",
    )
    planner.agent_family_role = "plan"
    planner.parent_workflow = "ace-run"
    planner.step_type = "agent"
    coder = _agent(
        "build--code",
        "WORKING TALE",
        suffix="coder",
        family="build",
        role="code",
        parent="root",
    )
    root.runtime_children = [planner, coder]
    root.followup_agents = [coder]
    snapshot = build_agent_tribe_summary_snapshot(
        "epic",
        [root, planner, coder],
        panel_collapsed=True,
        now=_NOW,
    )

    detail = build_tribe_detail_text(
        snapshot,
        fold_level=FoldLevel.FULLY_EXPANDED,
    )

    assert "Composition: 1 family · 1 lane · 2 nested" in detail.plain
    assert "[R1 D1]" in detail.plain
    assert "--plan-step · step · ✓ TALE APPROVED" in detail.plain
    assert "--code · agent · ▶ WORKING TALE" in detail.plain


def test_tribe_header_and_clan_unit_render_scoped_queue_count() -> None:
    implicit = _agent(
        "research.implicit",
        "QUEUED",
        suffix="implicit",
    )
    explicit = _agent(
        "research.explicit",
        "WAITING",
        suffix="explicit",
    )
    for agent in (implicit, explicit):
        agent.agent_clan = "research"
        agent.agent_clan_generation = "gen-1"
        agent.pid = 100
    implicit.wait_runners = 9
    implicit.slot_requested_at = "2026-07-18T14:00:00Z"
    explicit.wait_runners = 0
    explicit.wait_runners_explicit = True
    explicit.slot_requested_at = "2026-07-18T14:00:01Z"
    snapshot = build_agent_tribe_summary_snapshot(
        "epic",
        project_clan_tree([implicit, explicit]),
        panel_collapsed=True,
        now=_NOW,
    )

    detail = build_tribe_detail_text(
        snapshot,
        fold_level=FoldLevel.COLLAPSED,
    )

    assert "Status: QUEUED [Q1 W1]\n" in detail.plain
    assert "research · clan · … QUEUED ·" in detail.plain
    assert detail.plain.count("[Q1 W1]") == 2
    for start in (
        index
        for index in range(len(detail.plain))
        if detail.plain.startswith("Q1", index)
    ):
        digit = start + 1
        assert any(
            span.start <= digit < span.end and str(span.style) == "bold #5F87FF"
            for span in detail.spans
        )


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
    assert (
        "Epic phase-worker clans from sase bead work, one member per phase of an "
        "approved plan." in detail
    )
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

        assert "Composition: 0 lanes" in rendered
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

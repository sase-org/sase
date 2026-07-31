"""Tribe enrichment section rendering tests."""

from __future__ import annotations

from sase.ace.tui.models._agent_clan_sections import ClanTextEntry
from sase.ace.tui.models.agent_tribe_summary import build_agent_tribe_summary_snapshot
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
from tests.ace.tui.widgets._agent_display_tribe_helpers import (
    NOW,
    make_tribe_snapshot,
)


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
    snapshot = make_tribe_snapshot()
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
        now=NOW,
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
    snapshot = make_tribe_snapshot()
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
    snapshot = make_tribe_snapshot()
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

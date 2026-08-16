"""Tribe member roster and navigation rendering tests."""

from __future__ import annotations

from dataclasses import replace

import pytest

from sase.ace.tui.models._agent_tree import project_clan_tree
from sase.ace.tui.models.agent_tribe_summary import (
    TribeEntryTarget,
    build_agent_tribe_summary_snapshot,
)
from sase.ace.tui.models.fold_state import FoldLevel
from sase.ace.tui.widgets.prompt_panel._agent_display_tribe import (
    build_tribe_detail_text,
)
from sase.ace.tui.widgets.prompt_panel._member_roster import (
    MEMBER_ENTRY_CURSOR_GLYPH,
    MEMBER_ENTRY_CURSOR_STYLE,
    MEMBER_ROSTER_LIMIT,
)
from sase.ace.tui.widgets.prompt_panel._section_navigation import (
    SECTION_MARKER_META_KEY,
)
from tests.ace.tui.widgets._agent_display_tribe_helpers import (
    NOW,
    make_tribe_agent,
    make_tribe_snapshot,
)


def test_expanded_panel_roster_has_fixed_gutter_and_one_target_row() -> None:
    base = make_tribe_snapshot()
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
    base = make_tribe_snapshot()
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
    base = make_tribe_snapshot()
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
        make_tribe_agent(
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
        now=NOW,
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
    root = make_tribe_agent(
        "build--plan",
        "WORKING TALE",
        suffix="root",
        family="build",
        role="plan",
    )
    planner = make_tribe_agent(
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
    coder = make_tribe_agent(
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
        now=NOW,
    )

    detail = build_tribe_detail_text(
        snapshot,
        fold_level=FoldLevel.FULLY_EXPANDED,
    )

    assert "Composition: 1 family · 1 lane · 2 nested" in detail.plain
    assert "[R1]" in detail.plain
    assert "--plan-step · step · ✓ TALE APPROVED" in detail.plain
    assert "--code · agent · ▶ WORKING TALE" in detail.plain


def test_tribe_header_and_clan_unit_render_scoped_queue_count() -> None:
    implicit = make_tribe_agent(
        "research.implicit",
        "QUEUED",
        suffix="implicit",
    )
    explicit = make_tribe_agent(
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
        now=NOW,
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
        make_tribe_snapshot(),
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
        make_tribe_snapshot(),
        fold_level=FoldLevel.EXHAUSTIVE,
        cheap=True,
    ).plain

    assert "Fold: 4/4" in detail
    assert (
        "Epic phase-worker clans from sase bead work, one member per phase of an "
        "approved plan." in " ".join(detail.split())
    )
    assert "NEEDS ATTENTION" not in detail
    assert "TRIBE MEMBERS" not in detail

"""Foldable clan detail sections in the Agents metadata panel."""

from __future__ import annotations

from datetime import datetime

from sase.ace.tui.models._agent_clan_sections import (
    CLAN_DISK_SECTIONS,
    ClanDiskMemberSnapshot,
    ClanDiskSnapshot,
    ClanSectionSnapshot,
    aggregate_clan_in_memory,
)
from sase.ace.tui.models._agent_tree import project_clan_tree
from sase.ace.tui.models.fold_state import FoldLevel
from sase.ace.tui.widgets.prompt_panel._agent_display_clan import (
    build_clan_detail_text,
    clan_disk_sections_for_fold_state,
)
from tests.ace.tui.widgets._agent_display_clan_helpers import (
    make_clan_agent,
    rich_clan_snapshot,
)


def test_cold_collapsed_summary_hides_unknown_disk_sections_behind_tail() -> None:
    member = make_clan_agent(
        "research.one",
        status="RUNNING",
        start=datetime(2026, 7, 17, 12, 0, 0),
    )
    container = project_clan_tree([member])[0]

    detail = build_clan_detail_text(
        container,
        fold_level=FoldLevel.COLLAPSED,
    ).plain

    assert "Tribes:" not in detail
    assert "Members: 1 agent\n" in detail
    for heading in ("REPLIES", "SASE CONTEXT", "SLOW TOOL CALLS", "PROMPTS"):
        assert heading not in detail
    assert "loading…" not in detail
    assert detail.count("⋯ scanning member data…") == 1
    assert clan_disk_sections_for_fold_state(FoldLevel.COLLAPSED) == (
        CLAN_DISK_SECTIONS
    )


def test_known_empty_disk_sections_disappear_from_collapsed_summary() -> None:
    member = make_clan_agent(
        "research.one",
        status="RUNNING",
        start=datetime(2026, 7, 17, 12, 0, 0),
    )
    container = project_clan_tree([member])[0]
    in_memory = aggregate_clan_in_memory(container)
    disk_member = ClanDiskMemberSnapshot(
        member_identity=member.identity,
        member_label=".one",
        loaded_sections=CLAN_DISK_SECTIONS,
    )
    snapshot = ClanSectionSnapshot(
        in_memory=in_memory,
        disk=ClanDiskSnapshot(
            loaded_sections=CLAN_DISK_SECTIONS,
            members=(disk_member,),
            replies=(),
            prompts=(),
            context_lanes=(),
            slow_tool_calls=(),
        ),
    )

    detail = build_clan_detail_text(
        container,
        snapshot=snapshot,
        fold_level=FoldLevel.COLLAPSED,
    ).plain

    for heading in ("REPLIES", "SASE CONTEXT", "SLOW TOOL CALLS", "PROMPTS"):
        assert heading not in detail
    assert "⋯ scanning member data…" not in detail


def test_loaded_non_empty_disk_section_appears_while_others_scan() -> None:
    container, snapshot = rich_clan_snapshot()
    assert snapshot.disk is not None
    disk = snapshot.disk
    partial = ClanSectionSnapshot(
        in_memory=snapshot.in_memory,
        disk=ClanDiskSnapshot(
            loaded_sections=frozenset({"replies"}),
            members=disk.members,
            replies=disk.replies,
            prompts=(),
            context_lanes=(),
            slow_tool_calls=(),
        ),
    )

    detail = build_clan_detail_text(
        container,
        snapshot=partial,
        fold_level=FoldLevel.COLLAPSED,
    ).plain

    assert "▸ REPLIES · 1\n" in detail
    assert "PROMPTS" not in detail
    assert detail.count("⋯ scanning member data…") == 1


def test_clan_sections_honor_all_three_fold_contracts() -> None:
    container, snapshot = rich_clan_snapshot()

    collapsed = build_clan_detail_text(
        container,
        snapshot=snapshot,
        fold_level=FoldLevel.COLLAPSED,
    ).plain
    expanded = build_clan_detail_text(
        container,
        snapshot=snapshot,
        fold_level=FoldLevel.EXPANDED,
    ).plain
    full = build_clan_detail_text(
        container,
        snapshot=snapshot,
        fold_level=FoldLevel.FULLY_EXPANDED,
    ).plain

    assert "Fold: 1/3\n" in collapsed
    for heading in (
        "▸ ❖ CLAN MEMBERS · 1",
        "▸ ERRORS · 1",
        "▸ OUTPUT VARIABLES · 1",
        "▸ WORKFLOW VARIABLES · 1",
        "▸ REPLIES · 1",
        "▸ SASE CONTEXT · 2",
        "▸ SLOW TOOL CALLS · 1",
        "▸ PROMPTS · 1",
    ):
        assert heading in collapsed
    assert ".one · agent · ✗ FAILED" in collapsed
    assert "Build failed" not in collapsed
    assert "Reply summary" not in collapsed

    assert "Fold: 2/3\n" in expanded
    assert "▾ ❖ CLAN MEMBERS · 1" in expanded
    assert "reviewing patch" in expanded
    assert "wait for research.peer" in expanded
    assert "• .one · Build failed" in expanded
    assert "• .one.report = summary line" in expanded
    assert "• .one · AGENT REPLY · Reply summary" in expanded
    assert "BEAD · sase-demo · render clan summary" in expanded
    assert "• .one · Bash · 2m 5s · just check" in expanded
    assert ".one [XPROMPT] · AGENT XPROMPT · #review segment" in expanded
    assert "Second error detail" not in expanded
    assert "Reply full detail" not in expanded

    assert "Fold: 3/3\n" in full
    assert "▼ ❖ CLAN MEMBERS · 1" in full
    assert "start 2026-07-17 12:00:00" in full
    assert "0 attempts" in full
    assert "Second error detail" in full
    assert "ValueError: broken" in full
    assert "full report detail" in full
    assert "release detail" in full
    assert "Reply full detail" in full
    assert "Prompt full detail" in full


def test_exhaustive_shared_level_clamps_to_fully_expanded_clan() -> None:
    container, snapshot = rich_clan_snapshot()

    full = build_clan_detail_text(
        container,
        snapshot=snapshot,
        fold_level=FoldLevel.FULLY_EXPANDED,
    )
    exhaustive = build_clan_detail_text(
        container,
        snapshot=snapshot,
        fold_level=FoldLevel.EXHAUSTIVE,
    )

    assert exhaustive == full
    assert "Fold: 3/3\n" in exhaustive.plain


def test_clan_section_override_and_scanning_tail() -> None:
    container, snapshot = rich_clan_snapshot()
    overrides = {
        "errors": FoldLevel.FULLY_EXPANDED,
        "replies": FoldLevel.EXPANDED,
    }

    detail = build_clan_detail_text(
        container,
        snapshot=snapshot,
        fold_level=FoldLevel.COLLAPSED,
        section_fold_overrides=overrides,
    ).plain

    assert "Fold: 1/3\n" in detail
    assert "▸ ❖ CLAN MEMBERS · 1" in detail
    assert "▼ ERRORS · 1" in detail
    assert "Second error detail" in detail
    assert "▾ REPLIES · 1" in detail
    assert (
        clan_disk_sections_for_fold_state(
            FoldLevel.COLLAPSED,
            overrides,
        )
        == CLAN_DISK_SECTIONS
    )

    loading_snapshot = ClanSectionSnapshot(in_memory=snapshot.in_memory)
    loading = build_clan_detail_text(
        container,
        snapshot=loading_snapshot,
        fold_level=FoldLevel.EXPANDED,
    ).plain

    assert "REPLIES" not in loading
    assert "▾ SASE CONTEXT\n" in loading
    assert "SLOW TOOL CALLS" not in loading
    assert "PROMPTS" not in loading
    assert "loading…" not in loading
    assert loading.count("⋯ scanning member data…") == 1

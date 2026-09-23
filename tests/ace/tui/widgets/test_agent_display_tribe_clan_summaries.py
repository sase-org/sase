"""Renderer, fold, and enrichment tests for tribe CLAN SUMMARIES."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from typing import Any

from rich.text import Text

from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_tribe_summary import build_agent_tribe_summary_snapshot
from sase.ace.tui.models.fold_state import FoldLevel
from sase.ace.tui.widgets.prompt_panel._agent_display_tribe import (
    build_tribe_detail_text,
)
from sase.ace.tui.widgets.prompt_panel._agent_display_tribe_clan_summaries import (
    CLAN_SUMMARY_ENTRY_ANCHOR_PREFIX,
    append_clan_summaries,
)
from sase.ace.tui.widgets.prompt_panel._agent_tribe_aggregation import (
    TribeSectionSnapshot,
    TribeUnitSource,
    _TribeDiskSnapshot,
    build_tribe_enrichment,
    cache_tribe_enrichment,
    get_cached_tribe_sources,
    prepare_tribe_section_snapshot,
    tribe_sections_to_refresh,
)
from sase.ace.tui.widgets.prompt_panel._agent_tribe_clan_summaries import (
    TribeClanSummariesSnapshot,
    build_tribe_clan_summaries,
    empty_tribe_clan_summaries_snapshot,
)
from sase.ace.tui.widgets.prompt_panel._agent_tribe_prompts import (
    PromptDigest,
    TribePromptGroup,
    TribePromptMember,
    TribePromptsSnapshot,
)
from sase.ace.tui.widgets.prompt_panel._section_navigation import (
    SECTION_FOLD_ONLY_META_KEY,
    SECTION_MARKER_META_KEY,
)

_NOW = datetime(2026, 7, 18, 16, 0, 0)

_EPIC_SUMMARY = """◆ EPIC demo-clan
Title: Rebuild the thing
Goal: first goal line
Counts: 1/2
"""


def _clan_root(name: str, summary: str | None) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name=name,
        project_file="/tmp/demo.sase",
        status="RUNNING",
        start_time=_NOW,
        run_start_time=_NOW,
        raw_suffix=f"root-{name}",
        agent_name=name,
        is_clan_container=True,
        agent_clan=name,
        agent_clan_generation="gen-1",
        clan_summary=summary,
        tribe="epic",
    )


def _source(root: Agent, label: str) -> TribeUnitSource:
    return TribeUnitSource(
        root=root,
        unit_identity=root.identity,
        unit_label=label,
        rows=(root,),
        labels={root.identity: label},
    )


def _loaded_snapshot(
    roots: tuple[Agent, ...],
    summaries: TribeClanSummariesSnapshot,
) -> tuple[Any, TribeSectionSnapshot]:
    tribe = build_agent_tribe_summary_snapshot(
        "epic", list(roots), panel_collapsed=True, now=_NOW
    )
    sections = TribeSectionSnapshot(
        panel_identity=tribe.container_identity,
        source_signature=(),
        disk=_TribeDiskSnapshot(
            loaded_sections=frozenset({"prompts", "replies", "slow-tool-calls"}),
            replies=(),
            slow_tool_calls=(),
        ),
        runtime_statistics_loaded=True,
        clan_summaries=summaries,
    )
    return tribe, sections


def _render(
    roots: tuple[Agent, ...],
    summaries: TribeClanSummariesSnapshot,
    *,
    level: FoldLevel = FoldLevel.COLLAPSED,
    overrides: dict[str, FoldLevel] | None = None,
) -> Text:
    tribe, sections = _loaded_snapshot(roots, summaries)
    detail = build_tribe_detail_text(
        tribe,
        section_snapshot=sections,
        fold_level=level,
        section_fold_overrides=overrides or {},
    )
    assert isinstance(detail, Text)
    return detail


def _summaries_for(roots: tuple[Agent, ...]) -> TribeClanSummariesSnapshot:
    return build_tribe_clan_summaries(
        tuple(_source(root, root.agent_clan or "?") for root in roots)
    )


def test_section_sits_after_members_and_before_prompts() -> None:
    roots = (_clan_root("demo-clan", _EPIC_SUMMARY),)
    summaries = _summaries_for(roots)
    tribe = build_agent_tribe_summary_snapshot(
        "epic", list(roots), panel_collapsed=True, now=_NOW
    )
    prompt_snapshot = TribePromptsSnapshot(
        groups=(
            TribePromptGroup(
                digest=PromptDigest(
                    group_key="key1",
                    headline="Prompt headline.",
                    headline_spans=(),
                    body="Prompt headline.",
                    body_spans=(),
                    body_line_count=1,
                    launch="",
                    launch_spans=(),
                    xprompts=(),
                    project=None,
                ),
                members=(
                    TribePromptMember(
                        unit_identity=roots[0].identity,
                        unit_label="demo-clan",
                        member_identity=roots[0].identity,
                        member_label="demo-clan",
                    ),
                ),
            ),
        ),
        agent_count=1,
        multi_project=False,
    )
    sections = TribeSectionSnapshot(
        panel_identity=tribe.container_identity,
        source_signature=(),
        disk=_TribeDiskSnapshot(
            loaded_sections=frozenset({"prompts", "replies", "slow-tool-calls"}),
            replies=(),
            slow_tool_calls=(),
            prompts=prompt_snapshot,
        ),
        runtime_statistics_loaded=True,
        clan_summaries=summaries,
    )
    detail = build_tribe_detail_text(
        tribe, section_snapshot=sections, fold_level=FoldLevel.COLLAPSED
    )
    assert isinstance(detail, Text)
    rendered = detail.plain

    assert rendered.index("TRIBE MEMBERS") < rendered.index("CLAN SUMMARIES")
    assert rendered.index("CLAN SUMMARIES") < rendered.index("PROMPTS")


def test_section_absent_without_summaries_and_for_stale_units() -> None:
    nosummary = (_clan_root("demo-clan", None),)
    assert (
        "CLAN SUMMARIES"
        not in _render(nosummary, empty_tribe_clan_summaries_snapshot()).plain
    )

    roots = (_clan_root("demo-clan", _EPIC_SUMMARY),)
    summaries = _summaries_for(roots)
    _tribe, sections = _loaded_snapshot(roots, summaries)
    text = Text()
    append_clan_summaries(
        text,
        sections,
        level=FoldLevel.COLLAPSED,
        overrides={},
        unit_numbers={},
        present_units=set(),
    )
    assert "CLAN SUMMARIES" not in text.plain


def test_glance_entry_line_has_chip_kicker_headline_and_size() -> None:
    roots = (_clan_root("demo-clan", _EPIC_SUMMARY),)
    rendered = _render(roots, _summaries_for(roots)).plain

    assert "▸ CLAN SUMMARIES · 1" in rendered
    assert " 0  demo-clan  EPIC  Rebuild the thing · 3 lines" in rendered


def test_single_line_literal_has_no_kicker_or_size_tag() -> None:
    roots = (_clan_root("beta", "Audit authentication and authorization"),)
    rendered = _render(roots, _summaries_for(roots)).plain

    assert " 0  beta  Audit authentication and authorization" in rendered
    assert "lines" not in rendered.split("CLAN SUMMARIES")[1].split("PROMPTS")[0]


def test_glance_caps_at_eight_entries_with_more_tail() -> None:
    roots = tuple(
        _clan_root(f"clan-{index:02d}", f"Summary {index}.") for index in range(9)
    )
    rendered = _render(roots, _summaries_for(roots)).plain

    assert "▸ CLAN SUMMARIES · 9" in rendered
    assert "Summary 7." in rendered
    assert "Summary 8." not in rendered
    assert "  +1 more" in rendered


def test_triage_shows_lede_behind_the_clan_gutter() -> None:
    roots = (_clan_root("demo-clan", _EPIC_SUMMARY),)
    rendered = _render(roots, _summaries_for(roots), level=FoldLevel.EXPANDED).plain

    assert "▾ CLAN SUMMARIES · 1" in rendered
    assert "  ▎ Goal: first goal line" in rendered
    assert "  ▎ Counts: 1/2" in rendered
    assert "  ▎ Title:" not in rendered


def test_inspect_truncates_at_16_lines_with_tail_and_blank_gap() -> None:
    body = "\n".join(f"Body line {index}." for index in range(20))
    first = _clan_root("demo-clan", f"Headline here.\n{body}")
    second = _clan_root("beta", "Other summary.")
    roots = (first, second)
    rendered = _render(
        roots, _summaries_for(roots), level=FoldLevel.FULLY_EXPANDED
    ).plain

    assert "  ▎ Body line 14." in rendered
    assert "  ▎ Body line 15." not in rendered
    assert "  ▎ … +5 more lines" in rendered
    assert "\n\n 1  beta  Other summary." in rendered


def test_forensics_applies_500_line_cap_with_clan_panel_tail() -> None:
    body = "\n".join(f"Body line {index}." for index in range(505))
    roots = (_clan_root("demo-clan", f"Headline here.\n{body}"),)
    rendered = _render(roots, _summaries_for(roots), level=FoldLevel.EXHAUSTIVE).plain

    assert "  ▎ Body line 498." in rendered
    assert "  ▎ Body line 499." not in rendered
    assert "  ▎ … +6 more lines" in rendered
    assert "press 0 to open the clan panel for the rest" in rendered


def test_missing_number_renders_dim_bullet() -> None:
    roots = (_clan_root("demo-clan", _EPIC_SUMMARY),)
    summaries = _summaries_for(roots)
    text = Text()
    append_clan_summaries(
        text,
        TribeSectionSnapshot(
            panel_identity=("panel", "epic"),
            source_signature=(),
            clan_summaries=summaries,
        ),
        level=FoldLevel.COLLAPSED,
        overrides={},
        unit_numbers={},
        present_units={roots[0].identity},
    )

    assert "• demo-clan  EPIC  Rebuild the thing" in text.plain


def test_entry_anchors_are_fold_only_while_heading_is_a_stop() -> None:
    roots = (_clan_root("demo-clan", _EPIC_SUMMARY),)
    rendered = _render(roots, _summaries_for(roots))
    entry_key = _summaries_for(roots).entries[0].entry_key

    markers = [
        span.style.meta[SECTION_MARKER_META_KEY]
        for span in rendered.spans
        if getattr(span.style, "meta", None)
        and SECTION_MARKER_META_KEY in span.style.meta
    ]
    assert "tribe:clan-summaries" in markers
    assert f"{CLAN_SUMMARY_ENTRY_ANCHOR_PREFIX}{entry_key}" in markers
    fold_only = [
        span.style.meta[SECTION_MARKER_META_KEY]
        for span in rendered.spans
        if getattr(span.style, "meta", None)
        and span.style.meta.get(SECTION_FOLD_ONLY_META_KEY)
    ]
    assert f"{CLAN_SUMMARY_ENTRY_ANCHOR_PREFIX}{entry_key}" in fold_only
    assert "tribe:clan-summaries" not in fold_only


def test_per_entry_override_expands_only_that_entry() -> None:
    first = _clan_root("demo-clan", _EPIC_SUMMARY)
    second = _clan_root("beta", "Audit authentication and authorization")
    roots = (first, second)
    summaries = _summaries_for(roots)
    anchor = f"{CLAN_SUMMARY_ENTRY_ANCHOR_PREFIX}{summaries.entries[0].entry_key}"
    rendered = _render(
        roots, summaries, overrides={anchor: FoldLevel.FULLY_EXPANDED}
    ).plain

    assert "  ▎ Goal: first goal line" in rendered
    assert "  ▎ Audit authentication" not in rendered


def test_render_never_parses_markup(monkeypatch: Any) -> None:
    roots = (_clan_root("demo-clan", _EPIC_SUMMARY),)
    summaries = _summaries_for(roots)

    def forbidden(_text: str, **_kwargs: object) -> Text:
        raise AssertionError("render paths must replay spans, never parse")

    monkeypatch.setattr("rich.text.Text.from_markup", forbidden)
    for level in FoldLevel:
        rendered = _render(roots, summaries, level=level)
        assert "CLAN SUMMARIES" in rendered.plain


def test_empty_signature_needs_no_clan_worker() -> None:
    widget = SimpleNamespace()
    tribe = build_agent_tribe_summary_snapshot(
        "epic", [], panel_collapsed=True, now=_NOW
    )
    prepare_tribe_section_snapshot(widget, tribe, [])

    refresh = tribe_sections_to_refresh(
        widget, tribe.container_identity, {"clan-summaries"}
    )

    assert refresh == frozenset()


def test_signature_change_refreshes_and_churn_keeps_entries() -> None:
    first = _clan_root("demo-clan", _EPIC_SUMMARY)
    widget = SimpleNamespace()
    tribe = build_agent_tribe_summary_snapshot(
        "epic", [first], panel_collapsed=True, now=_NOW
    )
    prepare_tribe_section_snapshot(widget, tribe, [first])
    assert "clan-summaries" in tribe_sections_to_refresh(
        widget, tribe.container_identity, {"clan-summaries"}
    )

    sources = get_cached_tribe_sources(widget, tribe.container_identity)
    merged = cache_tribe_enrichment(
        widget,
        build_tribe_enrichment(
            widget,
            tribe.container_identity,
            sources=sources,
            sections={"clan-summaries"},
        ),
    )
    assert merged is not None
    assert len(merged.clan_summaries.entries) == 1
    assert not tribe_sections_to_refresh(
        widget, tribe.container_identity, {"clan-summaries"}
    )

    # Membership churn keeps the cached entries instead of blanking.
    extra = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="extra",
        project_file="/tmp/demo.sase",
        status="RUNNING",
        start_time=_NOW,
        run_start_time=_NOW,
        raw_suffix="extra-1",
        agent_name="extra",
        tribe="epic",
    )
    churned = build_agent_tribe_summary_snapshot(
        "epic", [first, extra], panel_collapsed=True, now=_NOW
    )
    kept = prepare_tribe_section_snapshot(widget, churned, [first, extra])
    assert kept.clan_summaries is not None
    assert len(kept.clan_summaries.entries) == 1

    # Changed summary text requests a refresh and publishes new entries.
    first.clan_summary = "Audit authentication and authorization"
    changed = build_agent_tribe_summary_snapshot(
        "epic", [first], panel_collapsed=True, now=_NOW
    )
    prepare_tribe_section_snapshot(widget, changed, [first])
    assert "clan-summaries" in tribe_sections_to_refresh(
        widget, changed.container_identity, {"clan-summaries"}
    )
    sources = get_cached_tribe_sources(widget, changed.container_identity)
    merged = cache_tribe_enrichment(
        widget,
        build_tribe_enrichment(
            widget,
            changed.container_identity,
            sources=sources,
            sections={"clan-summaries"},
        ),
    )
    assert merged is not None
    assert merged.clan_summaries.entries[0].digest.headline == (
        "Audit authentication and authorization"
    )


def test_worker_builds_clan_summaries_without_disk_sections() -> None:
    widget = SimpleNamespace()
    roots = (_clan_root("demo-clan", _EPIC_SUMMARY),)
    tribe = build_agent_tribe_summary_snapshot(
        "epic", list(roots), panel_collapsed=True, now=_NOW
    )
    prepare_tribe_section_snapshot(widget, tribe, list(roots))
    sources = get_cached_tribe_sources(widget, tribe.container_identity)

    result = build_tribe_enrichment(
        widget, tribe.container_identity, sources=sources, sections={"clan-summaries"}
    )

    assert result.disk is None
    assert result.clan_summaries is not None
    assert [entry.unit_label for entry in result.clan_summaries.entries] == [
        "demo-clan"
    ]

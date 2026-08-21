"""Completeness guards for contextual Statistics help."""

from __future__ import annotations

from sase.ace.tui.keymaps import StatisticsPaneKeymaps
from sase.ace.tui.keymaps.types import _STATISTICS_BINDING_META
from sase.ace.tui.modals.statistics_help_modal import StatisticsHelpModal
from sase.ace.tui.modals.statistics_pane_data import (
    STATISTICS_VIEW_SPECS,
    StatisticsView,
    VIEW_DESCRIPTIONS,
    VIEW_LABELS,
    VIEW_ORDER,
)
from sase.ace.tui.modals.statistics_pane_legends import VIEW_LEGENDS
from sase.stats.ranges import StatsRange


def _modal(current_view: StatisticsView = "overview") -> StatisticsHelpModal:
    return StatisticsHelpModal(
        current_view=current_view,
        selected_range=StatsRange(100, 200, "exact range", "Last 7 days"),
        projects_group_by="project",
        xprompts_group_by="usage",
        project_label="All projects",
        generated_at=150.0,
        keymaps=StatisticsPaneKeymaps(),
    )


def test_help_documents_every_statistics_view_and_legend() -> None:
    modal = _modal()
    views = modal._views_text().plain
    glossary = modal._glossary_text().plain

    for number, view in enumerate(VIEW_ORDER, start=1):
        assert f"{number:02d} {VIEW_LABELS[view]}" in views
        assert VIEW_LABELS[view] in views
        assert VIEW_DESCRIPTIONS[view] in views
        assert VIEW_LABELS[view] in glossary
        for legend in VIEW_LEGENDS[view]:
            assert legend.term in glossary
            assert legend.meaning in glossary


def test_help_lists_canonical_full_descriptions_not_compact_variants() -> None:
    modal = _modal("perf")
    views = modal._views_text().plain
    for spec in STATISTICS_VIEW_SPECS:
        assert f" — {spec.description}" in views
        assert spec.description == VIEW_DESCRIPTIONS[spec.id]
        if spec.compact_description != spec.description:
            assert f" — {spec.compact_description}" not in views


def test_help_documents_every_statistics_binding_and_current_scope() -> None:
    modal = _modal()
    controls = modal._controls_text().plain

    for action, description in _STATISTICS_BINDING_META:
        if action in {"cycle_group", "focus_xprompt", "clear_xprompt_focus"}:
            assert description not in controls
        else:
            assert description in controls
    assert "Last 7 days · exact range" in controls
    assert "0  Select View by Number — press 0 then 1-8; default chords 01-08" in (
        controls
    )
    assert "next ranked project (seeded); current: All projects" in controls
    assert "previous ranked project (seeded); current: All projects" in controls


def test_help_group_control_is_visible_only_for_grouping_views() -> None:
    for view in VIEW_ORDER:
        controls = _modal(view)._controls_text().plain
        if view == "projects":
            assert "Group By — Projects · By Project" in controls
        elif view == "xprompts":
            assert "Group By — XPrompts · By Usage" in controls
        elif view == "perf":
            assert "Group By — Perf · By Subsystem" in controls
        else:
            assert "Group By" not in controls


def test_help_xprompt_controls_are_visible_only_on_xprompts() -> None:
    for view in VIEW_ORDER:
        controls = _modal(view)._controls_text().plain
        if view == "xprompts":
            assert "Focus XPrompt — choose from loaded xprompts" in controls
            assert "Clear XPrompt Focus — return to All xprompts" in controls
        else:
            assert "Focus XPrompt" not in controls
            assert "Clear XPrompt Focus" not in controls


def test_help_explains_runner_eligibility_windows_and_capacity_caveats() -> None:
    methodology = _modal()._runner_methodology_text().plain

    for phrase in (
        "a live parallel family member",
        "post-handoff follow-up",
        "Carry-in agents and live agents",
        "Question waits that release a runner slot",
        "plan-review waits remain occupied",
        "Zero occupancy",
        "time-weighted",
        "earliest valid recorded runner segment",
        "filter is applied before concurrency",
        "Malformed rows, invalid bounds",
        "lanes without trustworthy ends",
        "user-hidden rows",
        "today's effective global reference",
        "including a live temporary override",
        "not a historical limit or project-specific capacity",
    ):
        assert phrase in methodology


def test_help_explains_xprompt_counting_methodology() -> None:
    methodology = _modal()._xprompt_methodology_text().plain

    for phrase in (
        "launch-boundary xprompts.json",
        "before prompt expansion",
        "Workflow step-template references are excluded",
        "A run counts once per xprompt name",
        "Refs counts argument variants separately",
        "other xprompts referenced in the same run",
        "attributed to every agent the swarm launched",
        "attribution is forward-only",
        "project filter is applied before aggregation",
        "artifact index has been rebuilt at its current schema",
    ):
        assert phrase in methodology


def test_help_explains_perf_methodology() -> None:
    methodology = _modal()._perf_methodology_text().plain

    for phrase in (
        "Nearest-rank on the sorted sample",
        "round(q * (n - 1))",
        "JKPerfTimer.summary()",
        "linear interpolation between cumulative histogram bucket bounds",
        "not a nearest-rank sample",
        "telemetry.health_thresholds",
        "p95_latency_*",
        "error_rate_*",
        "sase telemetry health",
        "ok below 2s",
        "warn below 5s",
        "warn on any hitch",
        "critical on any stall",
        "not project-scoped",
        "never by project",
        "TUI perf logs carry no project",
        "not comparable with the run counts on Overview, Projects, or XPrompts",
        "rolls raw samples up after 48 hours",
        "byte-bounded",
        "All time means as far back as the retained data goes",
        "SASE_TUI_PERF",
        "SASE_TUI_TRACE",
        "does not parse the probe files",
        "Launch p95",
        "Startup and stall medians",
    ):
        assert phrase in methodology
    assert "Launch, and stall medians" not in methodology

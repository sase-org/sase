"""Completeness guards for contextual Statistics help."""

from __future__ import annotations

from sase.ace.tui.keymaps import StatisticsPaneKeymaps
from sase.ace.tui.keymaps.types import _STATISTICS_BINDING_META
from sase.ace.tui.modals.statistics_help_modal import StatisticsHelpModal
from sase.ace.tui.modals.statistics_pane_data import (
    VIEW_DESCRIPTIONS,
    VIEW_LABELS,
    VIEW_ORDER,
)
from sase.ace.tui.modals.statistics_pane_legends import VIEW_LEGENDS
from sase.stats.ranges import StatsRange


def _modal() -> StatisticsHelpModal:
    return StatisticsHelpModal(
        current_view="overview",
        selected_range=StatsRange(100, 200, "exact range", "Last 7 days"),
        runtime_group_by="tribe",
        projects_group_by="project",
        project_label="All projects",
        generated_at=150.0,
        keymaps=StatisticsPaneKeymaps(),
    )


def test_help_documents_every_statistics_view_and_legend() -> None:
    modal = _modal()
    views = modal._views_text().plain
    glossary = modal._glossary_text().plain

    for view in VIEW_ORDER:
        assert VIEW_LABELS[view] in views
        assert VIEW_DESCRIPTIONS[view] in views
        assert VIEW_LABELS[view] in glossary
        for legend in VIEW_LEGENDS[view]:
            assert legend.term in glossary
            assert legend.meaning in glossary


def test_help_documents_every_statistics_binding_and_current_scope() -> None:
    modal = _modal()
    controls = modal._controls_text().plain

    for _action, description in _STATISTICS_BINDING_META:
        assert description in controls
    assert "Last 7 days · exact range" in controls
    assert "available in Runtime and Projects" in controls
    assert "All projects" in controls

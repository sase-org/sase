"""Tests for the ACE help modal tab-scoped content."""

from __future__ import annotations

from sase.ace.tui.modals.help_modal import HelpModal


def test_help_modal_refresh_for_tab_rebuilds_sections() -> None:
    modal = HelpModal(current_tab="changespecs", active_query='"feature"')

    assert "Artifact Sub-tabs" in modal._build_left_column().plain
    assert "PR Actions" in modal._build_right_column().plain

    modal.refresh_for_tab("agents", active_query=None)

    assert modal._current_tab == "agents"
    assert modal._active_query is None
    assert "Agents Tab" in modal._build_title().plain
    assert "Agent Actions" in modal._build_left_column().plain

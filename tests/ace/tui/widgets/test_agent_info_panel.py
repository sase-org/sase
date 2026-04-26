"""Tests for the Agents-tab info panel rendering."""

from __future__ import annotations

from unittest.mock import patch

from sase.ace.tui.widgets.agent_info_panel import AgentInfoPanel


def _collect_text(panel: AgentInfoPanel) -> str:
    captured: list[str] = []
    with patch.object(panel, "update", lambda text: captured.append(text.plain)):
        panel._update_display()
    assert captured, "panel._update_display did not invoke self.update()"
    return captured[-1]


def test_grouping_badge_renders_default_when_unset() -> None:
    """The badge always renders, treating an empty label as ``default``."""
    panel = AgentInfoPanel()
    panel._position = 1
    panel._total = 1
    plain = _collect_text(panel)
    assert "[group: default (g)]" in plain


def test_grouping_badge_renders_label_after_update() -> None:
    panel = AgentInfoPanel()
    panel._position = 1
    panel._total = 1
    panel._grouping_mode = "by status"
    plain = _collect_text(panel)
    assert "[group: by status (g)]" in plain


def test_grouping_badge_renders_by_date_label() -> None:
    panel = AgentInfoPanel()
    panel._position = 1
    panel._total = 1
    panel._grouping_mode = "by date"
    plain = _collect_text(panel)
    assert "[group: by date (g)]" in plain


def test_grouping_badge_suppressed_while_loading() -> None:
    """Loading state short-circuits before the badge segment is emitted."""
    panel = AgentInfoPanel()
    panel._loading = True
    plain = _collect_text(panel)
    assert "group:" not in plain

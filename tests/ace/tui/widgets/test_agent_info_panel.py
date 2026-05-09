"""Tests for the Agents-tab info panel rendering."""

from __future__ import annotations

from unittest.mock import patch

from sase.ace.tui.keymaps import key_display_name, load_keymap_registry
from sase.ace.tui.widgets.agent_info_panel import AgentInfoPanel

_DEFAULT_GROUPING_KEY = key_display_name(
    load_keymap_registry({}).app.cycle_grouping_mode
)


def _collect_text(panel: AgentInfoPanel) -> str:
    captured: list[str] = []
    with patch.object(panel, "update", lambda text: captured.append(text.plain)):
        panel._update_display()
    assert captured, "panel._update_display did not invoke self.update()"
    return captured[-1]


def test_grouping_badge_renders_by_project_when_unset() -> None:
    """The badge always renders, treating an empty label as ``by project``."""
    panel = AgentInfoPanel()
    plain = _collect_text(panel)
    assert f"[group: by project ({_DEFAULT_GROUPING_KEY})]" in plain


def test_agent_count_strip_renders_after_agents_label() -> None:
    panel = AgentInfoPanel()
    panel._position = 2
    panel._total = 12
    panel._unread_count = 3
    panel._running_count = 5
    panel._visible_agent_count = 12

    plain = _collect_text(panel)

    assert plain.startswith("Agents: 3 unread · 5 running · 12 total")
    assert "Agents: 2/12" not in plain


def test_update_agent_counts_uses_plain_metric_text() -> None:
    panel = AgentInfoPanel()

    captured: list[str] = []
    with patch.object(panel, "update", lambda text: captured.append(text.plain)):
        panel.update_agent_counts(1, 2, 4)
    assert captured, "panel.update_agent_counts did not refresh the display"
    plain = captured[-1]

    assert "1 unread · 2 running · 4 total" in plain
    assert "[" not in plain.split("1 unread", 1)[0]
    assert "#FFAF5F" not in plain


def test_grouping_badge_renders_label_after_update() -> None:
    panel = AgentInfoPanel()
    panel._grouping_mode = "by status"
    plain = _collect_text(panel)
    assert f"[group: by status ({_DEFAULT_GROUPING_KEY})]" in plain


def test_grouping_badge_renders_by_date_label() -> None:
    panel = AgentInfoPanel()
    panel._grouping_mode = "by date"
    plain = _collect_text(panel)
    assert f"[group: by date ({_DEFAULT_GROUPING_KEY})]" in plain


def test_grouping_badge_suppressed_while_loading() -> None:
    """Loading state short-circuits before the badge segment is emitted."""
    panel = AgentInfoPanel()
    panel._loading = True
    plain = _collect_text(panel)
    assert "group:" not in plain


def test_count_strip_suppressed_while_loading() -> None:
    panel = AgentInfoPanel()
    panel._loading = True
    panel._unread_count = 3
    panel._running_count = 5
    panel._visible_agent_count = 12

    plain = _collect_text(panel)

    assert plain == "Agents: …"
    assert "unread" not in plain

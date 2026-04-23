"""Tests for startup loading indicators on Agents and Axe surfaces."""

from __future__ import annotations

from unittest.mock import patch

from sase.ace.tui.widgets.agent_info_panel import AgentInfoPanel
from sase.ace.tui.widgets.axe_info_panel import AxeInfoPanel
from sase.ace.tui.widgets.tab_bar import TabBar


def test_tab_bar_agents_loading_renders_ellipsis() -> None:
    """Agents tab label shows a dim ellipsis while loading."""
    tab_bar = TabBar()
    tab_bar.update_agents_count(0, 0, show_hidden=False, loading=True)
    plain = tab_bar._build_content().plain
    assert "…" in plain
    # Loading suffix should not render the count-parentheses form.
    assert "Agents (" not in plain


def test_tab_bar_agents_loaded_renders_counts() -> None:
    """Once loading flips to False, Agents tab shows the count suffix."""
    tab_bar = TabBar()
    tab_bar.update_agents_count(3, 0, show_hidden=False, loading=False)
    plain = tab_bar._build_content().plain
    # The "Agents" segment sits between the two separators.
    agents_segment = plain.split("│")[1]
    assert "…" not in agents_segment
    assert "3" in agents_segment


def _collect_text(panel: AgentInfoPanel | AxeInfoPanel) -> str:
    """Call the panel's internal render method with .update() stubbed out.

    Returning the plain text of whatever would have been displayed lets us
    assert against rendering logic without needing a full Textual App
    context.
    """
    captured: list[str] = []
    with patch.object(panel, "update", lambda text: captured.append(text.plain)):
        panel._update_display()
    assert captured, "panel._update_display did not invoke self.update()"
    return captured[-1]


def test_agent_info_panel_loading_renders_ellipsis() -> None:
    """AgentInfoPanel shows 'Agents: …' while loading."""
    panel = AgentInfoPanel()
    panel._position = 0
    panel._total = 0
    panel._loading = True
    plain = _collect_text(panel)
    assert "Agents: " in plain
    assert "…" in plain
    assert "0/0" not in plain


def test_agent_info_panel_loading_clears() -> None:
    """Clearing loading restores the position/total display."""
    panel = AgentInfoPanel()
    panel._position = 2
    panel._total = 5
    panel._loading = False
    plain = _collect_text(panel)
    assert "2/5" in plain
    assert "…" not in plain


def test_axe_info_panel_loading_renders_ellipsis() -> None:
    """AxeInfoPanel shows 'AXE …' while loading."""
    panel = AxeInfoPanel()
    panel._loading = True
    plain = _collect_text(panel)
    assert "AXE" in plain
    assert "…" in plain


def test_axe_info_panel_loading_clears() -> None:
    """Clearing loading removes the ellipsis."""
    panel = AxeInfoPanel()
    panel._loading = False
    panel._countdown = 5
    panel._interval = 10
    plain = _collect_text(panel)
    assert "…" not in plain


def test_set_loading_short_circuits_when_unchanged() -> None:
    """set_loading is a no-op when the flag value has not changed."""
    panel = AgentInfoPanel()
    with patch.object(panel, "_update_display") as update:
        panel.set_loading(False)  # already False
    assert update.call_count == 0

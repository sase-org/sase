"""Tests for startup loading indicators on Agents and Axe surfaces."""

from __future__ import annotations

from unittest.mock import patch

from sase.ace.tui.bgcmd import BackgroundCommandInfo
from sase.ace.tui.widgets.agent_info_panel import AgentInfoPanel
from sase.ace.tui.widgets.axe_info_panel import AxeInfoPanel


def _collect_text(panel: AgentInfoPanel | AxeInfoPanel) -> str:
    """Call the panel's internal render method with .update() stubbed out.

    Returning the plain text of whatever would have been displayed lets us
    assert against rendering logic without needing a full Textual App
    context.
    """
    captured: list[str] = []
    with patch.object(
        panel,
        "update",
        lambda text, **_kwargs: captured.append(text.plain),
    ):
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
    """Clearing loading restores the count line without a position fraction."""
    panel = AgentInfoPanel()
    panel._position = 2
    panel._total = 5
    panel._agent_lane_count = 5
    panel._loading = False
    plain = _collect_text(panel)
    assert plain.startswith("5")
    assert "0 stopped" not in plain
    assert "2/5" not in plain
    assert "…" not in plain


def test_axe_info_panel_loading_renders_ellipsis() -> None:
    """AxeInfoPanel shows 'AXE …' while loading."""
    panel = AxeInfoPanel()
    panel._loading = True
    plain = _collect_text(panel)
    assert plain == "AXE …"
    assert "tab guide" not in plain


def test_axe_info_panel_loading_clears() -> None:
    """Clearing loading restores the countdown without the Guide hint."""
    panel = AxeInfoPanel()
    panel._loading = False
    panel._countdown = 5
    panel._interval = 10
    plain = _collect_text(panel)
    assert plain == "(auto-refresh in 5s)"
    assert "…" not in plain
    assert "tab guide" not in plain


def test_axe_info_panel_uses_bgcmd_display_project() -> None:
    """AxeInfoPanel shows PROJECT_NAME for background commands."""
    panel = AxeInfoPanel()
    panel._bgcmd_mode = True
    panel._bgcmd_info = BackgroundCommandInfo(
        command="make test",
        project="gh_acme__widgets",
        workspace_num=1,
        workspace_dir="/path",
        started_at="2025-01-01T12:00:00",
        project_display_name="widgets",
    )

    plain = _collect_text(panel)

    assert "widgets" in plain
    assert "gh_acme__widgets" not in plain


def test_set_loading_short_circuits_when_unchanged() -> None:
    """set_loading is a no-op when the flag value has not changed."""
    panel = AgentInfoPanel()
    with patch.object(panel, "_update_display") as update:
        panel.set_loading(False)  # already False
    assert update.call_count == 0

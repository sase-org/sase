"""Tests for Agents-tab mode affordances (mode-affordances phase).

Covers the HIDDEN/RAIL info-row chips and their click spans, the
zoom/rail footer entries, the help-modal Node Rail legend, and the
renamed palette entries.
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch

from rich.text import Text

from sase.ace.testing import AcePage
from sase.ace.tui.commands import iter_app_commands
from sase.ace.tui.keymaps import load_keymap_registry
from sase.ace.tui.modals.help_modal.bindings import agents_bindings
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.widgets import AgentDetail, AgentInfoPanel, KeybindingFooter
from sase.ace.tui.widgets._agent_list_render_rail import RAIL_LEGEND
from sase.ace.tui.widgets.decks.layout import SidebarMode
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_visual_idle,
)
from tests.ace.tui.widgets._agent_info_panel_helpers import (
    collect_rich_text,
    collect_text,
    stable_state_kwargs,
    style_for_plain_segment,
)


def _agent(
    name: str,
    status: str,
    minute: int,
) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name=f"rail-{name}",
        project_file="/workspace/sase/rail.sase",
        status=status,
        start_time=datetime(2026, 9, 27, 10, minute, 0),
        run_start_time=datetime(2026, 9, 27, 10, minute, 0),
        raw_suffix=f"2026092710{minute:02d}00-rail-{name}",
        agent_name=f"rail.{name}",
        tribe="sase",
        llm_provider="codex",
        model="gpt-5",
    )


def _agents() -> list[Agent]:
    return [
        _agent("asking", "QUESTION", 0),
        _agent("failed", "FAILED", 1),
        _agent("running", "RUNNING", 2),
        _agent("done", "DONE", 3),
    ]


def _render_hidden() -> tuple[AgentInfoPanel, Text]:
    panel = AgentInfoPanel()
    with patch.object(panel, "update"):
        panel.update_state(
            **stable_state_kwargs(position=3, total=7, sidebar_mode=SidebarMode.HIDDEN)
        )  # type: ignore[arg-type]
    return panel, collect_rich_text(panel)


def test_hidden_info_row_shows_reverse_zoom_restore_chip() -> None:
    """HIDDEN renders a reverse ZOOM chip, the zoom key, and node i/N."""
    panel, text = _render_hidden()
    plain = text.plain
    assert "ZOOM" in plain
    assert "Z restore" in plain
    assert "node 3/7" in plain
    assert "nodes 3/7" not in plain
    assert style_for_plain_segment(text, "ZOOM") == "bold #1a1a1a on #FFD700"
    assert panel._sidebar_chip_click_span is not None


def test_expanded_info_row_has_no_sidebar_chip() -> None:
    """EXPANDED renders neither chip and arms no click span."""
    panel = AgentInfoPanel()
    with patch.object(panel, "update"):
        panel.update_state(**stable_state_kwargs(position=3, total=7))  # type: ignore[arg-type]
    assert "ZOOM" not in collect_text(panel)
    assert panel._sidebar_chip_click_span is None


def test_click_inside_zoom_chip_posts_sidebar_clicked() -> None:
    """Clicking the ZOOM chip posts SidebarChipClicked."""
    panel, _text = _render_hidden()
    assert panel._sidebar_chip_click_span is not None
    start, _end = panel._sidebar_chip_click_span

    posted: list[object] = []
    with patch.object(
        panel, "post_message", side_effect=lambda msg: posted.append(msg)
    ):
        panel.on_click(SimpleNamespace(x=start + 1, stop=lambda: None))  # type: ignore[arg-type]

    assert len(posted) == 1
    assert isinstance(posted[0], AgentInfoPanel.SidebarChipClicked)


def test_click_before_zoom_chip_does_not_post() -> None:
    """Clicks outside the chip span are ignored."""
    panel, _text = _render_hidden()
    with patch.object(panel, "post_message") as post_message:
        panel.on_click(SimpleNamespace(x=0, stop=lambda: None))  # type: ignore[arg-type]
    post_message.assert_not_called()


def test_footer_restore_entry_appears_only_while_zoomed() -> None:
    """The footer names Z restore iff the deck is zoomed."""
    footer = KeybindingFooter()
    assert (footer._kd("zoom_panel"), "restore") in footer._compute_agent_bindings(
        None, deck_zoomed=True
    )
    plain_bindings = footer._compute_agent_bindings(None)
    assert "restore" not in [label for _key, label in plain_bindings]
    assert "expand nodes" not in [label for _key, label in plain_bindings]


def test_footer_expand_entry_appears_only_in_rail() -> None:
    """The footer names Ctrl+S expand nodes iff the rail is on."""
    footer = KeybindingFooter()
    assert (
        footer._kd("toggle_node_panel"),
        "expand nodes",
    ) in footer._compute_agent_bindings(None, node_rail=True)
    assert "expand nodes" not in [
        label for _key, label in footer._compute_agent_bindings(None, deck_zoomed=True)
    ]


def test_help_node_rail_legend_matches_vocabulary_and_box_width() -> None:
    """The Node Rail help box is generated from RAIL_LEGEND within width."""
    sections = agents_bindings(load_keymap_registry({}))
    rows = next(rows for name, rows in sections if name == "Node Rail")
    assert rows == [(glyph.plain, meaning) for glyph, meaning in RAIL_LEGEND]
    for key, description in rows:
        assert Text(key).cell_len <= 16
        assert Text(description).cell_len <= 32


def test_palette_entries_use_node_rail_labels() -> None:
    """The palette renames both entries and indexes rail/sidebar aliases."""
    by_id = {c.id: c for c in iter_app_commands(load_keymap_registry({}))}
    rail = by_id["app.toggle_node_panel"]
    assert rail.label == "Toggle node rail"
    assert "rail" in rail.aliases
    assert "sidebar" in rail.aliases
    assert "rail" in by_id["app.zoom_panel"].label


async def test_zoom_chip_click_restores_zoom(monkeypatch) -> None:
    """Clicking the info-row ZOOM chip while zoomed restores the snapshot."""
    patch_startup_loaders(monkeypatch, agents=_agents())
    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 4)
        await wait_for_visual_idle(page)
        detail = page.app.query_one("#agent-detail-panel", AgentDetail)
        await page.press("Z")
        await wait_for_visual_idle(page)
        assert detail.sidebar_mode is SidebarMode.HIDDEN
        panel = page.app.query_one("#agent-info-panel", AgentInfoPanel)
        span = panel._sidebar_chip_click_span
        assert span is not None
        await page.click("#agent-info-panel", offset=(span[0] + 2, 0))
        await wait_for_visual_idle(page)
        assert detail.sidebar_mode is SidebarMode.EXPANDED

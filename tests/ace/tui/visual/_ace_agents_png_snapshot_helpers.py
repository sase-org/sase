"""Shared helpers for Agents-tab PNG visual snapshot tests."""

from __future__ import annotations

from datetime import datetime
from xml.etree import ElementTree

import pytest
from textual.containers import VerticalScroll

from sase.ace.testing import AcePage
from sase.ace.tui.widgets import AgentDetail
from sase.ace.tui.widgets.decks.model import DeckId
from sase.ace.tui.widgets.prompt_panel._section_navigation import (
    PromptPanelSectionAnchor,
    PromptPanelSectionRole,
)
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    wait_for_state,
    wait_for_visual_idle,
)


async def choose_agent_metadata_view(page: AcePage) -> None:
    """Show the Main deck, which replaces the legacy metadata-only view."""
    detail = page.app.query_one("#agent-detail-panel", AgentDetail)
    detail.show_deck(0, DeckId.MAIN)
    await wait_for_visual_idle(page)


async def reveal_agent_file_view(page: AcePage) -> None:
    """Wait for File content, then show it in the focused deck panel."""
    await reveal_agent_file_larger_layout(page)


async def reveal_agent_file_larger_layout(page: AcePage) -> None:
    """Wait for File content, then select the Files deck."""
    detail = page.app.query_one("#agent-detail-panel", AgentDetail)
    detail.show_deck(0, DeckId.FILES)
    await wait_for_state(page, detail.is_file_visible, description="Files deck visible")


def pin_decks_paged(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin every Main deck to paged rendering for a deterministic golden.

    A multi-card document near the ``spread_max_screens`` threshold can settle
    as spread or paged depending on layout timing, so snapshots of such
    documents pin the mode instead of leaving it to the threshold.
    """
    from sase.ace.tui import agent_decks_settings

    settings = agent_decks_settings.AgentDecksSettings(spread_max_screens=0)
    monkeypatch.setattr(
        agent_decks_settings, "parse_agent_decks_settings", lambda _cfg: settings
    )


def main_deck_scroll(page: AcePage, panel_index: int = 0) -> VerticalScroll:
    """Return the scroll container of the deck shown in ``panel_index``."""
    detail = page.app.query_one("#agent-detail-panel", AgentDetail)
    return detail.deck_area.panel(panel_index).active_scroll()


async def select_main_card(
    page: AcePage, card_id: str, panel_index: int = 0, *, max_presses: int = 8
) -> None:
    """Cycle the focused panel's Main cards with ``ctrl+j`` until ``card_id``."""
    detail = page.app.query_one("#agent-detail-panel", AgentDetail)
    panel = detail.deck_area.panel(panel_index)
    for _ in range(max_presses):
        if panel.active_main_card() == card_id:
            break
        await page.press("ctrl+j")
        await wait_for_visual_idle(page)
    assert panel.active_main_card() == card_id
    await wait_for_visual_idle(page)


async def scroll_main_section_to_top(
    page: AcePage, identity: str, panel_index: int = 0
) -> None:
    """Scroll a Main deck section title to the top row of its viewport.

    The deck replacement for the deleted metadata section-stop actions. Paged
    Main renders one card, so select that card first with ``ctrl+j``/``ctrl+k``;
    spread Main renders every card, so its sections are always reachable.
    """
    detail = page.app.query_one("#agent-detail-panel", AgentDetail)
    panel = detail.deck_area.panel(panel_index)
    view = panel.main_view
    scroll = panel.active_scroll()
    view.enable_section_layout_reserve()

    def _anchor() -> PromptPanelSectionAnchor | None:
        if (
            view._section_anchor_generation != view._section_generation
            or view._section_anchor_width != view.size.width
        ):
            return None
        for anchor in view._section_anchors:
            if anchor.role is not PromptPanelSectionRole.CARD and (
                anchor.identity == identity
            ):
                return anchor
        return None

    await wait_for_state(
        page,
        lambda: _anchor() is not None,
        description=f"Main section anchor {identity!r}",
    )
    anchor = _anchor()
    assert anchor is not None
    scroll.scroll_to(
        y=view.virtual_region.y + anchor.row,
        animate=False,
        immediate=True,
    )
    await wait_for_visual_idle(page)
    resolved = resolved_main_section(page, panel_index)
    assert resolved == identity, f"expected {identity!r} at top, got {resolved!r}"


def resolved_main_section(page: AcePage, panel_index: int = 0) -> str | None:
    """Return the Main section occupying the top row of the deck viewport."""
    detail = page.app.query_one("#agent-detail-panel", AgentDetail)
    panel = detail.deck_area.panel(panel_index)
    view = panel.main_view
    row = int(panel.active_scroll().scroll_y) - view.virtual_region.y
    return view.resolve_section_at_row(row, width=view.size.width)


def pin_agents_visual_now(monkeypatch: pytest.MonkeyPatch, now: datetime) -> None:
    """Pin Agents-tab runtime formatting for date-sensitive snapshots."""
    from sase.ace.tui.actions.agents import (
        _display_panel_patches,
        _loading_compute_finalize,
        _loading_finalize,
    )
    from sase.ace.tui.models import _agent_time_wait
    from sase.ace.tui.models import agent as agent_module
    from sase.ace.tui.models import agent_time
    from sase.ace.tui.widgets.prompt_panel import _agent_queue_section
    from sase.core import time as core_time

    for module in (
        core_time,
        agent_module,
        agent_time,
        _agent_time_wait,
        _agent_queue_section,
        _display_panel_patches,
        _loading_compute_finalize,
        _loading_finalize,
    ):
        monkeypatch.setattr(module, "local_now", lambda: now)


def assert_page_svg_contains(page: AcePage, text: str) -> None:
    svg = page.export_svg(title="ACE visual assertion")
    svg_plain = _page_svg_text(svg)
    assert text in svg_plain


def page_svg_text(page: AcePage, *, title: str = "ACE visual assertion") -> str:
    """Return decoded text content from a fresh SVG export."""
    return _page_svg_text(page.export_svg(title=title))


def prompt_header_and_body_text(prompt: object) -> str:
    """Join the sticky header panel and the scrolling body for assertions."""
    from sase.ace.tui.widgets.renderable_text import renderable_to_text

    inline = getattr(prompt, "inline_document_renderable", None)
    if callable(inline):
        return renderable_to_text(inline()) or ""
    return renderable_to_text(getattr(prompt, "content", None)) or ""


def _page_svg_text(svg: str) -> str:
    """Return decoded text content from the exported SVG."""
    root = ElementTree.fromstring(svg)
    text_nodes = (
        "".join(element.itertext())
        for element in root.iter()
        if element.tag.rsplit("}", 1)[-1] == "text"
    )
    return "\n".join(text_nodes).replace("\xa0", " ")


def _page_svg_compact_styled_text(page: AcePage) -> str:
    """Return the page's SVG text content with styling boundaries collapsed.

    Rich represents spaces between differently styled SVG runs as
    x-offsets, not text nodes, so the caller compares against a compacted
    token stream with all spaces removed.
    """
    svg = page.export_svg(title="ACE visual assertion")
    return _page_svg_text(svg).replace(" ", "").replace("\n", "")


def assert_page_svg_styled_text_contains(page: AcePage, text: str) -> None:
    """Assert text across adjacent SVG elements with different Rich styles."""
    compact_text = text.replace(" ", "")
    svg_plain = _page_svg_compact_styled_text(page)
    assert compact_text in svg_plain, f"styled SVG text did not contain {text!r}"


def assert_page_svg_styled_text_absent(page: AcePage, text: str) -> None:
    """Assert text is absent across adjacent SVG elements with different styles."""
    compact_text = text.replace(" ", "")
    svg_plain = _page_svg_compact_styled_text(page)
    assert compact_text not in svg_plain, (
        f"styled SVG text unexpectedly contained {text!r}"
    )

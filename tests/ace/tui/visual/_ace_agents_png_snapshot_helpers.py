"""Shared helpers for Agents-tab PNG visual snapshot tests."""

from __future__ import annotations

import asyncio
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


async def show_reply_card(page: AcePage, panel_index: int = 0) -> AgentDetail:
    """Switch the Main deck to Reply with one ctrl+j once cycling can land it.

    Readiness matches exactly what ``DeckPanel.cycle_card`` needs: the panel
    document holds Context and Reply, the view already shows that document,
    and no deferred Main body is still being built off the pump. Pressing
    earlier silently drops the keystroke under parallel load.
    """
    detail = page.app.query_one("#agent-detail-panel", AgentDetail)
    await wait_for_state(
        page,
        lambda: _selected_agent_matches_detail(page, detail),
        description="selected agent detail is current before switching Main cards",
    )
    await wait_for_state(
        page,
        lambda: set(detail._main_deck_document.card_ids) == {"context", "reply"},
        description="Main deck has Context and Reply cards",
    )
    await wait_for_state(
        page,
        lambda: _main_view_ready_to_cycle(detail, panel_index),
        description="Main deck view is ready to cycle to the Reply card",
    )
    # The deck can land on Reply by itself (spread sticky landing) while the
    # readiness wait runs. Pressing then would wrap back to Context, so only
    # press when the switch is still needed. This is one press, not a retry:
    # a dropped press still fails loudly on the wait below.
    already = False
    try:
        already = (
            detail.deck_area.panel(panel_index).main_view.active_card_id == "reply"
        )
    except Exception:
        already = False
    if not already:
        await page.press("ctrl+j")
    await wait_for_state(
        page,
        lambda: detail.deck_area.panel(panel_index).main_view.active_card_id == "reply",
        description="Main deck shows the Reply card",
    )
    await wait_for_visual_idle(page)
    await _wait_main_card_visibly_applied(
        page,
        detail,
        panel_index,
        "reply",
        description="visible Main header selects Reply",
    )
    return detail


def _main_view_ready_to_cycle(detail: AgentDetail, panel_index: int) -> bool:
    """Return whether the selected Main document is applied and can be cycled."""
    try:
        panel = detail.deck_area.panel(panel_index)
    except Exception:
        return False
    try:
        if panel.deck is not DeckId.MAIN:
            return False
    except Exception:
        return False
    try:
        document = detail._main_deck_document
        view_document = panel.main_view._document
        panel_document = panel._main_document
        view_ids = set(document.card_ids)
    except Exception:
        return False
    if (
        panel_document is not document
        or view_document is not document
        or view_ids != {"context", "reply"}
    ):
        return False
    try:
        applied = int(getattr(panel, "_main_view_applied_generation", 0))
        generation = int(getattr(panel, "_view_generation", 0))
    except Exception:
        return False
    try:
        active = panel.active_main_card()
    except Exception:
        return False
    return applied >= generation and active in view_ids


def _selected_agent_matches_detail(page: AcePage, detail: AgentDetail) -> bool:
    """Return whether the detail panel belongs to the selected row identity."""
    try:
        from sase.ace.tui.actions.agents._archive_view import (
            archive_detail_owns_panel,
        )

        if archive_detail_owns_panel(page.app):
            runtime = getattr(page.app, "_archive_reader_runtime", None)
            if runtime is None or runtime.loading:
                return False
            selected = runtime.hydrated_agent
        else:
            selected = page.app._get_selected_agent()
        current = detail._current_agent
        return (
            selected is not None
            and current is not None
            and selected.identity == current.identity
        )
    except Exception:
        return False


def _main_card_selection_state(
    detail: AgentDetail, panel_index: int
) -> tuple[bool, str | None, str | None, bool]:
    """Return cheap spread-selection facts without exporting a frame.

    Returns ``(ready_to_cycle, view_active, stored_active, scroll_in_flight)``.
    Exporting an SVG every poll starves the pump it is waiting on, so callers
    gate the painted-header proof on these facts first.
    """
    try:
        panel = detail.deck_area.panel(panel_index)
    except Exception:
        return False, None, None, True
    try:
        ready = bool(_main_view_ready_to_cycle(detail, panel_index))
    except Exception:
        ready = False
    try:
        view_active = panel.main_view.active_card_id
    except Exception:
        view_active = None
    try:
        stored_active = panel._main_active_card
    except Exception:
        stored_active = None
    try:
        in_flight = panel.main_view._spread_pending_card is not None
    except Exception:
        in_flight = True
    return ready, view_active, stored_active, in_flight


def _redrive_main_card_selection(
    detail: AgentDetail, panel_index: int, card_id: str
) -> bool:
    """Re-issue the spread scroll to ``card_id`` after a background steal.

    A same-subject Main re-delivery can clamp the scroll offset while no
    navigation is in flight; the scroll watcher then derives the top card and
    overwrites the stored selection even though the view still shows the
    selected card. Re-issuing the generation-guarded scroll restores the
    user's selection the way a repeated keypress would. Returns whether a
    scroll was (re-)scheduled.
    """
    try:
        panel = detail.deck_area.panel(panel_index)
    except Exception:
        return False
    try:
        return panel.main_view.scroll_to_card(card_id) is not None
    except Exception:
        return False


def _main_card_diagnostics(
    detail: AgentDetail, panel_index: int, *, redrives: int
) -> str:
    """Describe spread landing state for a failed Main-card readiness wait."""
    try:
        panel = detail.deck_area.panel(panel_index)
        view = panel.main_view
        scroll = view._scroll_container()
        width = view._spread_content_width()
        rows = view.card_anchor_rows(width=width) if width > 0 else None
        return (
            f"main_active={getattr(panel, '_main_active_card', None)!r}; "
            f"view_active={view.active_card_id!r}; "
            f"spread_active={view.spread_active_card()!r}; "
            f"pending={getattr(view, '_spread_pending_card', None)!r}; "
            f"scroll_y={getattr(scroll, 'scroll_y', None)!r}; "
            f"max_scroll_y={getattr(scroll, 'max_scroll_y', None)!r}; "
            f"anchor_rows={rows!r}; "
            f"anchor_generation={getattr(view, '_section_anchor_generation', None)!r}/"
            f"{getattr(view, '_section_generation', None)!r}; "
            f"redrives={redrives}"
        )
    except Exception as exc:
        return f"unavailable ({exc!r}); redrives={redrives}"


async def _wait_main_card_visibly_applied(
    page: AcePage,
    detail: AgentDetail,
    panel_index: int,
    card_id: str,
    *,
    description: str,
    timeout: float = 15.0,
) -> None:
    """Wait until the Main view's painted header shows ``card_id`` selected.

    The cheap semantic facts (applied generation, view selection, stored
    selection) gate the painted-header proof so a slow frame export cannot
    starve the pump under load. When those facts settle on a different card
    with no navigation in flight — a background re-delivery stole the
    selection — the scroll is re-driven instead of waiting out a state that
    will never arrive. The total budget is unchanged; exhaustion still fails
    with the spread-landing diagnostics.
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    redrives = 0
    while True:
        ready, view_active, stored_active, in_flight = _main_card_selection_state(
            detail, panel_index
        )
        settled = (
            ready
            and view_active == card_id
            and stored_active == card_id
            and not in_flight
        )
        if settled and _main_card_header_visible(page, detail, panel_index, card_id):
            return
        if loop.time() >= deadline:
            state = _main_card_diagnostics(detail, panel_index, redrives=redrives)
            raise AssertionError(
                f"Timed out after {timeout:.2f}s waiting for {description}; "
                f"Main card diagnostics: {state}"
            )
        if not in_flight and (view_active != card_id or stored_active != card_id):
            if _redrive_main_card_selection(detail, panel_index, card_id):
                redrives += 1
        await page.pause(0)
        # Poll cheap semantic facts; the painted-header export runs on match.
        await asyncio.sleep(0.01)  # sase-test-wait: poll spread selection state


def _active_main_chrome_card(detail: AgentDetail, panel_index: int) -> str | None:
    """Return the card selected by the Main header state."""
    try:
        panel = detail.deck_area.panel(panel_index)
        tabs = panel._main_tabs()
        active_index = panel._active_tab_index()
        if active_index is None:
            return None
        return tabs[active_index].card_id
    except Exception:
        return None


def _main_card_header_visible(
    page: AcePage, detail: AgentDetail, panel_index: int, card_id: str
) -> bool:
    """Return whether the exported frame shows the selected Main card header."""
    try:
        panel = detail.deck_area.panel(panel_index)
        tabs = panel._main_tabs()
        active_index = panel._active_tab_index()
        if (
            active_index is None
            or tabs[active_index].card_id != card_id
            or _active_main_chrome_card(detail, panel_index) != card_id
        ):
            return False
        title = tabs[active_index].title.replace(" ", "")
        position = f"{active_index + 1}/{len(tabs)}"
        visible_text = _page_svg_compact_styled_text(page)

        # Deck headers can put the position between the title and decorative
        # chevrons (for example, ``‹ 2/2 › Reply``). Normalize those chrome
        # marks while retaining the slash so either supported title order is
        # checked against the rendered frame.
        def compact(value: str) -> str:
            return "".join(
                char.casefold() for char in value if char.isalnum() or char == "/"
            )

        visible_text = compact(visible_text)
        title = compact(title)
        position = compact(position)
        expected_header = (f"{title}{position}", f"{position}{title}")
        if any(token in visible_text for token in expected_header):
            return True
        # Spread titles drop N/M; the here-name in the painted frame is the
        # selection proof. Micro rungs may drop the name, so also accept the
        # border title when the chrome already names this card.
        try:
            spread = bool(panel.deck_cards_spread)
        except Exception:
            spread = False
        if not spread:
            return False
        if title in visible_text:
            return True
        try:
            return title in compact(panel._border_title.plain)
        except Exception:
            return False
    except Exception:
        return False


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


async def select_navigable_main_card(
    page: AcePage, card_id: str, panel_index: int = 0
) -> None:
    """Pin a Main card after its block-navigation predicate is ready."""
    detail = page.app.query_one("#agent-detail-panel", AgentDetail)
    await wait_for_state(
        page,
        lambda: _selected_agent_matches_detail(page, detail),
        description="selected agent identity is applied to the detail panel",
    )
    await wait_for_state(
        page,
        lambda: _main_view_ready_to_cycle(detail, panel_index),
        description="selected Main document and view generation are applied",
    )
    await select_main_card(page, card_id, panel_index)

    def ready() -> bool:
        try:
            panel = detail.deck_area.focused_panel()
            return (
                panel.deck is DeckId.MAIN
                and panel.active_main_card() == card_id
                and bool(panel.card_blocks_navigable)
            )
        except Exception:
            return False

    await page.wait_for(lambda _state: ready(), timeout=15.0)
    await wait_for_visual_idle(page)
    panel = detail.deck_area.panel(panel_index)
    # On narrow terminals the agent list can intentionally consume the entire
    # usable width, leaving the detail panel's Main view at zero width. Keep
    # the card selection semantic in that layout, and require a painted header
    # only when Textual has actually laid out space for the view.
    if panel.main_view.region.width > 0 and panel.main_view.region.height > 0:
        await _wait_main_card_visibly_applied(
            page,
            detail,
            panel_index,
            card_id,
            description=f"Main view visibly applies the selected {card_id} card",
        )
    await wait_for_visual_idle(page)
    focused = detail.deck_area.focused_panel()
    assert focused.deck is DeckId.MAIN
    assert focused.active_main_card() == card_id
    assert focused.card_blocks_navigable


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
    from sase.ace.tui.modals import node_finder_rendering
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
        node_finder_rendering,
    ):
        if hasattr(module, "local_now"):
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

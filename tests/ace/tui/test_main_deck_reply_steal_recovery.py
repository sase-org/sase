"""Main-deck Reply selection survives same-subject background re-delivery.

Full CI reproduced this ordering in
``test_renamed_generic_agent_session_root_png_snapshot`` (sase-1ln): the
short session document lands its sticky Reply at row 0 (the chat-log landing
rests above Reply's own anchor, under the empty Context card). A background
enrichment then re-delivers the same subject with a taller Context card
(SASE CONTEXT sections still resolving) and later without it. Each delivery
re-lands the follow position programmatically; the spread scroll watcher used
to read those scrolls as the reader choosing Context and overwrote the stored
selection while the view still showed Reply.

This test drives those deliveries through the production sink and asserts
the selection and the landed position survive every delayed callback. It
never calls the visual readiness helper that re-drives the selection.
"""

from __future__ import annotations

from datetime import datetime

import pytest
from rich.text import Text

from sase.ace.testing import AcePage
from sase.ace.tui.widgets import AgentDetail
from sase.ace.tui.widgets.decks.card_part import context_card
from sase.ace.tui.widgets.decks.main_document import MainDeckDocument
from sase.ace.tui.widgets.decks.model import DeckId, RenderMode
from tests.ace.tui.visual._ace_agents_png_snapshot_agent_session_fixtures import (
    renamed_generic_agent_session_agents,
)
from tests.ace.tui.visual._ace_agents_png_snapshot_helpers import (
    main_deck_scroll,
    pin_agents_visual_now,
)
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_visual_idle,
)

_RESOLVING_CONTEXT = "\n".join(
    [
        "SASE CONTEXT · 4",
        *(
            line
            for section in ("ARTIFACTS", "MEMORY", "GLOSSARY", "SKILLS")
            for line in (f"▾ {section} · resolving…", "")
        ),
    ]
)


def _with_resolving_context(document: MainDeckDocument) -> MainDeckDocument:
    """Return ``document`` with the enrichment's taller Context card."""
    context = document.card("context")
    assert context is not None
    cards = tuple(
        context_card(*card.renderables, Text(_RESOLVING_CONTEXT))
        if card.card_id == "context"
        else card
        for card in document.cards
    )
    return MainDeckDocument(
        cards=cards,
        subject=document.subject,
        partial=False,
        digest=f"{document.digest}:resolving-context",
    )


def _settled_on_reply(detail: AgentDetail) -> bool:
    panel = detail.deck_area.panel(0)
    view = panel.main_view
    return (
        panel.deck is DeckId.MAIN
        and panel._render_mode.get(DeckId.MAIN) is RenderMode.SPREAD
        and view._spread_pending_card is None
        and view.delivery_hold_card is None
        and view._block_spread_pending is None
        and panel._main_active_card == "reply"
        and view.active_card_id == "reply"
    )


def _describe(detail: AgentDetail) -> str:
    panel = detail.deck_area.panel(0)
    view = panel.main_view
    scroll = view._scroll_container()
    width = view._spread_content_width()
    return (
        f"stored={panel._main_active_card!r} view={view.active_card_id!r} "
        f"hold={view.delivery_hold_card!r} "
        f"pending={view._spread_pending_card!r} "
        f"block_pending={view._block_spread_pending!r} "
        f"scroll_y={getattr(scroll, 'scroll_y', None)!r} "
        f"max_scroll_y={getattr(scroll, 'max_scroll_y', None)!r} "
        f"anchors={view.card_anchor_rows(width=width) if width > 0 else None!r}"
    )


async def _deliver_and_expect_reply(
    page: AcePage, detail: AgentDetail, document: MainDeckDocument
) -> None:
    """Deliver ``document`` through the production sink; Reply must stay put."""
    panel = detail.deck_area.panel(0)
    view = panel.main_view
    scroll = view._scroll_container()
    assert scroll is not None
    card = document.card("reply")
    assert card is not None
    detail._deliver_main_document(document)
    await page.wait_for(
        lambda _state: (
            _settled_on_reply(detail)
            and panel._main_document is document
            and int(scroll.scroll_y) == view.spread_landing_target(card)
        ),
        timeout=15.0,
        timeout_message=lambda: (
            f"Reply after re-delivery {document.digest}: {_describe(detail)}"
        ),
    )
    await wait_for_visual_idle(page)
    assert _settled_on_reply(detail), _describe(detail)
    assert int(scroll.scroll_y) == view.spread_landing_target(card)


async def test_landed_reply_survives_same_subject_context_redelivery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pin_agents_visual_now(monkeypatch, datetime(2026, 7, 18, 11, 10, 0))
    patch_startup_loaders(monkeypatch, agents=renamed_generic_agent_session_agents())

    async with AcePage(query='"visual-family"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 1)
        await page.press("l")
        await page.expect_state("agent_count", 3)
        await wait_for_visual_idle(page)

        detail = page.app.query_one("#agent-detail-panel", AgentDetail)
        await page.wait_for(
            lambda _state: _settled_on_reply(detail),
            timeout=15.0,
            timeout_message=lambda: f"sticky Reply landing: {_describe(detail)}",
        )
        panel = detail.deck_area.panel(0)
        view = panel.main_view
        scroll = main_deck_scroll(page)
        landed = detail._main_deck_document
        reply = landed.card("reply")
        assert reply is not None
        # The chat-log landing rests above Reply's own anchor, so the
        # scroll-derived card here is Context while Reply is selected.
        assert int(scroll.scroll_y) == view.spread_landing_target(reply)
        assert view.spread_active_card() == "context"

        moves: list[tuple[float, float]] = []
        panel.watch(
            scroll, "scroll_y", lambda old, new: moves.append((old, new)), init=False
        )
        for document in (_with_resolving_context(landed), landed):
            moves.clear()
            await _deliver_and_expect_reply(page, detail, document)
            # The delivery really moved the scroll through the watcher.
            assert moves, _describe(detail)

        tabs = panel._main_tabs()
        assert tabs[panel._active_tab_index()].card_id == "reply"

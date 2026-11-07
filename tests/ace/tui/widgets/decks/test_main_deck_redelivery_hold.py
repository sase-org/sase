"""Same-subject Main re-delivery keeps a parked spread reader in place.

A background re-delivery re-renders the spread under the reader. Its layout
clamp, follow landing, and anchor restore are programmatic scrolls, not card
choices (sase-1ln): the selected card and the reader's anchor-relative row
must survive every delayed callback, while explicit navigation, a new
subject, and the reader's own scrolls still win.

Every delivery goes through the production sink
(``AgentDetail._deliver_main_document``); no readiness helper re-drives the
selection.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from rich.text import Text
from textual.app import App, ComposeResult
from textual.containers import VerticalScroll

from sase.ace.testing import wait_for
from sase.ace.tui.agent_decks_settings import AgentDecksSettings
from sase.ace.tui.widgets.agent_detail import AgentDetail
from sase.ace.tui.widgets.decks.card_block import BlockMeta, CardBlock
from sase.ace.tui.widgets.decks.card_part import CardPart, context_card, reply_card
from sase.ace.tui.widgets.decks.main_document import MainDeckDocument
from sase.ace.tui.widgets.decks.model import DeckId, RenderMode

_ROOT = Path(__file__).resolve().parents[5]
_SUBJECT = "redelivery-subject"


class _DetailApp(App[None]):
    CSS_PATH = _ROOT / "src/sase/ace/tui/styles.tcss"

    def compose(self) -> ComposeResult:
        yield AgentDetail(id="agent-detail-panel")


def _block(block_id: str, lines: int) -> CardBlock:
    from sase.ace.tui.widgets.prompt_panel._agent_display_content import (
        render_phase_divider,
    )

    header = render_phase_divider(
        f"AGENT ({block_id})", None, accent="#AF87FF", block_id=block_id
    )
    return CardBlock(
        block_id,
        f"block {block_id}",
        header,
        Text("\n".join(f"{block_id}-line-{i}" for i in range(lines))),
        meta=BlockMeta(
            number="0",
            label=block_id,
            glyph="",
            accent="#AF87FF",
            status_bucket="Done",
            kind="agent",
        ),
    )


def _reply(lines_per_block: int) -> CardPart:
    return reply_card(
        Text("AGENT REPLY"),
        *(_block(f"b{i}", lines_per_block) for i in range(3)),
    )


def _document(
    *, context_lines: int, lines_per_block: int, subject: str = _SUBJECT
) -> MainDeckDocument:
    """Return a Context + Reply document; only Context grows between deliveries.

    The digest is derived from the content, as production digests are: the
    section layout cache is keyed by digest, so reusing one digest for
    different content would serve another document's anchors.
    """
    return MainDeckDocument(
        cards=(
            context_card(Text("\n".join(f"ctx-{i}" for i in range(context_lines)))),
            _reply(lines_per_block),
        ),
        subject=subject,
        partial=False,
        digest=f"redelivery-hold:{subject}:{context_lines}:{lines_per_block}",
    )


def _detail(app: _DetailApp) -> AgentDetail:
    return app.query_one("#agent-detail-panel", AgentDetail)


def _scroll(panel: Any) -> VerticalScroll:
    return panel.query_one("#agent-deck-panel-0-main-scroll", VerticalScroll)


def _settled(panel: Any) -> bool:
    view = panel.main_view
    return (
        view._spread_pending_card is None
        and view.delivery_hold_card is None
        and view._block_spread_pending is None
    )


def _state(panel: Any) -> str:
    view = panel.main_view
    scroll = _scroll(panel)
    return (
        f"scroll_y={scroll.scroll_y} max={scroll.max_scroll_y} "
        f"stored={panel._main_active_card!r} view={view.active_card_id!r} "
        f"hold={view.delivery_hold_card!r} "
        f"restore={view.delivery_restore_pending} "
        f"pending={view._spread_pending_card!r} "
        f"reply_anchor={view.spread_anchor_row('reply')!r}"
    )


async def _start(
    pilot: Any, app: _DetailApp, *, context_lines: int, lines_per_block: int
) -> Any:
    """Deliver the first document and wait for its sticky Reply landing."""
    app._agent_decks_settings = AgentDecksSettings(  # type: ignore[attr-defined]
        spread_max_screens=10, block_spread_max_screens=1000
    )
    detail = _detail(app)
    panel = detail.deck_area.panel(0)
    detail._deliver_main_document(
        _document(context_lines=context_lines, lines_per_block=lines_per_block)
    )
    await wait_for(pilot, lambda: panel._render_mode[DeckId.MAIN] is RenderMode.SPREAD)
    view = panel.main_view
    await wait_for(
        pilot,
        lambda: (
            _settled(panel)
            and view.spread_anchor_row("reply") is not None
            and panel._main_active_card == "reply"
        ),
    )
    return panel


async def _park_on_reply(pilot: Any, panel: Any, offset: int) -> int:
    """Navigate to Reply, then read ``offset`` rows into it; return the row."""
    view = panel.main_view
    assert view.scroll_to_card("reply") == "reply"
    await wait_for(
        pilot,
        lambda: (
            _settled(panel)
            and int(_scroll(panel).scroll_y) == view.spread_anchor_row("reply")
        ),
    )
    anchor = view.spread_anchor_row("reply")
    assert anchor is not None
    row = anchor + offset
    _scroll(panel).scroll_to(y=row, animate=False)
    await wait_for(pilot, lambda: int(_scroll(panel).scroll_y) == row)
    assert panel._main_active_card == "reply"
    return row


async def _wait_reply_row(pilot: Any, panel: Any, offset: int) -> None:
    view = panel.main_view

    def at_row() -> bool:
        anchor = view.spread_anchor_row("reply")
        return (
            _settled(panel)
            and anchor is not None
            and int(_scroll(panel).scroll_y) == anchor + offset
        )

    try:
        await wait_for(pilot, at_row)
    except Exception as exc:  # pragma: no cover - diagnostics only
        raise AssertionError(f"reader row not restored: {_state(panel)}") from exc


async def test_landed_reply_survives_context_growth_and_shrink() -> None:
    """The CI ordering: Context grows then shrinks while Reply is landed."""
    app = _DetailApp()
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        panel = await _start(pilot, app, context_lines=1, lines_per_block=1)
        view = panel.main_view
        scroll = _scroll(panel)
        # The short document fits: the chat-log landing rests at row 0,
        # above Reply's own anchor, so the scroll-derived card is Context.
        assert int(scroll.scroll_y) == 0
        assert view.spread_active_card() == "context"
        moves: list[tuple[float, float]] = []
        panel.watch(
            scroll, "scroll_y", lambda old, new: moves.append((old, new)), init=False
        )

        detail = _detail(app)
        detail._deliver_main_document(_document(context_lines=40, lines_per_block=1))
        reply = panel._main_document.card("reply")
        await wait_for(
            pilot,
            lambda: (
                _settled(panel)
                and int(scroll.scroll_y) == view.spread_landing_target(reply)
            ),
        )
        # The follow re-land really scrolled (the watcher saw it) and still
        # landed short of Reply's anchor, yet Reply stays selected.
        assert moves, _state(panel)
        assert int(scroll.scroll_y) < (view.spread_anchor_row("reply") or 0)
        assert panel._main_active_card == "reply", _state(panel)
        assert view.active_card_id == "reply"

        moves.clear()
        detail._deliver_main_document(_document(context_lines=1, lines_per_block=1))
        await wait_for(pilot, lambda: _settled(panel) and int(scroll.scroll_y) == 0)
        assert moves, _state(panel)
        assert panel._main_active_card == "reply", _state(panel)
        assert view.active_card_id == "reply"
        tabs = panel._main_tabs()
        assert tabs[panel._active_tab_index()].card_id == "reply"


async def test_parked_reply_keeps_anchor_row_through_redelivery() -> None:
    app = _DetailApp()
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        panel = await _start(pilot, app, context_lines=1, lines_per_block=10)
        await _park_on_reply(pilot, panel, offset=3)
        detail = _detail(app)

        detail._deliver_main_document(_document(context_lines=12, lines_per_block=10))
        await _wait_reply_row(pilot, panel, offset=3)
        assert panel._main_active_card == "reply"
        assert panel.main_view.active_card_id == "reply"

        detail._deliver_main_document(_document(context_lines=1, lines_per_block=10))
        await _wait_reply_row(pilot, panel, offset=3)
        assert panel._main_active_card == "reply"


async def test_second_delivery_carries_the_pending_restore() -> None:
    app = _DetailApp()
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        panel = await _start(pilot, app, context_lines=1, lines_per_block=10)
        await _park_on_reply(pilot, panel, offset=3)
        detail = _detail(app)
        # Two deliveries before any refresh: the first restore never ran,
        # so the second must carry its offset instead of re-measuring the
        # stale scroll against unpublished anchors.
        detail._deliver_main_document(_document(context_lines=12, lines_per_block=10))
        assert panel.main_view.delivery_restore_pending
        detail._deliver_main_document(_document(context_lines=20, lines_per_block=10))
        await _wait_reply_row(pilot, panel, offset=3)
        assert panel._main_active_card == "reply"


async def test_explicit_navigation_supersedes_a_pending_restore() -> None:
    app = _DetailApp()
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        panel = await _start(pilot, app, context_lines=1, lines_per_block=10)
        await _park_on_reply(pilot, panel, offset=3)
        view = panel.main_view
        _detail(app)._deliver_main_document(
            _document(context_lines=12, lines_per_block=10)
        )
        assert view.delivery_hold_card == "reply"
        assert view.scroll_to_card("context") == "context"
        assert view.delivery_hold_card is None
        assert not view.delivery_restore_pending
        # Settled with the new anchors published: the superseded restore
        # (Reply anchor + 3) had its chance and never moved the reader.
        await wait_for(
            pilot,
            lambda: (
                _settled(panel)
                and view.spread_anchor_row("reply") is not None
                and int(_scroll(panel).scroll_y) == 0
            ),
        )
        assert panel._main_active_card == "context", _state(panel)
        assert view.active_card_id == "context"


async def test_reader_scroll_still_selects_and_survives_redelivery() -> None:
    app = _DetailApp()
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        panel = await _start(pilot, app, context_lines=1, lines_per_block=10)
        await _park_on_reply(pilot, panel, offset=3)
        view = panel.main_view
        # The reader scrolls back up into Context: a real selection change.
        _scroll(panel).scroll_to(y=0, animate=False)
        await wait_for(pilot, lambda: panel._main_active_card == "context")
        assert view.active_card_id == "context"
        # A later re-delivery must keep the reader's choice, not snap back
        # to the previously navigated Reply card.
        _detail(app)._deliver_main_document(
            _document(context_lines=12, lines_per_block=10)
        )
        await wait_for(
            pilot, lambda: _settled(panel) and int(_scroll(panel).scroll_y) == 0
        )
        assert panel._main_active_card == "context", _state(panel)
        assert view.active_card_id == "context"


async def test_new_subject_drops_the_previous_restore() -> None:
    app = _DetailApp()
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        panel = await _start(pilot, app, context_lines=1, lines_per_block=10)
        await _park_on_reply(pilot, panel, offset=3)
        view = panel.main_view
        detail = _detail(app)
        detail._deliver_main_document(_document(context_lines=12, lines_per_block=10))
        assert view.delivery_restore_pending
        detail._deliver_main_document(
            _document(
                context_lines=12,
                lines_per_block=10,
                subject="another-subject",
            )
        )
        assert not view.delivery_restore_pending
        reply = panel._main_document.card("reply")
        await wait_for(
            pilot,
            lambda: (
                _settled(panel)
                and int(_scroll(panel).scroll_y) == view.spread_landing_target(reply)
            ),
        )
        assert panel._main_active_card == "reply"

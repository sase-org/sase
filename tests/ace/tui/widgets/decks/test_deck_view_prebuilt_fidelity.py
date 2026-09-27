"""Prebuilt deferred Main bodies paint like the synchronous render."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from rich.segment import Segment
from rich.text import Text
from textual.app import App, ComposeResult
from textual.strip import Strip

from sase.ace.testing import wait_for
from sase.ace.tui.agent_decks_settings import AgentDecksSettings
from sase.ace.tui.widgets.agent_detail import AgentDetail
from sase.ace.tui.widgets.decks.card_block import BlockMeta, CardBlock
from sase.ace.tui.widgets.decks.card_part import context_card, reply_card
from sase.ace.tui.widgets.decks.main_document import MainDeckDocument
from sase.ace.tui.widgets.decks.model import DeckId, DeckView, RenderMode
from sase.ace.tui.widgets.decks.panel_view_deferred import (
    build_destination_renderable,
    build_prebuilt_offthread,
    capture_prebuilt_context,
    get_prebuilt,
    store_prebuilt,
)
from sase.ace.tui.widgets.decks.view_policy import forced_block_mode

_ROOT = Path(__file__).resolve().parents[5]


class _DetailApp(App[None]):
    CSS_PATH = _ROOT / "src/sase/ace/tui/styles.tcss"

    def compose(self) -> ComposeResult:
        yield AgentDetail(id="agent-detail-panel")


def _meta(label: str) -> BlockMeta:
    return BlockMeta(
        number="0",
        label=label,
        glyph="",
        accent="#AF87FF",
        status_bucket="Done",
        kind="agent",
    )


def _block(block_id: str, *lines: str) -> CardBlock:
    from sase.ace.tui.widgets.prompt_panel._agent_display_content import (
        render_phase_divider,
    )

    header = render_phase_divider(
        f"AGENT ({block_id})",
        None,
        accent="#AF87FF",
        block_id=block_id,
    )
    return CardBlock(
        block_id,
        f"block {block_id}",
        header,
        Text("\n".join(lines)),
        meta=_meta(block_id),
    )


def _reply_card() -> Any:
    blocks = [
        _block(f"b{i}", *(f"block-{i}-line-{j}" for j in range(12))) for i in range(3)
    ]
    return reply_card(Text("TRACEBACK-draw"), *blocks)


def _document() -> MainDeckDocument:
    return MainDeckDocument(
        cards=(context_card(Text("context-body")), _reply_card()),
        subject="fidelity",
        partial=False,
        digest="fidelity-1",
    )


def _strip_signature(strips: tuple[Strip, ...] | list[Strip]) -> list[Any]:
    return [[(segment.text, segment.style) for segment in strip] for strip in strips]


@pytest.mark.parametrize(
    ("deck_pin", "block_pin", "layout", "spread", "anchor_block", "policy"),
    (
        (0.0, 1000.0, DeckView.PAGE_CARDS, False, None, DeckView.PAGE_CARDS),
        (1000.0, 1000.0, DeckView.SPREAD, True, None, DeckView.SPREAD),
        (0.0, 0.0, DeckView.PAGE_BLOCKS, False, "b1", DeckView.PAGE_BLOCKS),
    ),
)
async def test_prebuilt_matches_synchronous_render(
    deck_pin: float,
    block_pin: float,
    layout: DeckView,
    spread: bool,
    anchor_block: str | None,
    policy: DeckView,
) -> None:
    """Prebuilt strips equal the synchronous RichVisual strips per layout."""
    app = _DetailApp()
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        app._agent_decks_settings = AgentDecksSettings(
            spread_max_screens=deck_pin, block_spread_max_screens=block_pin
        )
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        panel = detail.deck_area.panel(0)
        document = _document()
        panel.show_main_document(document, "reply")
        await wait_for(pilot, lambda: panel.effective_layout(DeckId.MAIN) is layout)
        await pilot.pause()
        await pilot.pause()
        view = panel.main_view
        width = int(view._spread_content_width())
        assert width > 0
        card = document.card("reply")
        assert card is not None
        try:
            block_total = len(card.blocks)
        except Exception:
            block_total = 0
        want_paged_blocks = forced_block_mode(policy, block_total) is RenderMode.PAGED
        renderable, digest = build_destination_renderable(
            document,
            spread=spread,
            target_card_id="reply",
            anchor_block_id=anchor_block,
            want_paged_blocks=bool(want_paged_blocks),
            spread_accent=view._spread_accent(),
        )
        assert digest is not None
        context = capture_prebuilt_context(app, view, renderable)
        assert context is not None
        prebuilt_strips, _, _ = build_prebuilt_offthread(context, width)
        # Synchronous reference: exactly RichVisual.render_strips' derivation.
        ref_options = app.console_options.update(
            highlight=False, width=width, height=None
        ).update_width(width)
        ref_segments = list(app.console.render(context.wrapped, ref_options))
        ref_strips = [
            Strip(line)
            for line in Segment.split_and_crop_lines(
                ref_segments, width, include_new_lines=False, pad=False
            )
        ]
        assert _strip_signature(prebuilt_strips) == _strip_signature(ref_strips)


async def test_prebuilt_served_only_under_matching_base_style() -> None:
    """The serve path honors the style token and falls back on mismatch."""
    app = _DetailApp()
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        app._agent_decks_settings = AgentDecksSettings(
            spread_max_screens=0.0, block_spread_max_screens=1000.0
        )
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        panel = detail.deck_area.panel(0)
        document = _document()
        panel.show_main_document(document, "reply")
        await wait_for(
            pilot, lambda: panel.effective_layout(DeckId.MAIN) is DeckView.PAGE_CARDS
        )
        await pilot.pause()
        await pilot.pause()
        view = panel.main_view
        width = int(view._spread_content_width())
        renderable, digest = build_destination_renderable(
            document,
            spread=False,
            target_card_id="reply",
            anchor_block_id=None,
            want_paged_blocks=False,
            spread_accent=view._spread_accent(),
        )
        assert digest is not None
        context = capture_prebuilt_context(app, view, renderable)
        assert context is not None
        strips, height, anchors = build_prebuilt_offthread(context, width)
        store_prebuilt(digest, width, strips, height, anchors, context.style_token)
        assert get_prebuilt(digest, width, context.style_token) is not None
        assert get_prebuilt(digest, width, "mismatched-token") is None

"""Shared apps and fixtures for Main deck-view pilot tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from rich.text import Text
from textual.app import App, ComposeResult

from sase.ace.testing import wait_for
from sase.ace.tui.agent_decks_settings import AgentDecksSettings
from sase.ace.tui.widgets.agent_detail import AgentDetail
from sase.ace.tui.widgets.decks.card_block import BlockMeta, CardBlock
from sase.ace.tui.widgets.decks.card_part import CardPart, context_card, reply_card
from sase.ace.tui.widgets.decks.main_document import MainDeckDocument
from sase.ace.tui.widgets.decks.model import DeckId, DeckView

_ROOT = Path(__file__).resolve().parents[5]


class MainDetailApp(App[None]):
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


def make_reply_card(block_count: int, *, lines_per_block: int = 12) -> CardPart:
    blocks = [
        _block(
            f"b{i}",
            *(f"block-{i}-line-{j}" for j in range(lines_per_block)),
        )
        for i in range(block_count)
    ]
    return reply_card(Text("TRACEBACK-draw"), *blocks)


def make_document(
    subject: object,
    reply: CardPart,
    *,
    digest: str,
    partial: bool = False,
) -> MainDeckDocument:
    return MainDeckDocument(
        cards=(context_card(Text("context-body")), reply),
        subject=subject,
        partial=partial,
        digest=digest,
    )


def pin_settings(app: Any, *, deck: float = 0, blocks: float = 0) -> None:
    app._agent_decks_settings = AgentDecksSettings(
        spread_max_screens=deck, block_spread_max_screens=blocks
    )


async def get_panel(app: MainDetailApp) -> Any:
    detail = app.query_one("#agent-detail-panel", AgentDetail)
    return detail.deck_area.panel(0)


async def settle_view(pilot: Any, panel: Any, layout: DeckView) -> None:
    await wait_for(pilot, lambda: panel.effective_layout(DeckId.MAIN) is layout)
    # Deferred Main bodies apply off the pump: wait until this generation's
    # body has been applied or dropped before asserting block/offset/pin.
    await wait_for(
        pilot,
        lambda: (
            int(getattr(panel, "_main_view_applied_generation", 0))
            >= int(getattr(panel, "_view_generation", 0))
        ),
    )
    try:
        view = panel.main_view
        await wait_for(
            pilot,
            lambda: (
                int(getattr(view, "_section_anchor_generation", -1))
                == int(getattr(view, "_section_generation", 0))
            ),
        )
    except Exception:
        pass
    await pilot.pause()
    await pilot.pause()


__all__ = [
    "MainDetailApp",
    "get_panel",
    "make_document",
    "make_reply_card",
    "pin_settings",
    "settle_view",
]

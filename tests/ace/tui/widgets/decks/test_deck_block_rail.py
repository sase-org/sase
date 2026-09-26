"""Tests for the one-row block rail: pure tiers plus panel pilots."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from rich.cells import cell_len
from rich.text import Text
from textual.app import App, ComposeResult

from sase.ace.testing import wait_for
from sase.ace.tui.agent_decks_settings import AgentDecksSettings
from sase.ace.tui.keymaps.display import key_display_name
from sase.ace.tui.widgets.agent_detail import AgentDetail
from sase.ace.tui.widgets.decks.block_rail import (
    RAIL_HORIZONTAL_PADDING,
    BlockRail,
    BlockRailEntry,
    block_rail_text,
    render_block_rail,
)
from sase.ace.tui.widgets.decks.card_block import BlockMeta, CardBlock
from sase.ace.tui.widgets.decks.card_part import context_card, reply_card
from sase.ace.tui.widgets.decks.main_document import MainDeckDocument
from sase.ace.tui.widgets.decks.model import DeckId, RenderMode
from sase.feature_flags import override_flags

_ROOT = Path(__file__).resolve().parents[5]
_ACCENT = "#B48EAD"


class _DetailApp(App[None]):
    CSS_PATH = _ROOT / "src/sase/ace/tui/styles.tcss"

    def compose(self) -> ComposeResult:
        yield AgentDetail(id="agent-detail-panel")


def _meta(number: int, label: str, **kwargs: Any) -> BlockMeta:
    return BlockMeta(
        number=str(number),
        label=label,
        glyph=kwargs.get("glyph", ""),
        accent=kwargs.get("accent", "#AF87FF"),
        status_bucket=kwargs.get("status_bucket", "Done"),
        kind=kwargs.get("kind", "agent"),
    )


def _entries(count: int) -> list[BlockRailEntry]:
    return [BlockRailEntry(f"b{i}", _meta(i, f"--phase-{i}")) for i in range(count)]


def _hint() -> tuple[str, str]:
    return (
        key_display_name("left_square_bracket"),
        key_display_name("right_square_bracket"),
    )


def _span_styles(text: Text) -> list[str]:
    return [str(span.style) for span in text.spans]


def test_tier_ladder_from_20_to_200() -> None:
    """Twelve blocks step down full-hint → full → windowed → compact → micro."""
    entries = _entries(12)
    seen: list[str] = []
    for width in range(20, 201, 5):
        text, ranges, tier = render_block_rail(
            entries,
            active_id="b10",
            arrived_ids=(),
            width=width,
            accent=_ACCENT,
            focused=True,
            key_hint=_hint(),
        )
        assert tier is not None
        assert cell_len(text.plain) <= width
        seen.append(tier)
    assert seen[0] in ("compact", "micro")
    assert seen[-1] in ("full", "full-hint")
    wide, _, wide_tier = render_block_rail(
        entries,
        active_id="b10",
        arrived_ids=(),
        width=400,
        accent=_ACCENT,
        focused=True,
        key_hint=_hint(),
    )
    assert wide_tier == "full-hint"
    assert cell_len(wide.plain) <= 400
    # The ladder only narrows as width shrinks.
    order = ["full-hint", "full", "windowed", "compact", "micro"]
    indices = [order.index(tier) for tier in seen]
    assert indices == sorted(indices, reverse=True)


def test_never_overflows_small_widths() -> None:
    """Every width from 1 to 200 renders within budget, all tiers."""
    scenarios = [
        (_entries(3), "b2", ()),
        (_entries(12), "b0", ("b11",)),
        (_entries(12), "b5", ("b6", "b7")),
    ]
    for entries, active_id, arrived in scenarios:
        for width in range(1, 201):
            text = block_rail_text(
                entries,
                active_id=active_id,
                arrived_ids=arrived,
                width=width,
                accent=_ACCENT,
                focused=True,
                key_hint=_hint(),
            )
            assert cell_len(text.plain) <= width


def test_active_pill_at_first_middle_and_last() -> None:
    """The pill caps wrap the active entry wherever it sits."""
    entries = _entries(3)
    for active_id in ("b0", "b1", "b2"):
        text, ranges, tier = render_block_rail(
            entries,
            active_id=active_id,
            arrived_ids=(),
            width=200,
            accent=_ACCENT,
            focused=True,
            key_hint=None,
        )
        assert tier == "full"
        assert set(ranges) == {"b0", "b1", "b2"}
        start, end = ranges[active_id]
        segment = text.plain[start:end]
        assert segment.startswith("▐") and segment.endswith("▌")
        assert "▐" not in text.plain[:start]
        assert "▌" not in text.plain[end:]


def test_arrival_dot_inline_and_on_overflow() -> None:
    """Arrivals show inline when visible and ride the indicator when cut."""
    entries = _entries(12)
    wide, _, _ = render_block_rail(
        entries,
        active_id="b5",
        arrived_ids=("b11",),
        width=200,
        accent=_ACCENT,
        focused=True,
        key_hint=None,
    )
    assert "●11" in wide.plain
    narrow, narrow_ranges, tier = render_block_rail(
        entries,
        active_id="b0",
        arrived_ids=("b11",),
        width=40,
        accent=_ACCENT,
        focused=True,
        key_hint=None,
    )
    assert tier in ("windowed", "compact")
    assert "b11" not in narrow_ranges
    assert "●" in narrow.plain


def test_unfocused_rail_dims_pill() -> None:
    """An unfocused panel renders the pill reverse-dim, never bold."""
    entries = _entries(3)
    focused_text, _, _ = render_block_rail(
        entries,
        active_id="b1",
        arrived_ids=(),
        width=200,
        accent=_ACCENT,
        focused=True,
        key_hint=None,
    )
    assert f"reverse bold {_ACCENT}" in _span_styles(focused_text)
    dimmed_text, _, _ = render_block_rail(
        entries,
        active_id="b1",
        arrived_ids=(),
        width=200,
        accent=_ACCENT,
        focused=False,
        key_hint=None,
    )
    styles = _span_styles(dimmed_text)
    assert "reverse dim" in styles
    assert not any("reverse bold" in style for style in styles)


def test_key_hint_only_at_widest_tier() -> None:
    """The live-named hint shows with full-hint and nowhere narrower."""
    entries = _entries(3)
    hint_text, _, hint_tier = render_block_rail(
        entries,
        active_id="b2",
        arrived_ids=(),
        width=200,
        accent=_ACCENT,
        focused=True,
        key_hint=_hint(),
    )
    assert hint_tier == "full-hint"
    assert "[ older · newer ]" in hint_text.plain
    plain_text, _, plain_tier = render_block_rail(
        entries,
        active_id="b2",
        arrived_ids=(),
        width=60,
        accent=_ACCENT,
        focused=True,
        key_hint=_hint(),
    )
    assert plain_tier == "full"
    assert "older · newer" not in plain_text.plain


def test_micro_ellipsizes_label_as_last_resort() -> None:
    """A narrow rail keeps the pill plus counts, truncating the label."""
    entries = _entries(12)
    text, _, tier = render_block_rail(
        entries,
        active_id="b10",
        arrived_ids=(),
        width=24,
        accent=_ACCENT,
        focused=True,
        key_hint=None,
    )
    assert tier == "micro"
    assert "‹" in text.plain and "›" in text.plain
    assert "▐" in text.plain and "▌" in text.plain
    assert cell_len(text.plain) <= 24
    tighter, _, _ = render_block_rail(
        entries,
        active_id="b10",
        arrived_ids=(),
        width=22,
        accent=_ACCENT,
        focused=True,
        key_hint=None,
    )
    assert "…" in tighter.plain
    assert "‹" in tighter.plain and "›" in tighter.plain
    assert cell_len(tighter.plain) <= 22


def _block_meta(label: str) -> BlockMeta:
    return BlockMeta(
        number="0",
        label=label,
        glyph="",
        accent="#AF87FF",
        status_bucket="Done",
        kind="agent",
    )


def _block(block_id: str, *lines: str) -> CardBlock:
    return CardBlock(
        block_id,
        f"block {block_id}",
        Text("\n".join(lines)),
        meta=_block_meta(block_id),
    )


def _reply_card(block_count: int, *, lines_per_block: int = 3) -> Any:
    blocks = [
        _block(
            f"b{i}",
            *(f"block-{i}-line-{j}" for j in range(lines_per_block)),
        )
        for i in range(block_count)
    ]
    return reply_card(Text("TRACEBACK-draw"), *blocks)


def _document(
    subject: object,
    reply: Any,
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


def _pin(app: Any, *, deck: float = 0, blocks: float = 0) -> None:
    app._agent_decks_settings = AgentDecksSettings(
        spread_max_screens=deck, block_spread_max_screens=blocks
    )


async def _panel(app: _DetailApp) -> Any:
    detail = app.query_one("#agent-detail-panel", AgentDetail)
    return detail.deck_area.panel(0)


def _rail(panel: Any) -> BlockRail:
    return panel.query_one(BlockRail)


async def test_rail_visible_in_paged_deck_and_follows_cycle() -> None:
    """The rail shows on a paged block card and tracks [ navigation."""
    app = _DetailApp()
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        _pin(app)
        panel = await _panel(app)
        with override_flags(card_blocks=True):
            panel.show_main_document(
                _document("s1", _reply_card(3), digest="rail-1"), "reply"
            )
            rail = _rail(panel)
            await wait_for(pilot, lambda: bool(rail._ranges))
            assert rail.has_class("-shown")
            assert set(rail._ranges) == {"b0", "b1", "b2"}
            assert panel.main_view.active_block_id("reply") == "b2"
            # Click ranges resolve back to their blocks.
            for block_id, (start, end) in rail._ranges.items():
                assert rail.block_id_at(RAIL_HORIZONTAL_PADDING + start) == block_id
                assert rail.block_id_at(RAIL_HORIZONTAL_PADDING + end - 1) == block_id
            assert panel.cycle_block(-1) is True
            await wait_for(
                pilot, lambda: panel.main_view.active_block_id("reply") == "b1"
            )
            start, end = rail._ranges["b1"]
            pill = rail.render()
            assert pill is not None
            assert rail.block_id_at(RAIL_HORIZONTAL_PADDING + start) == "b1"
            assert end > start


async def test_rail_hidden_flag_off_spread_partial_and_subject_change() -> None:
    """The rail hides off-flag, in spread decks, on partials, on resubject."""
    app = _DetailApp()
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        _pin(app)
        panel = await _panel(app)
        # Flag off: a block card renders undivided with no rail.
        with override_flags(card_blocks=False):
            panel.show_main_document(
                _document("s1", _reply_card(3), digest="rail-off"), "reply"
            )
            await pilot.pause()
            rail = _rail(panel)
            assert not rail.has_class("-shown")
        with override_flags(card_blocks=True):
            panel.show_main_document(
                _document("s1", _reply_card(3), digest="rail-on"), "reply"
            )
            await wait_for(pilot, lambda: bool(_rail(panel)._ranges))
            assert _rail(panel).has_class("-shown")
            # Partial paint clears the rail so it never shows stale shells.
            panel.show_main_document(
                _document("s2", _reply_card(3), digest="rail-partial", partial=True),
                "reply",
            )
            await pilot.pause()
            cleared = _rail(panel)
            assert not cleared.has_class("-shown")
            assert cleared._ranges == {}
            # A new subject redraws the rail from its own full document.
            panel.show_main_document(
                _document("s2", _reply_card(3), digest="rail-s2"), "reply"
            )
            await wait_for(pilot, lambda: bool(_rail(panel)._ranges))
            assert _rail(panel).has_class("-shown")


async def test_rail_hidden_in_spread_deck_but_shown_in_block_spread() -> None:
    """Spread decks hide the rail; block-spread cards in paged decks keep it."""
    app = _DetailApp()
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        _pin(app)
        panel = await _panel(app)
        with override_flags(card_blocks=True):
            _pin(app, deck=1000)
            panel.show_main_document(
                _document("s1", _reply_card(3), digest="rail-spread"), "reply"
            )
            await pilot.pause()
            assert not _rail(panel).has_class("-shown")
    spread_app = _DetailApp()
    async with spread_app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        _pin(spread_app, deck=0, blocks=1000)
        panel = await _panel(spread_app)
        with override_flags(card_blocks=True):
            panel.show_main_document(
                _document("s1", _reply_card(3), digest="rail-bspread"), "reply"
            )
            await wait_for(
                pilot,
                lambda: panel.block_mode_for_active_card() is RenderMode.SPREAD,
            )
            await wait_for(pilot, lambda: bool(_rail(panel)._ranges))
            assert _rail(panel).has_class("-shown")


async def test_rail_click_selects_block() -> None:
    """Clicking a rail entry selects that block."""
    app = _DetailApp()
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        _pin(app)
        panel = await _panel(app)
        with override_flags(card_blocks=True):
            panel.show_main_document(
                _document("s1", _reply_card(3), digest="rail-click"), "reply"
            )
            rail = _rail(panel)
            await wait_for(pilot, lambda: bool(rail._ranges))
            # Clicks need a laid-out rail: wait until it has a real region.
            await wait_for(pilot, lambda: rail.region.width > 0)
            assert panel.main_view.active_block_id("reply") == "b2"
            start, _end = rail._ranges["b0"]
            await pilot.click(BlockRail, offset=(RAIL_HORIZONTAL_PADDING + start, 0))
            await wait_for(
                pilot, lambda: panel.main_view.active_block_id("reply") == "b0"
            )


async def test_dual_panel_independent_pills() -> None:
    """Two split panels keep independent active pills."""
    from sase.ace.tui.widgets.decks.model import DeckLayout  # noqa: PLC0415

    app = _DetailApp()
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.pause()
        _pin(app)
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        panel0 = detail.deck_area.panel(0)
        with override_flags(card_blocks=True):
            panel0.show_main_document(
                _document("s1", _reply_card(3), digest="rail-split"), "reply"
            )
            rail0 = panel0.query_one(BlockRail)
            await wait_for(pilot, lambda: bool(rail0._ranges))
            detail.toggle_deck_split(DeckLayout.LEFT_RIGHT)
            await pilot.pause()
            panel1 = detail.deck_area.panel(1)
            panel1.set_deck(DeckId.MAIN)
            panel1.show_main_document(
                _document("s1", _reply_card(3), digest="rail-split"), "reply"
            )
            await wait_for(pilot, lambda: bool(panel1.query_one(BlockRail)._ranges))
            assert panel1.cycle_block(-1) is True
            await wait_for(
                pilot, lambda: panel1.main_view.active_block_id("reply") == "b1"
            )
            assert panel0.main_view.active_block_id("reply") == "b2"
            assert set(rail0._ranges) == {"b0", "b1", "b2"}
            assert set(panel1.query_one(BlockRail)._ranges) == {"b0", "b1", "b2"}

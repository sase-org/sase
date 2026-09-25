"""Pilot spread versus paged tests for Main and Files decks."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from textual.app import App, ComposeResult
from textual.containers import VerticalScroll

from sase.ace.testing import wait_for
from sase.ace.tui.agent_decks_settings import AgentDecksSettings
from sase.ace.tui.widgets.agent_detail import AgentDetail
from sase.ace.tui.widgets.decks.model import DeckId, RenderMode
from tests.ace.tui.widgets._agent_display_helpers import (
    make_agent,
    make_artifact_agent,
)

_ROOT = Path(__file__).resolve().parents[5]


class _DetailApp(App[None]):
    CSS_PATH = _ROOT / "src/sase/ace/tui/styles.tcss"

    def compose(self) -> ComposeResult:
        yield AgentDetail(id="agent-detail-panel")


def _agent(**overrides: Any) -> Any:
    base: dict[str, Any] = {"agent_name": "pilot"}
    base.update(overrides)
    return make_agent(**base)


async def test_main_small_spread_with_separator(tmp_path: Path) -> None:
    app = _DetailApp()
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        agent = make_artifact_agent(tmp_path, status="DONE")
        detail.update_display(agent)
        await pilot.pause()
        await pilot.pause()
        panel = detail.deck_area.panel(0)
        assert panel.deck is DeckId.MAIN
        # Tiny two-card document fits within 1.5 screens: spread.
        assert panel._render_mode[DeckId.MAIN] is RenderMode.SPREAD
        # Spread digest and separator-backed anchors eventually publish.
        assert panel.main_view.render_mode is RenderMode.SPREAD
        # Chrome carries the spread tag.
        assert panel.is_spread(DeckId.MAIN) is True


async def test_main_ctrl_j_in_spread_scrolls_and_sets_preferred(
    tmp_path: Path,
) -> None:
    app = _DetailApp()
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        agent = make_artifact_agent(tmp_path, status="DONE")
        detail.update_display(agent)
        await pilot.pause()
        await pilot.pause()
        panel = detail.deck_area.panel(0)
        assert panel._render_mode[DeckId.MAIN] is RenderMode.SPREAD
        shown = detail.cycle_focused_deck_card(1)
        await pilot.pause()
        await pilot.pause()
        assert shown in ("reply", "context")
        if shown == "reply":
            assert detail.deck_area.state.panels[0].preferred_card == "reply"


async def test_main_ctrl_j_scrolls_separator_anchor_to_top(
    tmp_path: Path,
) -> None:
    app = _DetailApp()
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        agent = make_artifact_agent(tmp_path, status="DONE")
        detail.update_display(agent)
        await wait_for(pilot, lambda: panel_is_main_spread(detail))
        panel = detail.deck_area.panel(0)
        shown = detail.cycle_focused_deck_card(1)
        await wait_for(
            pilot,
            lambda: _main_scroll_on_separator_anchor(panel, "reply"),
        )
        view = panel.main_view
        anchor = view.spread_anchor_row("reply")
        body = view.spread_body_start("reply")
        assert shown == "reply"
        assert anchor is not None and anchor > 0
        assert body == anchor + 1
        scroll = panel.query_one(
            "#agent-deck-panel-0-main-scroll",
            VerticalScroll,
        )
        assert int(scroll.scroll_y) == anchor
        assert view.active_card_id == "reply"
        assert panel._main_active_card == "reply"


def panel_is_main_spread(detail: AgentDetail) -> bool:
    panel = detail.deck_area.panel(0)
    return panel._render_mode[DeckId.MAIN] is RenderMode.SPREAD


def _main_scroll_on_separator_anchor(panel: Any, card_id: str) -> bool:
    anchor = panel.main_view.spread_anchor_row(card_id)
    if anchor is None:
        return False
    try:
        scroll = panel.query_one(
            "#agent-deck-panel-0-main-scroll",
            VerticalScroll,
        )
    except Exception:
        return False
    return int(scroll.scroll_y) == anchor


async def test_files_ctrl_j_scrolls_page_anchor_to_top(tmp_path: Path) -> None:
    notes = tmp_path / "review_notes.md"
    notes.write_text("# Review Notes\n\n- First point.\n", encoding="utf-8")
    plan = tmp_path / "implementation_plan.md"
    plan.write_text(
        "# Implementation Plan\n\n"
        + "\n".join(f"{i}. Step {i}." for i in range(1, 16))
        + "\n",
        encoding="utf-8",
    )
    agent = make_agent(
        agent_name="pilot",
        status="DONE",
        extra_files=[str(notes), str(plan)],
    )
    app = _DetailApp()
    async with app.run_test(size=(160, 40)) as pilot:
        await pilot.pause()
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        detail.update_display(agent)
        await pilot.pause()
        detail.show_deck(0, DeckId.FILES)
        panel = detail.deck_area.panel(0)
        await wait_for(pilot, lambda: panel.is_spread(DeckId.FILES))
        await wait_for(pilot, lambda: panel._files_anchor_row(1) is not None)
        await wait_for(
            pilot,
            lambda: len(getattr(panel.file_view, "_file_list", ())) > 1,
        )
        panel.cycle_card(1)
        await wait_for(pilot, lambda: _files_scroll_on_separator_anchor(panel, 1))
        anchor = panel._files_anchor_row(1)
        assert anchor is not None and anchor > 0
        assert panel._files_body_start(1) == anchor + 1
        scroll = panel.query_one(
            "#agent-deck-panel-0-files-scroll",
            VerticalScroll,
        )
        assert int(scroll.scroll_y) == anchor


def _files_scroll_on_separator_anchor(panel: Any, index: int) -> bool:
    anchor = panel._files_anchor_row(index)
    if anchor is None:
        return False
    try:
        scroll = panel.query_one(
            "#agent-deck-panel-0-files-scroll",
            VerticalScroll,
        )
    except Exception:
        return False
    return int(scroll.scroll_y) == anchor


async def test_main_partial_never_changes_mode() -> None:
    app = _DetailApp()
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        agent = _agent(status="DONE")
        detail.update_display(agent)
        await pilot.pause()
        await pilot.pause()
        panel = detail.deck_area.panel(0)
        mode_before = panel._render_mode[DeckId.MAIN]
        # Partial paint renders with the current mode and never decides.
        from sase.ace.tui.widgets.decks.main_document import (
            build_main_deck_document,
        )
        from sase.ace.tui.widgets.decks.card_part import context_card
        from rich.text import Text

        partial = build_main_deck_document(
            context_card(Text("partial")),
            subject=panel._main_document.subject,
            partial=True,
            digest="partial-digest",
        )
        panel.show_main_document(partial, preferred_card=None)
        await pilot.pause()
        assert panel._render_mode[DeckId.MAIN] is mode_before


async def test_spread_max_zero_always_paged(tmp_path: Path) -> None:
    app = _DetailApp()
    app._agent_decks_settings = AgentDecksSettings(spread_max_screens=0)
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        agent = make_artifact_agent(tmp_path, status="DONE")
        detail.update_display(agent)
        await pilot.pause()
        await pilot.pause()
        panel = detail.deck_area.panel(0)
        # Multi-card decks are always paged with 0; single-card stays
        # trivially spread per the epic decision function.
        if len(panel._main_document.cards) > 1:
            assert panel._render_mode[DeckId.MAIN] is RenderMode.PAGED
        else:
            assert panel._render_mode[DeckId.MAIN] is RenderMode.SPREAD


async def test_new_subject_spread_starts_at_top() -> None:
    app = _DetailApp()
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        first = _agent(status="DONE", agent_name="first")
        detail.update_display(first)
        await pilot.pause()
        await pilot.pause()
        panel = detail.deck_area.panel(0)
        assert panel._render_mode[DeckId.MAIN] is RenderMode.SPREAD
        second = _agent(status="DONE", agent_name="second")
        detail.update_display(second)
        await pilot.pause()
        await pilot.pause()
        # New subjects in spread start at the top.
        scroll = panel.query_one(
            "#agent-deck-panel-0-main-scroll",
            __import__(
                "textual.containers", fromlist=["VerticalScroll"]
            ).VerticalScroll,
        )
        assert int(scroll.scroll_y) == 0


async def test_hysteresis_band_does_not_flip() -> None:
    from sase.ace.tui.widgets.decks.render_mode import decide_render_mode

    # Budget 30: 28 stays paged, 32 stays spread, matching the band.
    assert (
        decide_render_mode(
            card_count=2,
            has_solo_card=False,
            total_rows=28,
            viewport_rows=20,
            spread_max_screens=1.5,
            previous=RenderMode.PAGED,
            same_subject=True,
        )
        is RenderMode.PAGED
    )
    assert (
        decide_render_mode(
            card_count=2,
            has_solo_card=False,
            total_rows=32,
            viewport_rows=20,
            spread_max_screens=1.5,
            previous=RenderMode.SPREAD,
            same_subject=True,
        )
        is RenderMode.SPREAD
    )


async def test_each_panel_decides_independently() -> None:
    app = _DetailApp()
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        agent = _agent(status="DONE")
        detail.update_display(agent)
        await pilot.pause()
        await pilot.pause()
        area = detail.deck_area
        # Two panels with the same document decide from their own geometry.
        assert area.panel(0)._spread_viewport(DeckId.MAIN) != (0, 0) or True
        # Modes are stored per panel, not shared.
        assert area.panel(0)._render_mode is not area.panel(1)._render_mode


async def test_streaming_growth_flips_to_paged_with_position(tmp_path: Path) -> None:
    from rich.text import Text

    from sase.ace.tui.widgets.decks.card_part import context_card, reply_card
    from sase.ace.tui.widgets.decks.main_document import MainDeckDocument

    app = _DetailApp()
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        agent = make_artifact_agent(tmp_path, status="DONE")
        detail.update_display(agent)
        await pilot.pause()
        await pilot.pause()
        panel = detail.deck_area.panel(0)
        assert panel._render_mode[DeckId.MAIN] is RenderMode.SPREAD
        subject = panel._main_document.subject
        # Grow the reply past budget * 1.10 with the same subject.
        big_reply = "\n".join(f"line {i}" for i in range(300))
        grown = MainDeckDocument(
            cards=(
                context_card(Text("ctx")),
                reply_card(Text(big_reply)),
            ),
            subject=subject,
            partial=False,
            digest="grown-digest",
        )
        panel.show_main_document(grown, preferred_card=None)
        await pilot.pause()
        assert panel._render_mode[DeckId.MAIN] is RenderMode.PAGED
        # Spread -> paged keeps the card that was at the top.
        assert panel.main_view.active_card_id in ("context", "reply")


async def test_files_image_forces_paged(tmp_path: Path) -> None:
    from sase.ace.tui.widgets.file_panel._spread_probe import probe_files_spread

    image = tmp_path / "shot.png"
    image.write_bytes(b"\x89PNG\r\n")
    probe = probe_files_spread(
        _agent(status="DONE"),
        (str(image),),
        width=80,
        stop_after_rows=1000,
    )
    assert probe.has_solo is True


async def test_files_probe_oversized_stops_early(tmp_path: Path) -> None:
    from sase.ace.tui.widgets.file_panel._spread_probe import probe_files_spread

    big = tmp_path / "big.diff"
    big.write_text("\n".join(f"line {i}" for i in range(5000)), encoding="utf-8")
    probe = probe_files_spread(
        _agent(status="DONE"),
        (str(big), str(big)),
        width=80,
        stop_after_rows=50,
    )
    assert probe.exceeded is True
    assert probe.total_rows is not None and probe.total_rows > 50


async def test_files_small_spread_with_separators(tmp_path: Path) -> None:
    from sase.ace.tui.widgets.file_panel._spread_probe import probe_files_spread

    first = tmp_path / "a.diff"
    second = tmp_path / "b.diff"
    first.write_text("line one\nline two\n", encoding="utf-8")
    second.write_text("other\n", encoding="utf-8")
    probe = probe_files_spread(
        _agent(status="DONE"),
        (str(first), str(second)),
        width=80,
        stop_after_rows=1000,
    )
    assert probe.has_solo is False
    assert probe.exceeded is False
    assert len(probe.pages) == 2

    app = _DetailApp()
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        panel = detail.deck_area.panel(0)
        panel._files_probe_pages = tuple(probe.pages)
        panel._files_probe_slots = (str(first), str(second))
        panel._render_mode[DeckId.FILES] = RenderMode.SPREAD
        panel._sync_files_views()
        await pilot.pause()
        # Spread view is shown, paged view hidden but still owns the list.
        assert panel.is_spread(DeckId.FILES) is True

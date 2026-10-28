"""Files anchor ownership regressions for sase-1ou.4 (sase-1a7).

Covers the Ctrl-J page-anchor scroll race: a hidden paged restore must not
move the shared spread viewport, visible paged restores must still work,
superseding navigation owns its target, and late layout resumes pending
navigation. Uses real widgets and controlled callback ordering.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from textual.app import App, ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Static

from sase.ace.testing import wait_for
from sase.ace.tui.widgets.agent_detail import AgentDetail
from sase.ace.tui.widgets.decks.model import DeckId, RenderMode
from tests.ace.tui.widgets._agent_display_helpers import make_agent
from tests.ace.tui.widgets.decks._deck_settle import (
    describe_files_nav,
    wait_for_anchor_scroll,
)

_ROOT = Path(__file__).resolve().parents[5]


class _DetailApp(App[None]):
    CSS_PATH = _ROOT / "src/sase/ace/tui/styles.tcss"

    def compose(self) -> ComposeResult:
        yield AgentDetail(id="agent-detail-panel")


def _files_scroll_y(panel: Any) -> int:
    scroll = panel.query_one(
        "#agent-deck-panel-0-files-scroll",
        VerticalScroll,
    )
    return int(scroll.scroll_y)


def _make_two_file_agent(tmp_path: Path) -> Any:
    notes = tmp_path / "review_notes.md"
    notes.write_text("# Review Notes\n\n- First point.\n", encoding="utf-8")
    plan = tmp_path / "implementation_plan.md"
    plan.write_text(
        "# Implementation Plan\n\n"
        + "\n".join(f"{i}. Step {i}." for i in range(1, 16))
        + "\n",
        encoding="utf-8",
    )
    return make_agent(
        agent_name="pilot",
        status="DONE",
        extra_files=[str(notes), str(plan)],
    )


async def _ready_spread_panel(tmp_path: Path, pilot: Any, detail: Any) -> Any:
    panel = detail.deck_area.panel(0)
    await wait_for(pilot, lambda: panel.is_spread(DeckId.FILES))
    await wait_for(pilot, lambda: panel._files_anchor_row(1) is not None)
    await wait_for(
        pilot,
        lambda: len(getattr(panel.file_view, "_file_list", ())) > 1,
    )
    return panel


async def test_hidden_paged_restore_preserves_spread_scroll(tmp_path: Path) -> None:
    """A delayed hidden paged restore must not move an active spread scroll."""
    agent = _make_two_file_agent(tmp_path)
    app = _DetailApp()
    async with app.run_test(size=(160, 40)) as pilot:
        await pilot.pause()
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        detail.update_display(agent)
        await pilot.pause()
        detail.show_deck(0, DeckId.FILES)
        panel = await _ready_spread_panel(tmp_path, pilot, detail)
        panel.cycle_card(1)
        await wait_for_anchor_scroll(
            pilot,
            lambda: _files_scroll_y(panel),
            lambda: panel._files_anchor_row(1),
            diagnose=lambda: describe_files_nav(panel),
        )
        anchor = panel._files_anchor_row(1)
        assert anchor is not None and anchor > 0, f"anchor={anchor!r}"
        assert panel._files_body_start(1) == anchor + 1
        scroll = panel.query_one("#agent-deck-panel-0-files-scroll", VerticalScroll)
        assert int(scroll.scroll_y) == anchor, (
            f"spread did not land: scroll_y={int(scroll.scroll_y)} anchor={anchor}"
        )
        assert panel.file_view.has_class("hidden")

        # Simulate a stale hidden paged read completing after the jump:
        # seed a paged offset at the top, then run its deferred restore.
        key = panel.file_view._current_anchor_key()
        assert key is not None
        panel.file_view.seed_scroll_anchor(key, 0)
        panel.file_view._schedule_scroll_anchor_restore()
        await pilot.pause()
        await pilot.pause()

        live_anchor = panel._files_anchor_row(1)
        assert live_anchor is not None
        assert int(scroll.scroll_y) == live_anchor, (
            f"hidden paged restore clobbered spread: "
            f"scroll_y={int(scroll.scroll_y)} anchor={live_anchor}"
        )
        assert panel._files_body_start(1) == live_anchor + 1


async def test_visible_paged_restore_still_moves_viewport(tmp_path: Path) -> None:
    """Visible paged restores keep working; return to paged keeps its offset."""
    agent = _make_two_file_agent(tmp_path)
    app = _DetailApp()
    async with app.run_test(size=(160, 40)) as pilot:
        await pilot.pause()
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        detail.update_display(agent)
        await pilot.pause()
        detail.show_deck(0, DeckId.FILES)
        panel = await _ready_spread_panel(tmp_path, pilot, detail)
        panel.cycle_card(1)
        await wait_for_anchor_scroll(
            pilot,
            lambda: _files_scroll_y(panel),
            lambda: panel._files_anchor_row(1),
            diagnose=lambda: describe_files_nav(panel),
        )
        anchor = panel._files_anchor_row(1)
        assert anchor is not None and anchor > 0

        # Return to paged: the hidden guard must not stick and the paged
        # view must own its viewport again.
        panel._apply_files_transition(RenderMode.PAGED)
        await pilot.pause()
        await pilot.pause()
        assert not panel.file_view.has_class("hidden")
        paged_scroll = panel.query_one(
            "#agent-deck-panel-0-files-scroll", VerticalScroll
        )
        key = panel.file_view._current_anchor_key()
        assert key is not None
        target = min(2, int(paged_scroll.max_scroll_y))
        panel.file_view.seed_scroll_anchor(key, target)
        panel.file_view._schedule_scroll_anchor_restore()
        await pilot.pause()
        await pilot.pause()
        assert int(paged_scroll.scroll_y) == target, (
            f"visible paged restore did not apply: "
            f"scroll_y={int(paged_scroll.scroll_y)} target={target} "
            f"max={int(paged_scroll.max_scroll_y)}"
        )


async def test_superseding_navigation_owns_target_and_manual_scroll_holds(
    tmp_path: Path,
) -> None:
    """A newer Ctrl-J owns the viewport; manual scroll works after settle."""
    agent = _make_two_file_agent(tmp_path)
    app = _DetailApp()
    async with app.run_test(size=(160, 40)) as pilot:
        await pilot.pause()
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        detail.update_display(agent)
        await pilot.pause()
        detail.show_deck(0, DeckId.FILES)
        panel = await _ready_spread_panel(tmp_path, pilot, detail)
        # Two rapid navigations: the second supersedes the first.
        panel.cycle_card(1)
        panel.cycle_card(1)
        await wait_for_anchor_scroll(
            pilot,
            lambda: _files_scroll_y(panel),
            lambda: panel._files_anchor_row(0),
            diagnose=lambda: describe_files_nav(panel),
        )
        anchor0 = panel._files_anchor_row(0)
        assert anchor0 == 0
        scroll = panel.query_one("#agent-deck-panel-0-files-scroll", VerticalScroll)
        assert int(scroll.scroll_y) == 0
        # Back to page 1, then manual scroll must stick (no viewport pin).
        panel.cycle_card(1)
        await wait_for_anchor_scroll(
            pilot,
            lambda: _files_scroll_y(panel),
            lambda: panel._files_anchor_row(1),
            diagnose=lambda: describe_files_nav(panel),
        )
        anchor1 = panel._files_anchor_row(1)
        assert anchor1 is not None and anchor1 > 0
        assert int(scroll.scroll_y) == anchor1
        scroll.scroll_to(y=0, animate=False)
        await pilot.pause()
        await pilot.pause()
        assert int(scroll.scroll_y) == 0, (
            f"manual scroll did not hold after settle: "
            f"scroll_y={int(scroll.scroll_y)} anchor={anchor1}"
        )


async def test_late_layout_resumes_pending_navigation(tmp_path: Path) -> None:
    """An outstanding jump survives missing anchors until layout publishes."""
    agent = _make_two_file_agent(tmp_path)
    app = _DetailApp()
    async with app.run_test(size=(160, 40)) as pilot:
        await pilot.pause()
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        detail.update_display(agent)
        await pilot.pause()
        detail.show_deck(0, DeckId.FILES)
        panel = await _ready_spread_panel(tmp_path, pilot, detail)
        real_anchor = panel._files_anchor_row
        held: dict[str, bool] = {"hold": True}

        def _held_anchor(index: int) -> int | None:
            if held["hold"]:
                return None
            return real_anchor(index)

        panel._files_anchor_row = _held_anchor  # type: ignore[method-assign]
        try:
            panel.cycle_card(1)
            # Let a layout cycle run while anchors are withheld; the request
            # must stay pending instead of being abandoned.
            await pilot.pause()
            await pilot.pause()
            await wait_for(pilot, lambda: panel._files_pending_scroll_index == 1)
            assert panel._files_pending_scroll_index == 1
            held["hold"] = False
            # A later relevant layout publication resumes the request.
            panel.files_spread_view._publish_section_layout(
                generation=panel.files_spread_view._section_generation,
                width=panel._spread_viewport(DeckId.FILES)[1] or 80,
                anchors=tuple(panel.files_spread_view._section_anchors),
            )
            await wait_for_anchor_scroll(
                pilot,
                lambda: _files_scroll_y(panel),
                lambda: real_anchor(1),
                diagnose=lambda: describe_files_nav(panel),
            )
        finally:
            panel._files_anchor_row = real_anchor  # type: ignore[method-assign]
        anchor = real_anchor(1)
        assert anchor is not None and anchor > 0
        assert panel._files_body_start(1) == anchor + 1
        scroll = panel.query_one("#agent-deck-panel-0-files-scroll", VerticalScroll)
        assert int(scroll.scroll_y) == anchor, (
            f"late layout did not resume navigation: "
            f"scroll_y={int(scroll.scroll_y)} anchor={anchor}"
        )


async def test_stalled_navigation_resumes_on_scroll_extent_growth(
    tmp_path: Path,
) -> None:
    """An extent that grows after the retry chain runs out resumes the jump.

    Holds the Files scroll extent short of the page-1 anchor for more
    refresh hops than the bounded retry chain survives, so the pending
    navigation is still recorded but no callback remains to finish it.
    Growing the scroll extent afterwards — with no new anchor publish —
    must resume the pending navigation and land on the live anchor.
    """
    agent = _make_two_file_agent(tmp_path)
    app = _DetailApp()
    async with app.run_test(size=(160, 40)) as pilot:
        await pilot.pause()
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        panel = detail.deck_area.panel(0)
        # Hold the trailing-reserve extent off so the scroll container stays
        # short of the page-1 anchor while the retry chain runs.
        real_enable = panel.files_spread_view.enable_section_layout_reserve
        panel.files_spread_view.enable_section_layout_reserve = (  # type: ignore[method-assign]
            lambda **kwargs: False
        )
        try:
            detail.update_display(agent)
            await pilot.pause()
            detail.show_deck(0, DeckId.FILES)
            panel = await _ready_spread_panel(tmp_path, pilot, detail)
            panel.cycle_card(1)
            # Wait until the bounded chain runs out of hops while the
            # extent stays short: retries exhausted, request still pending.
            await wait_for(
                pilot,
                lambda: int(getattr(panel, "_files_scroll_retry", 0) or 0) >= 8,
            )
            anchor = panel._files_anchor_row(1)
            assert anchor is not None and anchor > 0, f"anchor={anchor!r}"
            scroll = panel.query_one("#agent-deck-panel-0-files-scroll", VerticalScroll)
            assert int(scroll.max_scroll_y) < anchor, (
                f"extent was not held short: max={int(scroll.max_scroll_y)} "
                f"anchor={anchor}"
            )
            # The chain gave up, but the request is still pending.
            assert panel._files_pending_scroll_index == 1
            assert panel._files_scroll_retry >= 8
            # The extent grows after the last layout publish, with no anchor
            # republish: the pending navigation must resume and land.
            await scroll.mount(Static("\n".join(f"filler {i}" for i in range(60))))
            await wait_for_anchor_scroll(
                pilot,
                lambda: _files_scroll_y(panel),
                lambda: panel._files_anchor_row(1),
                diagnose=lambda: describe_files_nav(panel),
            )
            anchor = panel._files_anchor_row(1)
            assert anchor is not None and anchor > 0
            assert int(scroll.scroll_y) == anchor, (
                f"extent growth did not resume navigation: "
                f"scroll_y={int(scroll.scroll_y)} anchor={anchor}"
            )
        finally:
            panel.files_spread_view.enable_section_layout_reserve = real_enable  # type: ignore[method-assign]

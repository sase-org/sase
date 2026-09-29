"""Tier, click-mapping, overflow, and status-reservation strip tests."""

from __future__ import annotations

from typing import Any

import pytest
from rich.cells import cell_len
from textual import on
from textual.app import App, ComposeResult
from textual.containers import Horizontal
from textual.widgets import Static

from sase.ace.tui.models.agent_tab_index import _index_cache
from sase.ace.tui.widgets._agent_tab_strip_overflow import (
    overflow_needs_attention,
    overflow_window,
    tier_for_width,
)
from sase.ace.tui.widgets.agent_tab_strip import (
    OVERFLOW_NEXT_ID,
    OVERFLOW_PREV_ID,
    AgentTabDescriptor,
    AgentTabStrip,
)
from sase.core.agent_tab import DEFAULT_AGENT_TAB_KEY, AgentTabKey
from tests.ace.tui._agent_tab_strip_shared import SASE, make_descriptors

__all__ = [
    "strip_plain",
    "test_compact_inactive_drops_count_and_unread_but_keeps_failed",
    "test_full_compact_micro_tier_plains",
    "test_overflow_chip_click_opens_picker_request",
    "test_overflow_chips_tint_when_hidden_tabs_need_attention",
    "test_overflow_window_is_active_centered",
    "test_status_sibling_reserves_cells_for_health_text",
    "test_tier_for_width_picks_richest_fit",
    "test_two_cell_glyph_click_ranges_are_cell_accurate",
]


@pytest.fixture(autouse=True)
def _clear_index_cache() -> Any:
    _index_cache.clear()
    yield
    _index_cache.clear()


def strip_plain(
    descriptors: tuple[AgentTabDescriptor, ...],
    active: AgentTabKey,
    tier: str,
) -> str:
    return AgentTabStrip(descriptors, active)._build_content(tier).plain


# --- tier transitions -----------------------------------------------------


def test_full_compact_micro_tier_plains() -> None:
    strip = AgentTabStrip(make_descriptors(), SASE)
    assert strip._build_content("full").plain == ("main 2 ┊ ▐ sase 12 S1 U2 ▌ │ blog 3")
    assert strip._build_content("compact").plain == ("main ┊ ▐ sase 12 S1 U2 ▌ │ blog")
    micro = strip._build_content("micro").plain
    assert micro == "mai ┊ ▐sas S1▌ │ blo"


def test_compact_inactive_drops_count_and_unread_but_keeps_failed() -> None:
    descriptors = (
        AgentTabDescriptor(
            key=DEFAULT_AGENT_TAB_KEY,
            label="main",
            accent="#AFAFAF",
            count=4,
            unread=3,
            failed=1,
            is_default=True,
        ),
        AgentTabDescriptor(key=SASE, label="sase", accent="#AF87FF", count=1),
    )
    strip = AgentTabStrip(descriptors, SASE)
    compact = strip._build_content("compact").plain
    assert "main F1" in compact
    assert "U3" not in compact
    assert " 4" not in compact.split("┊")[0]


def test_tier_for_width_picks_richest_fit() -> None:
    descriptors = make_descriptors()
    assert tier_for_width(descriptors, 200, active_key=SASE) == "full"
    full_width = len(strip_plain(descriptors, SASE, "full"))
    compact_width = len(strip_plain(descriptors, SASE, "compact"))
    assert tier_for_width(descriptors, compact_width, active_key=SASE) in (
        "full",
        "compact",
    )
    assert tier_for_width(descriptors, 1, active_key=SASE) == "micro"
    _ = full_width


# --- cell-width click mapping ---------------------------------------------


async def test_two_cell_glyph_click_ranges_are_cell_accurate() -> None:
    descriptors = (
        AgentTabDescriptor(
            key=DEFAULT_AGENT_TAB_KEY,
            label="local",
            glyph="⌨",
            accent="#5FD7FF",
            count=9,
            is_default=True,
        ),
        AgentTabDescriptor(
            key=AgentTabKey.machine("id-apollo"),
            label="apollo",
            glyph="🔥",
            accent="#5FD7FF",
            count=14,
            stopped=1,
        ),
        AgentTabDescriptor(
            key=SASE, label="sase", accent="#AF87FF", count=12, unread=2
        ),
    )

    class _StripApp(App[None]):
        selected: str | None = None

        def compose(self) -> ComposeResult:
            yield AgentTabStrip(descriptors, SASE, id="tabs")

        @on(AgentTabStrip.TabClicked)
        def _on_tab_clicked(self, event: AgentTabStrip.TabClicked) -> None:
            self.selected = event.tab_id

    async with _StripApp().run_test(size=(120, 5)) as pilot:
        strip = pilot.app.query_one("#tabs", AgentTabStrip)
        await pilot.pause()
        text = strip._build_content("full")

        assert strip._line_width == cell_len(text.plain)
        start, end = strip._tab_ranges["named:sase"]
        assert end - start == cell_len("▐ sase 12 U2 ▌")

        # Chips render left-aligned, so the click lands on raw content
        # cells with no center-pad compensation.
        await pilot.click(strip, offset=(start + 1, 0))
        await pilot.pause()
        assert pilot.app.selected == "named:sase"


# --- overflow selection ----------------------------------------------------


def test_overflow_window_is_active_centered() -> None:
    descriptors = tuple(
        AgentTabDescriptor(
            key=AgentTabKey.named(f"tab{i:02d}"),
            label=f"tab{i:02d}",
            accent="#AF87FF",
            count=i,
        )
        for i in range(7)
    )
    active = AgentTabKey.named("tab03")
    visible, before, after = overflow_window(descriptors, active, max_visible=3)
    assert [desc.label for desc in visible] == ["tab02", "tab03", "tab04"]
    assert (before, after) == (2, 2)
    first, before_first, after_first = overflow_window(
        descriptors, AgentTabKey.named("tab00"), max_visible=3
    )
    assert [desc.label for desc in first] == ["tab00", "tab01", "tab02"]
    assert (before_first, after_first) == (0, 4)


def test_overflow_chips_tint_when_hidden_tabs_need_attention() -> None:
    descriptors = (
        AgentTabDescriptor(
            key=AgentTabKey.named("a"), label="a", accent="#AF87FF", count=1
        ),
        AgentTabDescriptor(
            key=AgentTabKey.named("b"), label="b", accent="#AF87FF", count=1
        ),
        AgentTabDescriptor(
            key=AgentTabKey.named("c"),
            label="c",
            accent="#AF87FF",
            count=1,
            failed=2,
        ),
    )
    visible = (descriptors[0], descriptors[1])
    prev_need, next_need = overflow_needs_attention(descriptors, visible)
    assert (prev_need, next_need) == (False, True)
    strip = AgentTabStrip(descriptors, AgentTabKey.named("a"))
    strip._overflow_before = 0
    strip._overflow_after = 1
    strip._visible_descriptors = visible
    strip._overflow_prev_attention, strip._overflow_next_attention = (
        overflow_needs_attention(descriptors, visible)
    )
    assert strip._overflow_next_attention is True


async def test_overflow_chip_click_opens_picker_request() -> None:
    descriptors = tuple(
        AgentTabDescriptor(
            key=AgentTabKey.named(f"tab{i:02d}"),
            label=f"tab{i:02d} much longer name {i}",
            accent="#AF87FF",
            count=i,
        )
        for i in range(6)
    )

    class _OverflowApp(App[None]):
        requested: str | None = None

        def compose(self) -> ComposeResult:
            yield AgentTabStrip(descriptors, AgentTabKey.named("tab02"), id="tabs")

        @on(AgentTabStrip.PickerRequested)
        def _on_picker(self, event: AgentTabStrip.PickerRequested) -> None:
            self.requested = event.direction

    async with _OverflowApp().run_test(size=(30, 5)) as pilot:
        strip = pilot.app.query_one("#tabs", AgentTabStrip)
        await pilot.pause()
        assert (
            OVERFLOW_PREV_ID in strip._tab_ranges
            or OVERFLOW_NEXT_ID in strip._tab_ranges
        )
        chip_id = (
            OVERFLOW_NEXT_ID
            if OVERFLOW_NEXT_ID in strip._tab_ranges
            else OVERFLOW_PREV_ID
        )
        start, end = strip._tab_ranges[chip_id]
        await pilot.click(strip, offset=(start, 0))
        await pilot.pause()
        assert pilot.app.requested in ("prev", "next")


# --- status reservation ------------------------------------------------------


async def test_status_sibling_reserves_cells_for_health_text() -> None:
    class _HeaderApp(App[None]):
        def compose(self) -> ComposeResult:
            with Horizontal():
                yield AgentTabStrip(make_descriptors(), SASE, id="tabs")
                yield Static("", id="agents-fleet-status")

    async with _HeaderApp().run_test(size=(120, 5)) as pilot:
        strip = pilot.app.query_one("#tabs", AgentTabStrip)
        await pilot.pause()
        assert strip._status_reserved_width() == 0
        pilot.app.query_one("#agents-fleet-status", Static).update(
            "apollo: stale · cached 2m ago"
        )
        await pilot.pause()
        assert (
            strip._status_reserved_width()
            == cell_len("apollo: stale · cached 2m ago") + 2
        )

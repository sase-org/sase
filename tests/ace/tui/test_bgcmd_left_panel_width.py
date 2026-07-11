"""Width clamps for the AXE-tab left sidebar (#bgcmd-list-container).

Pins the Phase 1 contract from sdd/plans/202605/axe_tab_visual_redesign.md:
``BgCmdList.WidthChanged`` events resize the sidebar container, clamp to
the configured min/max, and never starve the right-hand AXE dashboard on
narrow terminals.
"""

from __future__ import annotations

from typing import Any

from sase.ace.tui.actions.event_handlers import EventHandlersMixin
from sase.ace.tui.app import (
    _BGCMD_LIST_RESERVED_FOR_DASHBOARD,
    _MAX_BGCMD_LIST_WIDTH,
    _MIN_BGCMD_LIST_WIDTH,
)
from sase.ace.tui.widgets.bgcmd_list import BgCmdList


class _Styles:
    def __init__(self) -> None:
        self.width: int | None = None


class _Container:
    def __init__(self) -> None:
        self.styles = _Styles()


class _Size:
    def __init__(self, width: int) -> None:
        self.width = width


class _FakeApp(EventHandlersMixin):
    def __init__(self, terminal_width: int = 200) -> None:
        self.container = _Container()
        self.size = _Size(terminal_width)

    def query_one(self, selector: str, _type: Any = None) -> _Container:
        assert selector == "#bgcmd-list-container"
        return self.container


def test_width_event_clamps_below_min() -> None:
    app = _FakeApp()
    app.on_bg_cmd_list_width_changed(BgCmdList.WidthChanged(10))
    assert app.container.styles.width == _MIN_BGCMD_LIST_WIDTH


def test_width_event_clamps_above_max() -> None:
    app = _FakeApp(terminal_width=500)
    app.on_bg_cmd_list_width_changed(BgCmdList.WidthChanged(_MAX_BGCMD_LIST_WIDTH + 50))
    assert app.container.styles.width == _MAX_BGCMD_LIST_WIDTH


def test_width_event_fits_natural_width() -> None:
    app = _FakeApp(terminal_width=200)
    natural = _MIN_BGCMD_LIST_WIDTH + 12
    app.on_bg_cmd_list_width_changed(BgCmdList.WidthChanged(natural))
    assert app.container.styles.width == natural


def test_width_event_clamps_to_terminal_when_dashboard_would_be_starved() -> None:
    # 80-cell terminal: must leave _BGCMD_LIST_RESERVED_FOR_DASHBOARD cells
    # for the AXE dashboard, so the sidebar caps at 80 - reserved.
    terminal_width = 80
    expected_cap = terminal_width - _BGCMD_LIST_RESERVED_FOR_DASHBOARD
    app = _FakeApp(terminal_width=terminal_width)
    app.on_bg_cmd_list_width_changed(BgCmdList.WidthChanged(75))
    assert app.container.styles.width == expected_cap


def test_width_event_keeps_min_on_tiny_terminal() -> None:
    # Pathologically narrow terminal: the min still wins so the panel
    # never collapses to zero cells.
    app = _FakeApp(terminal_width=20)
    app.on_bg_cmd_list_width_changed(BgCmdList.WidthChanged(60))
    assert app.container.styles.width == _MIN_BGCMD_LIST_WIDTH

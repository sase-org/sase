"""Shared helpers for three-pane ``SasePager`` tests."""

from __future__ import annotations

from typing import Any

from textual.containers import Vertical
from textual.widgets import Static

from sase.ace.tui.util.pane_grid import _Geometry, _geometry
from sase.pager.app import SasePager
from sase.pager.view import PagerView

from ._app_helpers import pager_screen


def footer_text(app: SasePager) -> str:
    footer = pager_screen(app).query_one("#pager-footer", Static)
    visual = getattr(footer, "visual", None)
    if visual is not None:
        return str(visual.plain)
    content = getattr(footer, "_content", "")
    return str(getattr(content, "plain", content))


def panes_container(app: SasePager) -> Vertical:
    return pager_screen(app).query_one("#pager-panes", Vertical)


def mounted_views(app: SasePager) -> list[PagerView]:
    return list(pager_screen(app).query(PagerView))


async def nest_main_top(pilot: Any, app: SasePager) -> Any:
    """Drive ``\\`` then ``|`` to an R3 main-top grid; return the screen."""
    screen = pager_screen(app)
    await pilot.press("\\")
    await pilot.pause()
    await pilot.pause()
    assert len(screen.views) == 2
    await pilot.press("|")
    await pilot.pause()
    await pilot.pause()
    assert len(screen.views) == 3
    assert _geometry(screen._grid) is _Geometry.R3_MAIN_TOP
    return screen

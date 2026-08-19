"""Fast seam check for the Plugins scale-catalog fixture.

The slow bench times this path at 10/250/1000/2000. This test only opens
the smallest catalog so ``just check`` still exercises the stub seams.
"""

from __future__ import annotations

import pytest
from textual.widgets import Input

from sase.ace.testing import AcePage
from tests.ace.tui._plugins_browser_pane_helpers import (
    _open_plugins_pane,
    _patch_catalog,
    _patch_other_panes,
    _uv_tool,
)
from tests.perf.plugin_catalog_scale import (
    FILTER_KEYSTROKE,
    make_scale_catalog,
    scale_filter_match_count,
)


async def test_scale_catalog_fixture_filters_and_marks_at_n10(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog = make_scale_catalog(10)
    _patch_other_panes(monkeypatch)
    _patch_catalog(monkeypatch, catalog=catalog, uv_tool=_uv_tool())

    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        assert pane._catalog is not None
        assert len(pane._catalog.entries) == 10

        filter_input = pane.query_one("#plugins-filter-input", Input)
        pane.on_input_changed(Input.Changed(filter_input, FILTER_KEYSTROKE))
        matched = sum(len(entries) for _, _, entries in pane._grouped)
        assert matched == scale_filter_match_count(10) == 10

        pane.action_toggle_install_mark()
        assert len(pane._marked_install) == 1

        pane.action_jump_to_entry()
        assert pane.jump_mode_active is True
        pane.exit_jump_mode()
        assert pane.jump_mode_active is False

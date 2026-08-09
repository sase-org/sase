"""Regression tests for PatchList one-line option rendering."""

from __future__ import annotations

from pathlib import Path

import pytest
from textual.app import App, ComposeResult
from textual.containers import Container

from sase.ace.patch import Patch
from sase.ace.tui.models.patch_groups import PatchGroupingMode
from sase.ace.tui.widgets import PatchList


_ROOT = Path(__file__).resolve().parents[4]


def _cs(name: str, *, status: str = "WIP") -> Patch:
    return Patch(
        name=name,
        description="",
        parent=None,
        cl="https://example.invalid/reviews/1234567890",
        status=status,
        file_path="/tmp/long-project-name/project.sase",
        line_number=1,
    )


class _NarrowPatchListApp(App[None]):
    """Mount PatchList with the production stylesheet."""

    CSS_PATH = _ROOT / "src/sase/ace/tui/styles.tcss"
    CSS = """
    #harness {
        width: 28;
        height: 12;
    }

    #patch-list {
        width: 100%;
        height: 100%;
    }
    """

    def compose(self) -> ComposeResult:
        with Container(id="harness"):
            yield PatchList(id="patch-list")


@pytest.mark.asyncio
async def test_patch_list_options_stay_single_line_when_narrow() -> None:
    """Textual's OptionList line cache should assign one visual row per option."""
    app = _NarrowPatchListApp()
    async with app.run_test(size=(36, 16)) as pilot:
        widget = app.query_one(PatchList)
        widget.update_list(
            [
                _cs("very-long-patch-name-alpha"),
                _cs("very-long-patch-name-beta"),
            ],
            current_idx=0,
            grouping_mode=PatchGroupingMode.BY_STATUS,
        )
        await pilot.pause()

        widget._line_cache.clear()
        widget._update_lines()

        assert widget.styles.text_wrap == "nowrap"
        assert widget.styles.text_overflow == "clip"
        assert widget.option_count > 0
        assert set(widget._line_cache.heights.values()) == {1}
        assert len(widget._line_cache.lines) == widget.option_count

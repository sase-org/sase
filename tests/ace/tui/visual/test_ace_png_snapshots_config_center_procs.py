"""ACE TUI PNG visual snapshot coverage for the Admin Center Tasks tab."""

from __future__ import annotations

import pytest
from textual.widgets import OptionList, Static

from sase.ace.testing import AcePage
from sase.ace.tui.modals.procs_filter_bar import ProcsFilterBar
from sase.ace.tui.modals.procs_pane import ProcsPane
from sase.ace.tui.proc_observer import ObservedProc
from sase.monitor_state import MONITOR_GLYPH
from tests.ace.tui.visual._ace_config_center_png_snapshot_helpers import (
    _FIXED_TASK_NOW,
    _freeze_procs_clock,
    _open_procs_modal,
    _patch_config_view,
    _patch_plugins_catalog,
    _patch_xprompt_sources,
    _seed_tasks_tab_queue,
)
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


def _detached_nightly_row() -> ObservedProc:
    return ObservedProc(
        proc_id="detached123",
        proc_type="detached",
        cl_name="",
        project_file="",
        status="running",
        message="",
        started_at=_FIXED_TASK_NOW.replace(tzinfo=None),
        display_name="Epic · nightly",
        output="worker: creating beads\n",
        command=["sase", "bead", "work", "nightly.md", "--yes-to-all"],
        durable_proc_id="detached123",
        store_backed=True,
    )


def _option_plain(option_list: OptionList, index: int) -> str:
    return option_list.get_option_at_index(index).prompt.plain


def _row_index_containing(option_list: OptionList, needle: str) -> int:
    for index in range(option_list.option_count):
        if needle in _option_plain(option_list, index):
            return index
    raise AssertionError(f"no proc row contained {needle!r}")


async def _open_seeded_procs_tab(page: AcePage) -> ProcsPane:
    await page.press(page.artifacts_digit("patches"))
    await page.expect_state("artifacts_subtab", "patches")
    _seed_tasks_tab_queue(page.app, extra_rows=(_detached_nightly_row(),))
    _, pane = await _open_procs_modal(page)
    return pane


async def test_config_center_procs_tab_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    _patch_xprompt_sources(monkeypatch)
    _patch_plugins_catalog(monkeypatch)
    _patch_config_view(monkeypatch, None)
    _freeze_procs_clock(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        pane = await _open_seeded_procs_tab(page)
        option_list = pane.query_one("#procs-list", OptionList)
        output = pane.query_one("#procs-output-content", Static)
        title = pane._title_text().plain
        assert "sync sase-42" in _option_plain(option_list, 0)
        assert any(
            "◆ detached" in _option_plain(option_list, index)
            for index in range(option_list.option_count)
        )
        monitor_index = _row_index_containing(option_list, "just check-full")
        assert MONITOR_GLYPH in _option_plain(option_list, monitor_index)
        assert "acme--mon" in _option_plain(option_list, monitor_index)
        finished_index = _row_index_containing(option_list, "pytest -x")
        assert MONITOR_GLYPH in _option_plain(option_list, finished_index)
        assert "hotfix--mon-0" in _option_plain(option_list, finished_index)
        assert "remote: Enumerating objects" in output.render().plain
        assert "⚙ 3" in title
        assert "⚙ 1" in title
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "config_center_procs_tab_120x40",
            title="ACE SASE Admin Center - Procs tab",
        )


@pytest.mark.parametrize(
    ("size", "snapshot_name"),
    [
        ((120, 40), "config_center_procs_tab_monitors_120x40"),
        ((90, 40), "config_center_procs_tab_monitors_90x40"),
    ],
)
async def test_config_center_procs_tab_monitors_png_snapshot(
    size: tuple[int, int],
    snapshot_name: str,
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    _patch_xprompt_sources(monkeypatch)
    _patch_plugins_catalog(monkeypatch)
    _patch_config_view(monkeypatch, None)
    _freeze_procs_clock(monkeypatch)

    async with AcePage(query='"visual"', patches=patches(), size=size) as page:
        await wait_for_startup(page)
        pane = await _open_seeded_procs_tab(page)
        option_list = pane.query_one("#procs-list", OptionList)
        monitor_index = _row_index_containing(option_list, "just check-full")
        pane._rebuild_list(highlight_index=monitor_index)
        output = pane.query_one("#procs-output-content", Static)
        title = pane._title_text().plain
        hints = pane.query_one("#procs-hints", Static)
        assert f"{MONITOR_GLYPH} just check-full" in _option_plain(
            option_list, monitor_index
        )
        assert "acme--mon" in _option_plain(option_list, monitor_index)
        assert MONITOR_GLYPH in _option_plain(
            option_list, _row_index_containing(option_list, "pytest -x")
        )
        assert "agent  acme--mon" in output.render().plain
        assert "ruff .................. Passed" in output.render().plain
        assert "pytest tests/ace" in output.render().plain
        assert "⚙ 3" in title
        assert "⚙ 1" in title
        assert "⏎: agent" in hints.render().plain
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            snapshot_name,
            title="ACE SASE Admin Center - Procs tab monitors",
        )


async def test_config_center_procs_tab_filtered_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The teal filter bar, its highlighted closed display, and `N/M shown`."""
    patch_startup_loaders(monkeypatch)
    _patch_xprompt_sources(monkeypatch)
    _patch_plugins_catalog(monkeypatch)
    _patch_config_view(monkeypatch, None)
    _freeze_procs_clock(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        pane = await _open_seeded_procs_tab(page)
        bar = pane.query_one(ProcsFilterBar)
        display = bar.query_one(f"#{bar.DISPLAY_ID}", Static)

        await page.press("/")
        bar.set_query("monitor")
        bar.post_message(ProcsFilterBar.Submitted("monitor"))
        await page.wait_for(
            lambda _state: (
                not bar._editing  # noqa: SLF001
                and display.render().plain == "monitor"
            )
        )
        await wait_for_visual_idle(page)

        option_list = pane.query_one("#procs-list", OptionList)
        await page.wait_for(
            lambda _state: (
                option_list.option_count > 0
                and all(
                    MONITOR_GLYPH in _option_plain(option_list, index)
                    for index in range(option_list.option_count)
                )
                and "shown" in pane._title_text().plain
            )
        )
        title = pane._title_text().plain
        assert all(
            MONITOR_GLYPH in _option_plain(option_list, index)
            for index in range(option_list.option_count)
        )
        assert "shown" in title

        ace_png_visual.assert_page_png(
            page,
            "config_center_procs_tab_filtered_120x40",
            title="ACE SASE Admin Center - Procs tab filtered",
        )

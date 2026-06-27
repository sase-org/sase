"""ACE TUI PNG visual snapshot coverage for Operations / Tasks."""

from __future__ import annotations

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.modals import tasks_pane as tp
from sase.ace.tui.task_queue import TaskQueue
from textual.widgets import OptionList, Static
from tests.ace.tui.visual._ace_config_center_png_snapshot_helpers import (
    BROAD_SCREENSHOT_MAX_DIFF_RATIO,
    _FIXED_TASK_NOW,
    _open_tasks_modal,
    _patch_config_view,
    _patch_plugins_catalog,
    _patch_xprompt_sources,
    _seed_tasks_tab_queue,
)
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    changespecs,
    patch_startup_loaders,
    wait_for_startup,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


async def test_config_center_tasks_tab_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    _patch_xprompt_sources(monkeypatch)
    _patch_plugins_catalog(monkeypatch)
    _patch_config_view(monkeypatch, None)
    original_relative_time = tp._relative_time
    monkeypatch.setattr(
        tp,
        "_relative_time",
        lambda dt: original_relative_time(dt, now=_FIXED_TASK_NOW),
    )
    monkeypatch.setattr(TaskQueue, "prune_old", lambda self: None)

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        _seed_tasks_tab_queue(page.app)
        _, pane = await _open_tasks_modal(page)
        option_list = pane.query_one("#tasks-list", OptionList)
        output = pane.query_one("#tasks-output-content", Static)
        assert "sync sase-42" in option_list.get_option_at_index(0).prompt.plain
        assert "remote: Enumerating objects" in output.render().plain

        ace_png_visual.assert_page_png(
            page,
            "config_center_operations_tasks_120x40",
            title="ACE SASE Admin Center - Operations / Tasks",
            max_diff_ratio=BROAD_SCREENSHOT_MAX_DIFF_RATIO,
        )

"""ACE TUI PNG visual snapshot coverage for the Admin Center Tasks tab."""

from __future__ import annotations

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.modals import procs_pane as tp
from sase.ace.tui.modals import procs_pane_render as tpr
from sase.ace.tui.modals.procs_store_rows import _store_task_row
from sase.ace.tui.proc_queue import ProcQueue
from sase.procs import Proc
from textual.widgets import OptionList, Static
from tests.ace.tui.visual._ace_config_center_png_snapshot_helpers import (
    _FIXED_TASK_NOW,
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


async def test_config_center_procs_tab_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    _patch_xprompt_sources(monkeypatch)
    _patch_plugins_catalog(monkeypatch)
    _patch_config_view(monkeypatch, None)
    original_relative_time = tpr._relative_time
    monkeypatch.setattr(
        tpr,
        "_relative_time",
        lambda dt: original_relative_time(dt, now=_FIXED_TASK_NOW),
    )
    original_elapsed = tpr._elapsed
    monkeypatch.setattr(
        tpr,
        "_elapsed",
        lambda task, *, now=None: original_elapsed(
            task,
            now=_FIXED_TASK_NOW.replace(tzinfo=None),
        ),
    )
    # Freeze the running-task spinner so the status token is byte-stable; the
    # 0.25s refresh timer would otherwise advance it between runs.
    monkeypatch.setattr(tpr, "_SPINNER_FRAMES", ("|",))
    detached = _store_task_row(
        Proc(
            proc_id="detached123",
            label="Epic · nightly",
            kind="detached",
            status="running",
            command=["sase", "bead", "work", "nightly.md", "--yes-to-all"],
            cwd="/repo",
            origin="telegram",
            created_at="2026-06-26T11:59:56Z",
            started_at="2026-06-26T11:59:56Z",
            log_path="/tmp/detached123.log",
        )
    )
    # Keep the real durable store out of the frame while retaining one fixed
    # detached row so its global marker has PNG coverage.
    monkeypatch.setattr(
        tp,
        "load_store_task_rows",
        lambda **_kwargs: tp.StoreTasksSnapshot(rows=[detached], mtime=1.0),
    )
    monkeypatch.setattr(ProcQueue, "prune_old", lambda self: None)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("2")
        await page.expect_state("artifacts_subtab", "patches")
        _seed_tasks_tab_queue(page.app)
        _, pane = await _open_procs_modal(page)
        option_list = pane.query_one("#procs-list", OptionList)
        output = pane.query_one("#procs-output-content", Static)
        assert "sync sase-42" in option_list.get_option_at_index(0).prompt.plain
        assert any(
            "◆ detached" in option_list.get_option_at_index(index).prompt.plain
            for index in range(option_list.option_count)
        )
        assert "remote: Enumerating objects" in output.render().plain
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "config_center_procs_tab_120x40",
            title="ACE SASE Admin Center - Procs tab",
        )

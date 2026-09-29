"""ACE PNG snapshots for ToolRun overlays (epic sase-1bt, cutover).

Every surface reads deterministic fixtures through one loader seam each
for glance, node summaries, and run detail, with pinned clocks and no
SQLite. Generation is not approval: inspect every new PNG.
"""

from __future__ import annotations

import pytest

from sase.ace.testing import AcePage
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_svg_contains,
    wait_for_visual_idle,
)
from tests.ace.tui.visual._ace_tool_runs_png_snapshot_shared import pin_tool_run_clocks
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


async def test_tool_runs_notification_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.ace.tui.modals.notification_modal import NotificationModal
    from sase.notifications.models import Notification

    pin_tool_run_clocks(monkeypatch)
    patch_startup_loaders(monkeypatch, agents=[])
    monkeypatch.setattr(
        "sase.ace.tui.modals.notification_modal_options.format_relative_time",
        lambda _timestamp: "4m ago",
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.notification_modal_sent_at.format_relative_time",
        lambda _timestamp: "4m ago",
    )
    run_id = "6c3d5107" + "0" * 24
    modal = NotificationModal(
        [
            Notification(
                id="visual-tool-run-settled",
                timestamp="2026-07-28T12:03:00+00:00",
                sender="tool-run",
                notes=[
                    "Tool run check failed (exit 1)",
                    "cause: failed",
                    f"sase tool show {run_id}",
                ],
                tags=["tool-run"],
                action="OpenToolRun",
                action_data={
                    "run_id": run_id,
                    "command": f"sase tool show {run_id}",
                },
            )
        ]
    )

    async with AcePage(query='"visual"', size=(120, 40), patches=patches()) as page:
        await wait_for_startup(page)
        page.app.push_screen(modal)
        await page.expect_modal("NotificationModal")
        await wait_for_svg_contains(page, "⚒")
        await wait_for_visual_idle(page)
        ace_png_visual.assert_page_png(
            page,
            "tool_runs_notification_120x40",
            title="ACE tool run settlement notification",
        )


async def test_tool_runs_procs_marker_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.ace.tui.proc_observer import ObservedProc
    from tests.ace.tui.visual._ace_config_center_png_snapshot_helpers import (
        _FIXED_TASK_NOW,
        _freeze_procs_clock,
        _open_procs_modal,
        _seed_tasks_tab_queue,
    )

    pin_tool_run_clocks(monkeypatch)
    patch_startup_loaders(monkeypatch)
    _freeze_procs_clock(monkeypatch)
    run_id = "6c3d5107" + "0" * 24

    async with AcePage(query='"visual"', patches=patches(), size=(120, 40)) as page:
        await wait_for_startup(page)
        _seed_tasks_tab_queue(
            page.app,
            extra_rows=(
                ObservedProc(
                    proc_id="handoff-check",
                    proc_type="tool",
                    cl_name="",
                    project_file="",
                    status="running",
                    message="sase tool run check",
                    started_at=_FIXED_TASK_NOW.replace(tzinfo=None),
                    display_name="tool:check",
                    output="",
                    command=["sase", "tool", "run", "check"],
                    tags=["tool-run", f"tool-run:{run_id}"],
                ),
            ),
        )
        await _open_procs_modal(page)
        await page.press("end")
        await wait_for_svg_contains(page, "tool:check")
        await wait_for_visual_idle(page)
        ace_png_visual.assert_page_png(
            page, "tool_runs_procs_marker_120x40", title="ACE tool run procs marker"
        )

"""ACE TUI PNG visual snapshot coverage for the ``,L`` Log panel."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.modals.log_modal import LogModal
from sase.logs import (
    events_log_path,
    launch_failures_log_path,
    runs_log_path,
    tui_log_path,
)
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    changespecs,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual

BROAD_SCREENSHOT_MAX_DIFF_RATIO = 0.03
_FIXED_MTIME = int(datetime(2026, 6, 17, 14, 30, tzinfo=UTC).timestamp())


def _write_log(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    os.utime(path, (_FIXED_MTIME, _FIXED_MTIME))


def _seed_log_panel_files() -> None:
    _write_log(
        launch_failures_log_path(),
        "\n".join(
            [
                "=" * 72,
                "[2026-06-17 14:30:00 UTC] fanout launch failure: visual-auth",
                "  kind: fanout",
                "  project: sase",
                "  workspace: 11",
                "  error: RuntimeError: provider exited before writing metadata",
                "",
                "  traceback:",
                (
                    '    File "src/sase/ace/tui/actions/agent_workflow/'
                    '_launch_tasks.py", line 89, in _finish'
                ),
                "      raise RuntimeError('provider exited before writing metadata')",
                "    RuntimeError: provider exited before writing metadata",
                "",
                "  prompt preview:",
                "    Build the log panel visual snapshot and verify it is readable.",
            ]
        )
        + "\n",
    )
    _write_log(
        tui_log_path(),
        "\n".join(
            [
                "2026-06-17 14:28:00 WARNING sase.ace.tui: retrying stale launch task",
                (
                    "2026-06-17 14:30:00 ERROR sase.ace.tui: launch failed; "
                    "wrote launch_failures.log"
                ),
            ]
        )
        + "\n",
    )
    _write_log(
        runs_log_path(),
        "\n".join(
            [
                json.dumps(
                    {
                        "timestamp": "260617_142700",
                        "event": "agent_run",
                        "workflow": "visual",
                        "project": "sase",
                        "workspace_num": 11,
                        "status": "FAILED",
                    }
                ),
                json.dumps(
                    {
                        "timestamp": "260617_143000",
                        "event": "agent_run",
                        "workflow": "visual",
                        "project": "sase",
                        "workspace_num": 11,
                        "status": "DONE",
                    }
                ),
            ]
        )
        + "\n",
    )
    _write_log(
        events_log_path(),
        json.dumps(
            {
                "timestamp": "260617_143000",
                "event": "agent_revive_failed",
                "project": "sase",
                "name": "visual-auth",
                "outcome": "failure",
            }
        )
        + "\n",
    )


async def test_log_panel_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    _seed_log_panel_files()

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        modal = LogModal()
        page.app.push_screen(modal)
        await page.expect_modal("LogModal")
        await wait_for_visual_idle(page)
        assert "Launch & Fan-out Failures" in modal._last_detail_text.plain
        assert (
            "provider exited before writing metadata" in modal._last_detail_text.plain
        )

        ace_png_visual.assert_page_png(
            page,
            "log_panel_120x40",
            title="ACE ,L Log panel",
            max_diff_ratio=BROAD_SCREENSHOT_MAX_DIFF_RATIO,
        )

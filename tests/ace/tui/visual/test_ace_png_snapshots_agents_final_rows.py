"""sase's TUI PNG visual snapshots for FINAL glance row states."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.models.agent import Agent
from tests.ace.tui.visual._ace_agents_final_png_snapshot_shared import (
    T0_TS,
    goto_agents,
    make_agent,
    pin_visual_time,
)
from tests.ace.tui.visual._ace_agents_png_snapshot_helpers import (
    assert_page_svg_contains,
)
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    patch_startup_loaders,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


def _row_agents(tmp_path: Path) -> list[Agent]:
    """Five glance rows: FINALIZING, failed, deferred, interrupted, silence."""
    executing = {
        "schema_version": 1,
        "phase": "executing",
        "instances": [
            {
                "id": "commit",
                "status": "running",
                "attempt": 1,
                "max_attempts": 1,
                "op": "stitch main",
                "step": "just fix",
                "started_at": T0_TS + 10,
            }
        ],
    }
    failed = {
        "schema_version": 1,
        "phase": "settled",
        "status": "failed",
        "instances": [{"id": "check", "status": "failed"}],
    }
    deferred = {
        "schema_version": 1,
        "phase": "settled",
        "status": "deferred",
        "instances": [{"id": "commit", "status": "deferred"}],
    }
    interrupted = {
        "schema_version": 1,
        "phase": "executing",
        "instances": [{"id": "commit", "status": "running"}],
    }
    success = {
        "schema_version": 1,
        "phase": "settled",
        "status": "success",
        "instances": [{"id": "commit", "status": "success"}],
    }
    return [
        make_agent(
            tmp_path, name="finalizing", suffix="a", status="RUNNING", summary=executing
        ),
        make_agent(
            tmp_path, name="failed", suffix="b", status="FAILED", summary=failed
        ),
        make_agent(
            tmp_path, name="deferred", suffix="c", status="DONE", summary=deferred
        ),
        make_agent(
            tmp_path, name="killed", suffix="d", status="FAILED", summary=interrupted
        ),
        make_agent(tmp_path, name="landed", suffix="e", status="DONE", summary=success),
    ]


@pytest.mark.parametrize(
    ("width", "snapshot_name"),
    [
        (120, "agents_final_rows_120x40"),
        (80, "agents_final_rows_80x40"),
        (60, "agents_final_rows_60x40"),
    ],
)
async def test_agents_final_row_states_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    width: int,
    snapshot_name: str,
) -> None:
    pin_visual_time(monkeypatch)
    patch_startup_loaders(monkeypatch, agents=_row_agents(tmp_path))
    async with AcePage(query='"visual"', size=(width, 40), patches=patches()) as page:
        await goto_agents(page, 5)
        assert_page_svg_contains(page, "FINALIZING")
        assert_page_svg_contains(page, "⊛")
        ace_png_visual.assert_page_png(
            page,
            snapshot_name,
            title="ACE agents FINAL glance row states",
        )

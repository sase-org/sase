"""sase's TUI PNG visual snapshots for FINAL Reply receipts."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.widgets import AgentDetail
from tests.ace.tui.visual._ace_agents_final_png_snapshot_shared import (
    T0_TS,
    goto_agents,
    make_agent,
    pin_visual_time,
)
from tests.ace.tui.visual._ace_agents_png_snapshot_helpers import (
    assert_page_svg_styled_text_contains,
)
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    patch_startup_loaders,
    wait_for_state,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


async def _receipt_page(page: AcePage) -> None:
    await goto_agents(page, 1)
    detail = page.app.query_one("#agent-detail-panel", AgentDetail)
    await wait_for_state(
        page,
        lambda: set(detail._main_deck_document.card_ids) == {"context", "reply"},
        description="Main deck has Context and Reply cards",
    )
    await wait_for_visual_idle(page)


async def test_agents_final_receipt_running_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    pin_visual_time(monkeypatch)
    agent = make_agent(
        tmp_path,
        name="running",
        suffix="receipt-run",
        status="RUNNING",
        summary={
            "schema_version": 1,
            "phase": "executing",
            "started_at": T0_TS,
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
        },
    )
    patch_startup_loaders(monkeypatch, agents=[agent])
    async with AcePage(query='"visual"', patches=patches()) as page:
        await _receipt_page(page)
        assert_page_svg_styled_text_contains(page, "⊛ FINAL")
        ace_png_visual.assert_page_png(
            page,
            "agents_final_receipt_running_120x40",
            title="ACE agents FINAL running Reply receipt",
        )


async def test_agents_final_receipt_failed_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    pin_visual_time(monkeypatch)
    agent = make_agent(
        tmp_path,
        name="failed",
        suffix="receipt-fail",
        status="FAILED",
        summary={
            "schema_version": 1,
            "phase": "settled",
            "status": "failed",
            "started_at": T0_TS,
            "instances": [
                {
                    "id": "check",
                    "status": "failed",
                    "attempt": 2,
                    "max_attempts": 2,
                    "reason": "command_failed",
                    "started_at": T0_TS + 50,
                    "finished_at": T0_TS + 81,
                }
            ],
        },
    )
    patch_startup_loaders(monkeypatch, agents=[agent])
    async with AcePage(query='"visual"', patches=patches()) as page:
        await _receipt_page(page)
        assert_page_svg_styled_text_contains(page, "command_failed")
        ace_png_visual.assert_page_png(
            page,
            "agents_final_receipt_failed_120x40",
            title="ACE agents FINAL failed Reply receipt",
        )


async def test_agents_final_receipt_deferred_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    pin_visual_time(monkeypatch)
    agent = make_agent(
        tmp_path,
        name="deferred",
        suffix="receipt-defer",
        status="DONE",
        summary={
            "schema_version": 1,
            "phase": "settled",
            "status": "deferred",
            "started_at": T0_TS,
            "instances": [
                {
                    "id": "commit",
                    "status": "deferred",
                    "reason": "no_diff",
                    "started_at": T0_TS + 10,
                    "finished_at": T0_TS + 12,
                },
                {"id": "lint", "status": "not_triggered"},
            ],
        },
    )
    patch_startup_loaders(monkeypatch, agents=[agent])
    async with AcePage(query='"visual"', patches=patches()) as page:
        await _receipt_page(page)
        assert_page_svg_styled_text_contains(page, "not triggered")
        ace_png_visual.assert_page_png(
            page,
            "agents_final_receipt_deferred_120x40",
            title="ACE agents FINAL deferred Reply receipt",
        )

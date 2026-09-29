"""sase's TUI PNG visual snapshots for FINAL sessions, splits, and tiers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.models.agent import Agent
from sase.ace.tui.widgets import AgentDetail
from sase.ace.tui.widgets.decks.model import DeckId
from tests.ace.tui.visual._ace_agents_final_png_snapshot_shared import (
    T0_TS,
    deck_summary,
    goto_agents,
    make_agent,
    make_decl,
    node_failed_check,
    node_single_commit,
    patch_final_view,
    pin_visual_time,
    show_final,
)
from tests.ace.tui.visual._ace_agents_png_snapshot_helpers import (
    assert_page_svg_contains,
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


def _node_session() -> dict[str, Any]:
    """A handoff-skipped plan, a failed code run, and a clean monitor run."""
    code_run = node_failed_check()["runs"][0]
    code_run["run_id"] = "run-code"
    code_run["number"] = 1
    code_run["label"] = "--code"
    commit_item = {
        "instance_id": "commit",
        "status": "success",
        "provider_ref": "builtin@commit",
        "selection_reason": "default",
        "attempt": 1,
        "max_attempts": 1,
        "op": "stitch main",
        "headline": {
            "evidence_type": "commit",
            "label": "commit",
            "value": "8bb7e55",
            "display": "commit 8bb7e55",
        },
        "attempts": [
            {
                "attempt": 1,
                "status": "success",
                "started_at": T0_TS + 10,
                "duration_seconds": 12.3,
            }
        ],
        "operations": [],
        "evidence": [],
    }
    code_run["instances"] = [commit_item, *code_run["instances"]]
    mon_run = {
        "run_id": "run-mon",
        "number": 2,
        "label": "--mon",
        "kind": "monitor",
        "disposition": "ran",
        "cycles": 1,
        "plan_digest": "def456",
        "result_status": "success",
        "declarations": [make_decl("accepted", 200, payload_count=1)],
        "drift": [],
        "diagnostics": [],
        "instances": [
            {
                "instance_id": "commit",
                "status": "success",
                "provider_ref": "builtin@commit",
                "selection_reason": "default",
                "attempt": 1,
                "max_attempts": 1,
                "op": "stitch main",
                "headline": {
                    "evidence_type": "commit",
                    "label": "commit",
                    "value": "9cc8f66",
                    "display": "commit 9cc8f66",
                },
                "attempts": [
                    {
                        "attempt": 1,
                        "status": "success",
                        "started_at": T0_TS + 210,
                        "duration_seconds": 8.0,
                    }
                ],
                "operations": [],
                "evidence": [],
            }
        ],
    }
    plan_run = {
        "run_id": "run-plan",
        "number": 0,
        "label": "--plan",
        "kind": "agent",
        "disposition": "skipped",
        "cycles": 0,
        "reason": "handoff:plan",
        "declarations": [],
        "drift": [],
        "diagnostics": [],
        "instances": [],
    }
    return {
        "schema_version": 1,
        "status": "failed",
        "glyph": "✗",
        "run_level_trouble": True,
        "attention_instance_id": "check",
        "instances": [
            {
                "instance_id": "commit",
                "selection_reason": "default",
                "status": "success",
                "provider_ref": "builtin@commit",
            },
            {
                "instance_id": "check",
                "selection_reason": "default",
                "status": "failed",
                "provider_ref": "builtin@command",
            },
        ],
        "unselected": [],
        "runs": [plan_run, code_run, mon_run],
    }


def _session_agents(tmp_path: Path) -> list[Agent]:
    """A collapsed session container: skipped plan, failed code, clean mon."""
    skipped = {
        "schema_version": 1,
        "phase": "skipped",
        "reason": "handoff:plan",
        "instances": [],
    }
    failed = {
        "schema_version": 1,
        "phase": "settled",
        "status": "failed",
        "instances": [
            {"id": "commit", "status": "success"},
            {"id": "check", "status": "failed"},
        ],
    }
    success = {
        "schema_version": 1,
        "phase": "settled",
        "status": "success",
        "instances": [{"id": "commit", "status": "success"}],
    }
    root = make_agent(
        tmp_path,
        name="visual-final",
        suffix="sess-root",
        status="DONE",
        summary=None,
        role="root",
        session="visual-final",
    )
    plan = make_agent(
        tmp_path,
        name="visual-final--plan",
        suffix="sess-plan",
        status="DONE",
        summary=skipped,
        role="plan",
        session="visual-final",
        parent_timestamp=root.raw_suffix,
        role_suffix="--plan",
    )
    code = make_agent(
        tmp_path,
        name="visual-final--code",
        suffix="sess-code",
        status="FAILED",
        summary=failed,
        role="code",
        session="visual-final",
        parent_timestamp=root.raw_suffix,
        role_suffix="--code",
    )
    mon = make_agent(
        tmp_path,
        name="visual-final--mon",
        suffix="sess-mon",
        status="DONE",
        summary=success,
        role="mon",
        session="visual-final",
        parent_timestamp=root.raw_suffix,
        role_suffix="--mon",
    )
    root.followup_agents = [plan, code, mon]
    return [root, plan, code, mon]


def _node_many_instances(count: int) -> dict[str, Any]:
    """A settled node with ``count`` successful instances for title tiers."""
    return {
        "schema_version": 1,
        "status": "success",
        "glyph": "✓",
        "run_level_trouble": False,
        "attention_instance_id": None,
        "instances": [
            {
                "instance_id": f"c{i}",
                "selection_reason": "default",
                "status": "success",
                "provider_ref": "builtin@command",
            }
            for i in range(count)
        ],
        "unselected": [],
        "runs": [
            {
                "run_id": "run-code",
                "number": 0,
                "label": "--code",
                "kind": "agent",
                "disposition": "ran",
                "cycles": 1,
                "plan_digest": "abc123",
                "result_status": "success",
                "declarations": [make_decl("accepted", 0, payload_count=1)],
                "drift": [],
                "diagnostics": [],
                "instances": [
                    {
                        "instance_id": f"c{i}",
                        "status": "success",
                        "provider_ref": "builtin@command",
                        "selection_reason": "default",
                        "attempt": 1,
                        "max_attempts": 1,
                        "op": "run",
                        "attempts": [
                            {
                                "attempt": 1,
                                "status": "success",
                                "started_at": T0_TS + 10,
                                "duration_seconds": 3.0,
                            }
                        ],
                        "operations": [],
                        "evidence": [],
                    }
                    for i in range(count)
                ],
            }
        ],
    }


async def test_agents_final_session_blocks_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    pin_visual_time(monkeypatch)
    patch_final_view(monkeypatch, _node_session())
    patch_startup_loaders(monkeypatch, agents=_session_agents(tmp_path))
    async with AcePage(query='"visual"', patches=patches()) as page:
        await goto_agents(page, 1)
        detail = await show_final(page, preferred="overview", expect="--plan ○ skipped")
        assert detail.deck_area.panel(0).final_view.active_card_id == "overview"
        assert_page_svg_styled_text_contains(page, "--plan ○ skipped")
        ace_png_visual.assert_page_png(
            page,
            "agents_final_session_blocks_120x40",
            title="ACE agents FINAL session run blocks with rail",
        )


async def test_agents_final_reply_split_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    pin_visual_time(monkeypatch)
    patch_final_view(monkeypatch, node_failed_check())
    agent = make_agent(
        tmp_path,
        name="failed",
        suffix="deck-split",
        status="FAILED",
        summary=deck_summary("check", status="failed"),
    )
    patch_startup_loaders(monkeypatch, agents=[agent])
    async with AcePage(query='"visual"', patches=patches()) as page:
        await goto_agents(page, 1)
        detail = page.app.query_one("#agent-detail-panel", AgentDetail)
        await page.press("backslash")
        await wait_for_visual_idle(page)
        detail.set_deck_preferred_card(0, "reply", DeckId.MAIN)
        detail.show_deck(0, DeckId.MAIN)
        await wait_for_state(
            page,
            lambda: detail.deck_area.panel(0).main_view.active_card_id == "reply",
            description="top panel shows the Reply card",
        )
        await show_final(
            page, preferred="instance:check", index=1, expect="attempt 2/2"
        )
        assert detail.deck_area.panel(1).deck is DeckId.FINAL
        assert_page_svg_styled_text_contains(page, "attempt 2/2")
        ace_png_visual.assert_page_png(
            page,
            "agents_final_reply_split_120x40",
            title="ACE agents Reply above FINAL below",
        )


async def test_agents_final_picker_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    pin_visual_time(monkeypatch)
    patch_final_view(monkeypatch, node_single_commit())
    agent = make_agent(
        tmp_path,
        name="landed",
        suffix="deck-picker",
        status="DONE",
        summary=deck_summary("commit"),
    )
    patch_startup_loaders(monkeypatch, agents=[agent])
    async with AcePage(query='"visual"', patches=patches()) as page:
        await goto_agents(page, 1)
        await show_final(page)
        await page.press("p")
        await page.expect_modal("DeckPickerModal")
        await wait_for_visual_idle(page)
        assert_page_svg_contains(page, "FINAL")
        ace_png_visual.assert_page_png(
            page,
            "agents_final_picker_120x40",
            title="ACE agents deck picker with FINAL",
        )


async def test_agents_final_narrow_tiers_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    pin_visual_time(monkeypatch)
    patch_final_view(monkeypatch, _node_many_instances(6))
    agent = make_agent(
        tmp_path,
        name="landed",
        suffix="deck-tiers",
        status="DONE",
        summary=deck_summary("c0", "c1", "c2", "c3", "c4", "c5"),
    )
    patch_startup_loaders(monkeypatch, agents=[agent])
    async with AcePage(query='"visual"', patches=patches()) as page:
        await goto_agents(page, 1)
        # A left-right split narrows each panel enough for the tab-only
        # title tiers while keeping the deck visible.
        await page.press("vertical_line")
        await wait_for_visual_idle(page)
        detail = await show_final(page, index=1, expect="2/7")
        panel = detail.deck_area.panel(1)
        assert panel.deck is DeckId.FINAL
        # `P` never applies to FINAL: the press is a no-op on this panel.
        await page.press("P")
        await wait_for_visual_idle(page)
        assert panel.deck is DeckId.FINAL
        assert detail.cycle_focused_deck_view() is None
        ace_png_visual.assert_page_png(
            page,
            "agents_final_narrow_tiers_120x40",
            title="ACE agents FINAL narrow tab-only title tiers",
        )

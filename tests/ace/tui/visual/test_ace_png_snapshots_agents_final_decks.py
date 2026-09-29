"""sase's TUI PNG visual snapshots for core FINAL deck states."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from sase.ace.testing import AcePage
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
    assert_page_svg_styled_text_contains,
)
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    patch_startup_loaders,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


def _node_plugin() -> dict[str, Any]:
    """One settled run: a plugin instance with typed evidence and steps."""
    return {
        "schema_version": 1,
        "status": "success",
        "glyph": "✓",
        "run_level_trouble": False,
        "attention_instance_id": None,
        "instances": [
            {
                "instance_id": "open-pr",
                "selection_reason": "default",
                "status": "success",
                "provider_ref": "acme@open-pr",
            }
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
                "plan_digest": "beef01",
                "result_status": "success",
                "declarations": [make_decl("accepted", 0, payload_count=2)],
                "drift": [],
                "diagnostics": [],
                "instances": [
                    {
                        "instance_id": "open-pr",
                        "status": "success",
                        "provider_ref": "acme@open-pr",
                        "selection_reason": "default",
                        "attempt": 1,
                        "max_attempts": 1,
                        "op": "execute",
                        "headline": {
                            "evidence_type": "url",
                            "label": "pull request",
                            "value": "https://example.dev/pr/412",
                            "display": "PR #412",
                        },
                        "attempts": [
                            {
                                "attempt": 1,
                                "status": "success",
                                "started_at": T0_TS + 8,
                                "duration_seconds": 22.0,
                            }
                        ],
                        "operations": [
                            {
                                "op": "execute",
                                "kind": "subprocess",
                                "label": "execute",
                                "attempt": 1,
                                "started_at": T0_TS + 8,
                                "duration_seconds": 22.0,
                                "returncode": 0,
                                "steps": [
                                    {
                                        "step": "opening pull request",
                                        "state": "start",
                                        "t": T0_TS + 9,
                                    },
                                    {
                                        "step": "PR #412 opened",
                                        "state": "ok",
                                        "t": T0_TS + 28,
                                    },
                                ],
                            }
                        ],
                        "evidence": [
                            {
                                "evidence_type": "url",
                                "label": "pull request",
                                "value": "https://example.dev/pr/412",
                                "display": "PR #412",
                            }
                        ],
                    }
                ],
            }
        ],
    }


def _node_unselected_drift() -> dict[str, Any]:
    """One settled run with an unselected instance, extra cycles, and drift."""
    payload = node_single_commit()
    run = payload["runs"][0]
    run["cycles"] = 3
    run["drift"] = [
        {
            "message": "commit.max_attempts sealed as 1, live config says 2",
            "instance_id": "commit",
            "code": "config_changed",
        }
    ]
    payload["unselected"] = [
        {
            "instance_id": "lint",
            "reason": "%final:!lint",
            "provider_ref": "builtin@command",
        }
    ]
    return payload


async def test_agents_final_single_commit_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    pin_visual_time(monkeypatch)
    patch_final_view(monkeypatch, node_single_commit())
    agent = make_agent(
        tmp_path,
        name="landed",
        suffix="deck-commit",
        status="DONE",
        summary=deck_summary("commit"),
    )
    patch_startup_loaders(monkeypatch, agents=[agent])
    async with AcePage(query='"visual"', patches=patches()) as page:
        await goto_agents(page, 1)
        detail = await show_final(page, preferred="overview", expect="rejected")
        assert detail.deck_area.panel(0).final_view.active_card_id == "overview"
        assert_page_svg_styled_text_contains(page, "rejected")
        ace_png_visual.assert_page_png(
            page,
            "agents_final_single_commit_120x40",
            title="ACE agents FINAL single successful commit",
        )


async def test_agents_final_failed_check_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    pin_visual_time(monkeypatch)
    patch_final_view(monkeypatch, node_failed_check())
    agent = make_agent(
        tmp_path,
        name="failed",
        suffix="deck-check",
        status="FAILED",
        summary=deck_summary("check", status="failed"),
    )
    patch_startup_loaders(monkeypatch, agents=[agent])
    async with AcePage(query='"visual"', patches=patches()) as page:
        await goto_agents(page, 1)
        detail = await show_final(
            page, preferred="instance:check", expect="attempt 2/2"
        )
        assert detail.deck_area.panel(0).final_view.active_card_id == "instance:check"
        assert_page_svg_styled_text_contains(page, "attempt 2/2")
        ace_png_visual.assert_page_png(
            page,
            "agents_final_failed_check_120x40",
            title="ACE agents FINAL failed check across two attempts",
        )


async def test_agents_final_plugin_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    pin_visual_time(monkeypatch)
    patch_final_view(monkeypatch, _node_plugin())
    agent = make_agent(
        tmp_path,
        name="landed",
        suffix="deck-plugin",
        status="DONE",
        summary=deck_summary("open-pr"),
    )
    patch_startup_loaders(monkeypatch, agents=[agent])
    async with AcePage(query='"visual"', patches=patches()) as page:
        await goto_agents(page, 1)
        detail = await show_final(page, preferred="instance:open-pr", expect="PR #412")
        assert detail.deck_area.panel(0).final_view.active_card_id == "instance:open-pr"
        assert_page_svg_styled_text_contains(page, "PR #412")
        ace_png_visual.assert_page_png(
            page,
            "agents_final_plugin_120x40",
            title="ACE agents FINAL plugin instance card",
        )


async def test_agents_final_overview_unselected_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    pin_visual_time(monkeypatch)
    patch_final_view(monkeypatch, _node_unselected_drift())
    agent = make_agent(
        tmp_path,
        name="landed",
        suffix="deck-overview",
        status="DONE",
        summary=deck_summary("commit"),
    )
    patch_startup_loaders(monkeypatch, agents=[agent])
    async with AcePage(query='"visual"', patches=patches()) as page:
        await goto_agents(page, 1)
        detail = await show_final(page, preferred="overview", expect="not selected")
        assert detail.deck_area.panel(0).final_view.active_card_id == "overview"
        assert_page_svg_styled_text_contains(page, "not selected")
        ace_png_visual.assert_page_png(
            page,
            "agents_final_overview_unselected_120x40",
            title="ACE agents FINAL Overview with unselected instance and drift",
        )

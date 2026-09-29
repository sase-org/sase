"""Shared FINAL-deck PNG snapshot fixtures and navigation helpers.

Public helpers for the ``test_ace_png_snapshots_agents_final*`` split. This
module is private (``_``-prefixed); the helpers are public so each split test
module can import them without importing a ``_``-prefixed name across modules.
"""

from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.widgets import AgentDetail
from sase.ace.tui.widgets.decks.model import DeckId
from sase.core.agent_scan_wire_markers import finalizer_status_from_mapping
from sase.core.finalizer_run_view import finalizer_node_view_from_dict
from tests.ace.tui.visual._ace_agents_png_snapshot_helpers import pin_agents_visual_now
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    wait_for_startup,
    wait_for_state,
    wait_for_visual_idle,
)

FIXED_NOW = datetime(2026, 9, 27, 12, 0, 0)
FIXED_NOW_TS = FIXED_NOW.timestamp()
T0_TS = datetime(2026, 9, 27, 7, 30, 0).timestamp()


def pin_visual_time(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin every clock the FINAL goldens can observe.

    Agent-relative labels come from ``pin_agents_visual_now``; the
    running Reply receipt stamps durations with ``time.time``.
    """
    pin_agents_visual_now(monkeypatch, FIXED_NOW)
    monkeypatch.setattr(time, "time", lambda: FIXED_NOW_TS)


def make_decl(status: str, offset: float, **extra: Any) -> dict[str, Any]:
    return {"status": status, "t": T0_TS + offset, **extra}


def make_agent(
    tmp_path: Path,
    *,
    name: str,
    suffix: str,
    status: str,
    summary: dict[str, Any] | None,
    role: str = "code",
    session: str | None = None,
    parent_timestamp: str | None = None,
    role_suffix: str | None = None,
) -> Agent:
    """Build a lone fixture agent with Reply content and a glance summary."""
    directory = tmp_path / f"visual-final-{suffix}"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "raw_xprompt.md").write_text(
        f"{role} xprompt line one\n{role} xprompt line two\n", encoding="utf-8"
    )
    (directory / "01_prompt.md").write_text(
        f"{role} prompt line one\n{role} prompt line two\n", encoding="utf-8"
    )
    response_path = directory / "response.md"
    response_path.write_text(
        f"{role} outcome line one\n{role} outcome line two\n", encoding="utf-8"
    )
    agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="visual-final",
        project_file="/workspace/sase/visual_project.sase",
        status=status,
        start_time=datetime(2026, 9, 27, 7, 30, 0),
        stop_time=datetime(2026, 9, 27, 7, 42, 0),
        raw_suffix=f"20260927073000-{suffix}",
        agent_name=name,
        llm_provider="codex",
        model="gpt-5",
        artifacts_dir=str(directory),
        response_path=str(response_path),
        parent_timestamp=parent_timestamp,
        role_suffix=role_suffix,
    )
    if session is not None:
        agent.agent_session = session
        agent.agent_session_role = role
    agent.finalizer_status = (
        finalizer_status_from_mapping(summary) if summary is not None else None
    )
    return agent


def deck_summary(
    *ids: str, status: str = "success", phase: str = "settled"
) -> dict[str, Any]:
    """A settled glance summary naming ``ids`` so the FINAL probe has content."""
    return {
        "schema_version": 1,
        "phase": phase,
        "status": status,
        "instances": [{"id": instance_id, "status": status} for instance_id in ids],
    }


def patch_final_view(monkeypatch: pytest.MonkeyPatch, payload: dict[str, Any]) -> None:
    """Serve one fixed node view from the FINAL loader's projection point."""
    import sase.ace.tui.widgets.decks.final.loader as loader_module

    loader_module.clear_final_cache()
    view = finalizer_node_view_from_dict(payload)
    monkeypatch.setattr(loader_module, "project_node_view", lambda _targets: view)


async def goto_agents(page: AcePage, count: int) -> None:
    await wait_for_startup(page)
    await page.press("shift+tab")
    await page.expect_state("tab", "agents")
    await page.expect_state("agent_count", count)
    await wait_for_visual_idle(page)


async def show_final(
    page: AcePage,
    *,
    preferred: str | None = None,
    index: int = 0,
    expect: str | None = None,
) -> AgentDetail:
    """Show the FINAL deck on one panel and wait for its document to paint."""
    from tests.ace.tui.visual._ace_agents_png_snapshot_helpers import page_svg_text

    detail = page.app.query_one("#agent-detail-panel", AgentDetail)
    if preferred is not None:
        detail.set_deck_preferred_card(index, preferred, DeckId.FINAL)
    detail.show_deck(index, DeckId.FINAL)
    await wait_for_state(
        page,
        lambda: detail.deck_area.panel(index)._final_document is not None,
        description="FINAL deck document loaded",
    )
    if expect is not None:
        compact = expect.replace(" ", "")

        def _painted(_state: dict[str, Any]) -> bool:
            try:
                svg_plain = page_svg_text(page).replace(" ", "").replace("\n", "")
            except Exception:
                return False
            return compact in svg_plain

        await page.wait_for(_painted, timeout=10.0)
    await wait_for_visual_idle(page)
    return detail


def node_single_commit() -> dict[str, Any]:
    """One settled run: a successful commit after a rejected declaration."""
    return {
        "schema_version": 1,
        "status": "success",
        "glyph": "✓",
        "run_level_trouble": False,
        "attention_instance_id": None,
        "instances": [
            {
                "instance_id": "commit",
                "selection_reason": "default",
                "status": "success",
                "provider_ref": "builtin@commit",
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
                "cycles": 2,
                "plan_digest": "abc123",
                "result_status": "success",
                "declarations": [
                    make_decl(
                        "rejected",
                        0,
                        code="invalid",
                        first_line="sase final submit --help",
                    ),
                    make_decl("accepted", 5, payload_count=1),
                ],
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
                            "value": "8bb7e55",
                            "display": "commit 8bb7e55",
                        },
                        "warnings": 2,
                        "attempts": [
                            {
                                "attempt": 1,
                                "status": "success",
                                "started_at": T0_TS + 10,
                                "duration_seconds": 12.3,
                            }
                        ],
                        "operations": [
                            {
                                "op": "stitch main",
                                "kind": "subprocess",
                                "label": "stitch main",
                                "attempt": 1,
                                "started_at": T0_TS + 12,
                                "duration_seconds": 4.5,
                                "returncode": 0,
                            }
                        ],
                        "evidence": [
                            {
                                "evidence_type": "commit",
                                "label": "commit",
                                "value": "8bb7e55",
                                "display": "commit 8bb7e55",
                            }
                        ],
                    }
                ],
            }
        ],
    }


def node_failed_check() -> dict[str, Any]:
    """One settled run: a failed check across two attempts with diagnostics."""
    return {
        "schema_version": 1,
        "status": "failed",
        "glyph": "✗",
        "run_level_trouble": True,
        "attention_instance_id": "check",
        "instances": [
            {
                "instance_id": "check",
                "selection_reason": "default",
                "status": "failed",
                "provider_ref": "builtin@command",
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
                "plan_digest": "def456",
                "result_status": "failed",
                "declarations": [make_decl("accepted", 0, payload_count=1)],
                "drift": [],
                "diagnostics": [],
                "instances": [
                    {
                        "instance_id": "check",
                        "status": "failed",
                        "provider_ref": "builtin@command",
                        "selection_reason": "default",
                        "attempt": 2,
                        "max_attempts": 2,
                        "op": "just check",
                        "failure_reason": "command_failed",
                        "attempts": [
                            {
                                "attempt": 1,
                                "status": "failed",
                                "started_at": T0_TS + 10,
                                "duration_seconds": 30.0,
                            },
                            {
                                "attempt": 2,
                                "status": "failed",
                                "started_at": T0_TS + 50,
                                "duration_seconds": 31.5,
                            },
                        ],
                        "operations": [
                            {
                                "op": "just check",
                                "kind": "subprocess",
                                "label": "just check",
                                "attempt": 2,
                                "started_at": T0_TS + 50,
                                "duration_seconds": 31.5,
                                "returncode": 1,
                                "argv": ["just", "check"],
                                "logs": [
                                    {
                                        "kind": "stdout",
                                        "name": "attempt-2.run.stdout",
                                        "line_count": 40,
                                    }
                                ],
                                "steps": [
                                    {
                                        "step": "running just check",
                                        "state": "start",
                                        "t": T0_TS + 51,
                                    },
                                    {
                                        "step": "2 tests failed",
                                        "state": "fail",
                                        "t": T0_TS + 81,
                                    },
                                ],
                            }
                        ],
                        "diagnostics": [
                            {
                                "code": "command_failed",
                                "message": "just check exited 1",
                                "severity": "error",
                                "attempt": 2,
                            }
                        ],
                    }
                ],
            }
        ],
    }

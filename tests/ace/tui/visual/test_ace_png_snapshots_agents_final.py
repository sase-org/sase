"""sase's TUI PNG visual snapshots for the ⊛ FINAL deck (epic sase-1b2, bead sase-1b2.19).

Deterministic goldens for every glance and deck state, built on fixed
fixtures: row states (FINALIZING, ``⊛✗``, ``⊛⏸``, ``⊛!``, success
silence), Reply receipts (running, failed with reason, deferred plus
not-triggered), the FINAL deck (single successful commit with
declaration rejections, failed check across two attempts, a plugin
instance, an Overview with an unselected instance and drift, a session
container with run blocks and the rail), the Reply/FINAL split, the
deck picker with ``n``, and the narrow title tiers.

FINAL deck views are built from fixed dict fixtures through
``finalizer_node_view_from_dict`` and installed by patching the
loader's ``project_node_view`` entry point, so no wall-clock, thread
timing, or artifact mtime reaches the pixels. The panels, chrome,
tabs, subtitle, picker, rail, and block host under test are all real.
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
from tests.ace.tui.visual._ace_agents_png_snapshot_helpers import (
    assert_page_svg_contains,
    assert_page_svg_styled_text_contains,
    pin_agents_visual_now,
)
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_state,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual

_FIXED_NOW = datetime(2026, 9, 27, 12, 0, 0)
_FIXED_NOW_TS = _FIXED_NOW.timestamp()
_T0_TS = datetime(2026, 9, 27, 7, 30, 0).timestamp()


def _pin_visual_time(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin every clock the FINAL goldens can observe.

    Agent-relative labels come from ``pin_agents_visual_now``; the
    running Reply receipt stamps durations with ``time.time``.
    """
    pin_agents_visual_now(monkeypatch, _FIXED_NOW)
    monkeypatch.setattr(time, "time", lambda: _FIXED_NOW_TS)


def _decl(status: str, offset: float, **extra: Any) -> dict[str, Any]:
    return {"status": status, "t": _T0_TS + offset, **extra}


def _agent(
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


def _deck_summary(
    *ids: str, status: str = "success", phase: str = "settled"
) -> dict[str, Any]:
    """A settled glance summary naming ``ids`` so the FINAL probe has content."""
    return {
        "schema_version": 1,
        "phase": phase,
        "status": status,
        "instances": [{"id": instance_id, "status": status} for instance_id in ids],
    }


def _patch_final_view(monkeypatch: pytest.MonkeyPatch, payload: dict[str, Any]) -> None:
    """Serve one fixed node view from the FINAL loader's projection point."""
    import sase.ace.tui.widgets.decks.final.loader as loader_module

    loader_module.clear_final_cache()
    view = finalizer_node_view_from_dict(payload)
    monkeypatch.setattr(loader_module, "project_node_view", lambda _targets: view)


async def _goto_agents(page: AcePage, count: int) -> None:
    await wait_for_startup(page)
    await page.press("shift+tab")
    await page.expect_state("tab", "agents")
    await page.expect_state("agent_count", count)
    await wait_for_visual_idle(page)


async def _show_final(
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


def _node_single_commit() -> dict[str, Any]:
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
                    _decl(
                        "rejected",
                        0,
                        code="invalid",
                        first_line="sase final submit --help",
                    ),
                    _decl("accepted", 5, payload_count=1),
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
                                "started_at": _T0_TS + 10,
                                "duration_seconds": 12.3,
                            }
                        ],
                        "operations": [
                            {
                                "op": "stitch main",
                                "kind": "subprocess",
                                "label": "stitch main",
                                "attempt": 1,
                                "started_at": _T0_TS + 12,
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


def _node_failed_check() -> dict[str, Any]:
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
                "declarations": [_decl("accepted", 0, payload_count=1)],
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
                                "started_at": _T0_TS + 10,
                                "duration_seconds": 30.0,
                            },
                            {
                                "attempt": 2,
                                "status": "failed",
                                "started_at": _T0_TS + 50,
                                "duration_seconds": 31.5,
                            },
                        ],
                        "operations": [
                            {
                                "op": "just check",
                                "kind": "subprocess",
                                "label": "just check",
                                "attempt": 2,
                                "started_at": _T0_TS + 50,
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
                                        "t": _T0_TS + 51,
                                    },
                                    {
                                        "step": "2 tests failed",
                                        "state": "fail",
                                        "t": _T0_TS + 81,
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
                "declarations": [_decl("accepted", 0, payload_count=2)],
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
                                "started_at": _T0_TS + 8,
                                "duration_seconds": 22.0,
                            }
                        ],
                        "operations": [
                            {
                                "op": "execute",
                                "kind": "subprocess",
                                "label": "execute",
                                "attempt": 1,
                                "started_at": _T0_TS + 8,
                                "duration_seconds": 22.0,
                                "returncode": 0,
                                "steps": [
                                    {
                                        "step": "opening pull request",
                                        "state": "start",
                                        "t": _T0_TS + 9,
                                    },
                                    {
                                        "step": "PR #412 opened",
                                        "state": "ok",
                                        "t": _T0_TS + 28,
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
    payload = _node_single_commit()
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


def _node_session() -> dict[str, Any]:
    """A handoff-skipped plan, a failed code run, and a clean monitor run."""
    code_run = _node_failed_check()["runs"][0]
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
                "started_at": _T0_TS + 10,
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
        "declarations": [_decl("accepted", 200, payload_count=1)],
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
                        "started_at": _T0_TS + 210,
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
                "started_at": _T0_TS + 10,
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
        _agent(
            tmp_path, name="finalizing", suffix="a", status="RUNNING", summary=executing
        ),
        _agent(tmp_path, name="failed", suffix="b", status="FAILED", summary=failed),
        _agent(tmp_path, name="deferred", suffix="c", status="DONE", summary=deferred),
        _agent(
            tmp_path, name="killed", suffix="d", status="FAILED", summary=interrupted
        ),
        _agent(tmp_path, name="landed", suffix="e", status="DONE", summary=success),
    ]


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
                "declarations": [_decl("accepted", 0, payload_count=1)],
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
                                "started_at": _T0_TS + 10,
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


# -- Row states ------------------------------------------------------------


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
    _pin_visual_time(monkeypatch)
    patch_startup_loaders(monkeypatch, agents=_row_agents(tmp_path))
    async with AcePage(query='"visual"', size=(width, 40), patches=patches()) as page:
        await _goto_agents(page, 5)
        assert_page_svg_contains(page, "FINALIZING")
        assert_page_svg_contains(page, "⊛")
        ace_png_visual.assert_page_png(
            page,
            snapshot_name,
            title="ACE agents FINAL glance row states",
        )


# -- Reply receipts --------------------------------------------------------


async def _receipt_page(page: AcePage) -> None:
    await _goto_agents(page, 1)
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
    _pin_visual_time(monkeypatch)
    agent = _agent(
        tmp_path,
        name="running",
        suffix="receipt-run",
        status="RUNNING",
        summary={
            "schema_version": 1,
            "phase": "executing",
            "started_at": _T0_TS,
            "instances": [
                {
                    "id": "commit",
                    "status": "running",
                    "attempt": 1,
                    "max_attempts": 1,
                    "op": "stitch main",
                    "step": "just fix",
                    "started_at": _T0_TS + 10,
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
    _pin_visual_time(monkeypatch)
    agent = _agent(
        tmp_path,
        name="failed",
        suffix="receipt-fail",
        status="FAILED",
        summary={
            "schema_version": 1,
            "phase": "settled",
            "status": "failed",
            "started_at": _T0_TS,
            "instances": [
                {
                    "id": "check",
                    "status": "failed",
                    "attempt": 2,
                    "max_attempts": 2,
                    "reason": "command_failed",
                    "started_at": _T0_TS + 50,
                    "finished_at": _T0_TS + 81,
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
    _pin_visual_time(monkeypatch)
    agent = _agent(
        tmp_path,
        name="deferred",
        suffix="receipt-defer",
        status="DONE",
        summary={
            "schema_version": 1,
            "phase": "settled",
            "status": "deferred",
            "started_at": _T0_TS,
            "instances": [
                {
                    "id": "commit",
                    "status": "deferred",
                    "reason": "no_diff",
                    "started_at": _T0_TS + 10,
                    "finished_at": _T0_TS + 12,
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


# -- FINAL deck states -----------------------------------------------------


async def test_agents_final_single_commit_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _pin_visual_time(monkeypatch)
    _patch_final_view(monkeypatch, _node_single_commit())
    agent = _agent(
        tmp_path,
        name="landed",
        suffix="deck-commit",
        status="DONE",
        summary=_deck_summary("commit"),
    )
    patch_startup_loaders(monkeypatch, agents=[agent])
    async with AcePage(query='"visual"', patches=patches()) as page:
        await _goto_agents(page, 1)
        detail = await _show_final(page, preferred="overview", expect="rejected")
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
    _pin_visual_time(monkeypatch)
    _patch_final_view(monkeypatch, _node_failed_check())
    agent = _agent(
        tmp_path,
        name="failed",
        suffix="deck-check",
        status="FAILED",
        summary=_deck_summary("check", status="failed"),
    )
    patch_startup_loaders(monkeypatch, agents=[agent])
    async with AcePage(query='"visual"', patches=patches()) as page:
        await _goto_agents(page, 1)
        detail = await _show_final(
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
    _pin_visual_time(monkeypatch)
    _patch_final_view(monkeypatch, _node_plugin())
    agent = _agent(
        tmp_path,
        name="landed",
        suffix="deck-plugin",
        status="DONE",
        summary=_deck_summary("open-pr"),
    )
    patch_startup_loaders(monkeypatch, agents=[agent])
    async with AcePage(query='"visual"', patches=patches()) as page:
        await _goto_agents(page, 1)
        detail = await _show_final(page, preferred="instance:open-pr", expect="PR #412")
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
    _pin_visual_time(monkeypatch)
    _patch_final_view(monkeypatch, _node_unselected_drift())
    agent = _agent(
        tmp_path,
        name="landed",
        suffix="deck-overview",
        status="DONE",
        summary=_deck_summary("commit"),
    )
    patch_startup_loaders(monkeypatch, agents=[agent])
    async with AcePage(query='"visual"', patches=patches()) as page:
        await _goto_agents(page, 1)
        detail = await _show_final(page, preferred="overview", expect="not selected")
        assert detail.deck_area.panel(0).final_view.active_card_id == "overview"
        assert_page_svg_styled_text_contains(page, "not selected")
        ace_png_visual.assert_page_png(
            page,
            "agents_final_overview_unselected_120x40",
            title="ACE agents FINAL Overview with unselected instance and drift",
        )


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
    root = _agent(
        tmp_path,
        name="visual-final",
        suffix="sess-root",
        status="DONE",
        summary=None,
        role="root",
        session="visual-final",
    )
    plan = _agent(
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
    code = _agent(
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
    mon = _agent(
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


async def test_agents_final_session_blocks_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _pin_visual_time(monkeypatch)
    _patch_final_view(monkeypatch, _node_session())
    patch_startup_loaders(monkeypatch, agents=_session_agents(tmp_path))
    async with AcePage(query='"visual"', patches=patches()) as page:
        await _goto_agents(page, 1)
        detail = await _show_final(
            page, preferred="overview", expect="--plan ○ skipped"
        )
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
    _pin_visual_time(monkeypatch)
    _patch_final_view(monkeypatch, _node_failed_check())
    agent = _agent(
        tmp_path,
        name="failed",
        suffix="deck-split",
        status="FAILED",
        summary=_deck_summary("check", status="failed"),
    )
    patch_startup_loaders(monkeypatch, agents=[agent])
    async with AcePage(query='"visual"', patches=patches()) as page:
        await _goto_agents(page, 1)
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
        await _show_final(
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
    _pin_visual_time(monkeypatch)
    _patch_final_view(monkeypatch, _node_single_commit())
    agent = _agent(
        tmp_path,
        name="landed",
        suffix="deck-picker",
        status="DONE",
        summary=_deck_summary("commit"),
    )
    patch_startup_loaders(monkeypatch, agents=[agent])
    async with AcePage(query='"visual"', patches=patches()) as page:
        await _goto_agents(page, 1)
        await _show_final(page)
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
    _pin_visual_time(monkeypatch)
    _patch_final_view(monkeypatch, _node_many_instances(6))
    agent = _agent(
        tmp_path,
        name="landed",
        suffix="deck-tiers",
        status="DONE",
        summary=_deck_summary("c0", "c1", "c2", "c3", "c4", "c5"),
    )
    patch_startup_loaders(monkeypatch, agents=[agent])
    async with AcePage(query='"visual"', patches=patches()) as page:
        await _goto_agents(page, 1)
        # A left-right split narrows each panel enough for the tab-only
        # title tiers while keeping the deck visible.
        await page.press("vertical_line")
        await wait_for_visual_idle(page)
        detail = await _show_final(page, index=1, expect="2/7")
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

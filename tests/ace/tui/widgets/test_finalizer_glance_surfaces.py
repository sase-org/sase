"""Glance-surface tests for phase glance-surfaces (epic sase-1b2, bead sase-1b2.8).

Covers the shared vocabulary, pure row-state tables, the D10 session
supersede rule, row/header rendering, and the Reply receipt.
"""

from __future__ import annotations

from datetime import datetime

from rich.text import Text

from sase.ace.tui.models._agent_time_wait import format_compact_duration
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.finalizer_row_state import (
    finalizer_header_chip,
    finalizer_row_state,
    finalizer_summary_token,
    session_finalizer_row_state,
)
from sase.ace.tui.widgets._agent_list_render_agent_status import (
    append_agent_row_status,
)
from sase.ace.tui.widgets.prompt_panel._agent_finalizer_receipt import (
    finalizer_receipt_text,
)
from sase.agent.status_buckets import status_bucket_for_values
from sase.core.agent_scan_wire_markers import finalizer_status_from_mapping
from sase.finalizers.view_vocabulary import instance_style


def _agent(*, status: str = "RUNNING", summary: dict | None = None) -> Agent:
    agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="demo-code",
        project_file="/tmp/p.sase",
        status=status,
        start_time=datetime(2026, 9, 27, 7, 30, 0),
        raw_suffix="20260927073000-code",
    )
    agent.finalizer_status = (
        finalizer_status_from_mapping(summary) if summary is not None else None
    )
    return agent


_EXECUTING = {
    "schema_version": 1,
    "phase": "executing",
    "run_id": "abc123",
    "started_at": 1727440000.0,
    "updated_at": 1727440012.5,
    "instance_count": 1,
    "instances": [
        {
            "id": "commit",
            "status": "running",
            "attempt": 1,
            "max_attempts": 1,
            "op": "stitch main",
            "step": "just fix",
            "started_at": 1727440001.0,
        }
    ],
}


def test_vocabulary_maps_c5_statuses() -> None:
    assert instance_style("running").glyph == "▶"
    assert instance_style("failed").word == "failed"
    assert instance_style("refused").glyph == "⊘"
    assert instance_style("deferred").glyph == "⏸"
    assert instance_style("waiting").word == "planned"
    assert instance_style("bogus").word == "planned"


def test_row_state_finalizing_and_chip() -> None:
    state = finalizer_row_state(_agent(status="RUNNING", summary=_EXECUTING))

    assert state.is_finalizing is True
    assert state.chip_text == "⊛ commit · just fix"


def test_row_state_step_falls_back_to_op() -> None:
    summary = {
        "phase": "executing",
        "instances": [{"id": "check", "status": "running", "op": "just check"}],
    }

    state = finalizer_row_state(_agent(status="RUNNING", summary=summary))

    assert state.chip_text == "⊛ check · just check"


def test_row_state_success_is_silent_despite_warnings() -> None:
    summary = {
        "phase": "settled",
        "status": "success",
        "instances": [{"id": "commit", "status": "success", "warnings": 3}],
    }

    state = finalizer_row_state(_agent(status="DONE", summary=summary))

    assert state.is_finalizing is False
    assert state.chip_text is None


def test_row_state_failed_refused_deferred_chips() -> None:
    for status, glyph in (("failed", "✗"), ("refused", "⊘"), ("deferred", "⏸")):
        summary = {
            "phase": "settled",
            "status": status,
            "instances": [{"id": "check", "status": status}],
        }

        state = finalizer_row_state(_agent(status="FAILED", summary=summary))

        assert state.chip_text == f"⊛{glyph} check"


def test_row_state_interrupted_when_turn_ends_mid_run() -> None:
    state = finalizer_row_state(_agent(status="DONE", summary=_EXECUTING))

    assert state.is_finalizing is False
    assert state.chip_text == "⊛! commit · just fix"


def test_row_state_silent_for_planned_skipped_and_legacy() -> None:
    planned = {"phase": "planned", "instances": [{"id": "c", "status": "planned"}]}
    skipped = {"phase": "skipped", "reason": "handoff:plan", "instances": []}

    assert finalizer_row_state(_agent(summary=planned)).chip_text is None
    assert finalizer_row_state(_agent(summary=skipped)).chip_text is None
    assert finalizer_row_state(_agent(summary=None)).chip_text is None
    assert finalizer_row_state(_agent(summary=None)).is_finalizing is False


def test_row_state_summary_token() -> None:
    token = finalizer_summary_token(_agent(summary=_EXECUTING))

    assert token == ("executing", None, 1727440012.5, 1)
    assert finalizer_summary_token(_agent(summary=None)) is None


def test_session_supersede_ignores_runs_before_latest_success() -> None:
    old_failure = _agent(
        status="DONE",
        summary={
            "phase": "settled",
            "status": "failed",
            "instances": [{"id": "check", "status": "failed"}],
        },
    )
    new_success = _agent(
        status="DONE",
        summary={
            "phase": "settled",
            "status": "success",
            "instances": [{"id": "check", "status": "success"}],
        },
    )
    container = _agent(status="DONE", summary=None)

    state = session_finalizer_row_state(container, members=[old_failure, new_success])

    assert state.chip_text is None


def test_session_supersede_picks_severity_with_run_counts() -> None:
    ok = _agent(
        status="DONE",
        summary={
            "phase": "settled",
            "status": "success",
            "instances": [{"id": "commit", "status": "success"}],
        },
    )
    failed = _agent(
        status="DONE",
        summary={
            "phase": "settled",
            "status": "failed",
            "instances": [{"id": "check", "status": "failed"}],
        },
    )
    running = _agent(status="RUNNING", summary=_EXECUTING)
    container = _agent(status="RUNNING", summary=None)

    state = session_finalizer_row_state(container, members=[ok, failed, running])

    assert state.chip_text == "⊛✗ check · 1 of 2 runs"
    assert state.is_finalizing is True


def _render_row(agent: Agent) -> str:
    text = Text()
    append_agent_row_status(text, agent)
    return text.plain


def test_row_renders_finalizing_word_in_running_bucket() -> None:
    agent = _agent(status="RUNNING", summary=_EXECUTING)

    plain = _render_row(agent)

    assert "(FINALIZING)" in plain
    assert "⊛ commit · just fix" in plain
    # D11: the overlay never changes the underlying status or its bucket.
    assert agent.status == "RUNNING"
    assert status_bucket_for_values("RUNNING") == "Running"


def test_row_done_failure_chip() -> None:
    agent = _agent(
        status="FAILED",
        summary={
            "phase": "settled",
            "status": "failed",
            "instances": [{"id": "check", "status": "failed"}],
        },
    )

    assert "⊛✗ check" in _render_row(agent)


def test_header_chip_finalizing_and_declaration() -> None:
    text, _style = finalizer_header_chip(_agent(status="RUNNING", summary=_EXECUTING))
    assert text == "⊛ finalizing · commit · just fix"

    declaring = dict(_EXECUTING, phase="declaring")
    text, _style = finalizer_header_chip(_agent(status="RUNNING", summary=declaring))
    assert text == "⊛ declaration"

    assert finalizer_header_chip(_agent(summary=None)) is None


def test_receipt_running_and_failed() -> None:
    receipt = finalizer_receipt_text(_agent(status="RUNNING", summary=_EXECUTING))

    assert isinstance(receipt, Text)
    assert "⊛ FINAL" in receipt.plain
    assert "commit" in receipt.plain
    assert "just fix" in receipt.plain

    failed = _agent(
        status="FAILED",
        summary={
            "phase": "settled",
            "status": "failed",
            "started_at": 1727440000.0,
            "instances": [
                {
                    "id": "check",
                    "status": "failed",
                    "attempt": 2,
                    "max_attempts": 2,
                    "reason": "command_failed",
                    "started_at": 1727440000.0,
                    "finished_at": 1727440220.0,
                },
                {"id": "tasks", "status": "not_run"},
            ],
        },
    )
    receipt = finalizer_receipt_text(failed)

    assert receipt is not None
    assert "✗ check" in receipt.plain
    assert "command_failed · attempt 2/2" in receipt.plain
    assert "FAILED command_failed" in receipt.plain
    assert "not run" in receipt.plain
    assert format_compact_duration(220.0) in receipt.plain


def test_receipt_success_warnings_suffix() -> None:
    agent = _agent(
        status="DONE",
        summary={
            "phase": "settled",
            "status": "success",
            "started_at": 1727440000.0,
            "instances": [
                {
                    "id": "commit",
                    "status": "success",
                    "headline": "commit 8bb7e55",
                    "warnings": 2,
                }
            ],
        },
    )

    receipt = finalizer_receipt_text(agent)

    assert receipt is not None
    assert "⚠2" in receipt.plain
    assert "commit 8bb7e55" in receipt.plain


def test_receipt_absent_for_skipped_planned_legacy_and_empty() -> None:
    skipped = _agent(
        summary={"phase": "skipped", "reason": "handoff:plan", "instances": []}
    )
    planned = _agent(
        summary={"phase": "planned", "instances": [{"id": "c", "status": "planned"}]}
    )
    empty = _agent(summary={"phase": "settled", "status": "success", "instances": []})
    legacy = _agent(summary=None)

    assert finalizer_receipt_text(skipped) is None
    assert finalizer_receipt_text(planned) is None
    assert finalizer_receipt_text(empty) is None
    assert finalizer_receipt_text(legacy) is None

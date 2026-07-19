"""Tests for the agent revive audit log helpers and CLI."""

from __future__ import annotations

import argparse
import io
import json
from contextlib import redirect_stdout
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from sase.ace.tui.actions.agents._revive_log import (
    log_revive_failure,
    log_revive_started,
    log_revive_success,
)
from sase.ace.tui.models.agent import Agent, AgentType
from sase.logs.revive_log_cli import handle_revive_log_command
from sase.logs.run_log import iter_revive_events


def _make_agent(**overrides: object) -> Agent:
    defaults: dict[str, object] = {
        "agent_type": AgentType.WORKFLOW,
        "cl_name": "test_cl",
        "project_file": "/tmp/projects/myproj/myproj.sase",
        "status": "DONE",
        "start_time": datetime(2024, 1, 1, 12, 0, 0),
        "workflow": "wf",
        "raw_suffix": "20240101120000",
        "artifacts_dir": "/tmp/projects/myproj/artifacts/workflow-wf/20240101120000",
    }
    defaults.update(overrides)
    return Agent(**defaults)  # type: ignore[arg-type]


def test_round_trip_through_log_event(tmp_path: Path) -> None:
    """Records written via the helpers parse back through iter_revive_events."""
    events_file = tmp_path / "events.jsonl"
    agent = _make_agent(cl_name="feature_a", raw_suffix="20260201120000")
    agent._dismissed_bundle_path = "/fake/path/20260201120000.json"

    with patch("sase.logs.run_log.EVENTS_FILE", str(events_file)):
        log_revive_started(agents=[agent])
        log_revive_success(agent=agent)

    records = list(iter_revive_events(events_file=str(events_file)))
    # Reverse-chronological: success first, then started.
    assert [r["event"] for r in records] == ["agent_revived", "agent_revive_started"]
    success = records[0]
    assert success["cl_name"] == "feature_a"
    assert success["raw_suffix"] == "20260201120000"
    assert success["bundle_path"] == "/fake/path/20260201120000.json"
    assert success["outcome"] == "success"
    assert success["agent_identity"] == [
        "workflow",
        "feature_a",
        "20260201120000",
    ]


def test_iter_revive_events_filters_outcome(tmp_path: Path) -> None:
    """``outcome`` filters infer success/failure from the event name."""
    events_file = tmp_path / "events.jsonl"
    agent = _make_agent(cl_name="cl_a")

    with patch("sase.logs.run_log.EVENTS_FILE", str(events_file)):
        log_revive_success(agent=agent)
        log_revive_failure(
            stage="artifact_restore", agent=agent, error=RuntimeError("boom")
        )

    successes = list(
        iter_revive_events(outcome="success", events_file=str(events_file))
    )
    failures = list(iter_revive_events(outcome="failure", events_file=str(events_file)))
    assert [r["event"] for r in successes] == ["agent_revived"]
    assert [r["event"] for r in failures] == ["agent_revive_failed"]
    assert failures[0]["stage"] == "artifact_restore"
    assert failures[0]["error_type"] == "RuntimeError"
    assert failures[0]["error_message"] == "boom"


def test_iter_revive_events_skips_non_revive_events(tmp_path: Path) -> None:
    """Other events (commit_created, etc.) are not yielded."""
    events_file = tmp_path / "events.jsonl"
    events_file.write_text(
        json.dumps(
            {"timestamp": "260101_120000", "event": "commit_created", "cl_name": "x"}
        )
        + "\n"
        + json.dumps(
            {
                "timestamp": "260101_120001",
                "event": "agent_revived",
                "cl_name": "y",
                "outcome": "success",
            }
        )
        + "\n"
    )
    records = list(iter_revive_events(events_file=str(events_file)))
    assert len(records) == 1
    assert records[0]["cl_name"] == "y"


def test_iter_revive_events_skips_malformed_lines(tmp_path: Path) -> None:
    """Garbage lines must not break the iterator."""
    events_file = tmp_path / "events.jsonl"
    events_file.write_text(
        "not json\n"
        + json.dumps(
            {
                "timestamp": "260101_120001",
                "event": "agent_revived",
                "cl_name": "y",
                "outcome": "success",
            }
        )
        + "\n"
    )
    records = list(iter_revive_events(events_file=str(events_file)))
    assert len(records) == 1


def test_cli_table_output(tmp_path: Path) -> None:
    """Default CLI invocation renders a table with the right columns."""
    events_file = tmp_path / "events.jsonl"
    events_file.write_text(
        json.dumps(
            {
                "timestamp": "260101_120000",
                "event": "agent_revived",
                "cl_name": "feature_a",
                "raw_suffix": "20260101120000",
                "outcome": "success",
            }
        )
        + "\n"
    )
    args = argparse.Namespace(
        all=False, limit=20, since=None, outcome=None, as_json=False
    )
    buf = io.StringIO()
    with (
        patch("sase.logs.run_log.EVENTS_FILE", str(events_file)),
        redirect_stdout(buf),
    ):
        try:
            handle_revive_log_command(args)
        except SystemExit:
            pass
    output = buf.getvalue()
    assert "feature_a" in output
    assert "20260101120000" in output
    assert "success" in output


def test_cli_json_output(tmp_path: Path) -> None:
    """--json emits one JSON object per line."""
    events_file = tmp_path / "events.jsonl"
    events_file.write_text(
        json.dumps(
            {
                "timestamp": "260101_120000",
                "event": "agent_revived",
                "cl_name": "feature_a",
                "outcome": "success",
            }
        )
        + "\n"
        + json.dumps(
            {
                "timestamp": "260101_120100",
                "event": "agent_revived",
                "cl_name": "feature_b",
                "outcome": "success",
            }
        )
        + "\n"
    )
    args = argparse.Namespace(
        all=False, limit=20, since=None, outcome=None, as_json=True
    )
    buf = io.StringIO()
    with (
        patch("sase.logs.run_log.EVENTS_FILE", str(events_file)),
        redirect_stdout(buf),
    ):
        try:
            handle_revive_log_command(args)
        except SystemExit:
            pass
    lines = [line for line in buf.getvalue().splitlines() if line.strip()]
    assert len(lines) == 2
    payloads = [json.loads(line) for line in lines]
    # Reverse chronological: feature_b first.
    assert payloads[0]["cl_name"] == "feature_b"
    assert payloads[1]["cl_name"] == "feature_a"


def test_logging_helpers_swallow_exceptions() -> None:
    """A broken log writer must never break a revival."""
    agent = _make_agent()
    with patch("sase.logs.run_log.log_event", side_effect=OSError("disk full")):
        log_revive_started(agents=[agent])
        log_revive_success(agent=agent)
        log_revive_failure(stage="artifact_restore", agent=agent, error=ValueError("x"))

"""Tests for killed agent iteration user/external classification."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from sase.agent.staged_handoff import (
    STAGED_HANDOFF_RESPONSE_FILENAME,
    build_plan_staged_record,
    read_staged_handoff,
    write_staged_handoff,
    write_staged_handoff_response,
)
from sase.agent.user_kill import USER_KILL_INTENT_MARKER
from sase.axe.run_agent_exec import LoopState, _handle_killed_iteration

from tests._axe_run_agent_exec_helpers import make_exec_ctx


def _state(artifacts_dir: Path) -> LoopState:
    return LoopState(
        current_prompt="prompt",
        current_role_suffix="",
        current_artifacts_dir=str(artifacts_dir),
        loop_outcome="completed",
        sdd_spec_path=None,
        original_prompt="prompt",
    )


def _write_marker(artifacts_dir: Path, name: str, data: dict[str, object]) -> None:
    (artifacts_dir / name).write_text(json.dumps(data), encoding="utf-8")


def _write_pending_call(artifacts_dir: Path) -> None:
    record = {
        "schema_version": 2,
        "recorded_at": "1970-01-01T00:01:39+00:00",
        "runtime": "codex",
        "source": "stream",
        "event": "ToolUse",
        "status": "pending",
        "tool_name": "Bash",
        "tool_use_id": "propose-call",
        "session_id": "session-1",
    }
    (artifacts_dir / "tool_calls.jsonl").write_text(
        json.dumps(record) + "\n", encoding="utf-8"
    )


def _tool_call_records(artifacts_dir: Path) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in (artifacts_dir / "tool_calls.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]


def test_pending_plan_marker_is_not_adopted_on_external_kill(tmp_path: Path) -> None:
    ctx = make_exec_ctx(tmp_path, is_home_mode=False)
    artifacts = Path(ctx.artifacts_dir)
    state = _state(artifacts)
    _write_marker(
        artifacts,
        ".sase_plan_pending",
        {"plan_file": "/tmp/plan.md", "timestamp": 99.0},
    )
    _write_pending_call(artifacts)

    with patch("sase.axe.run_agent_exec.killed_at", return_value=100.0):
        outcome = _handle_killed_iteration(ctx, state)

    assert outcome == "killed"
    assert (artifacts / ".sase_plan_pending").exists()
    result = _tool_call_records(artifacts)[-1]
    assert result["event"] == "ToolResult"
    assert result["status"] == "interrupted"
    assert result["completed_at"] == "1970-01-01T00:01:40+00:00"


def test_pending_monitor_marker_is_not_adopted_on_external_kill(tmp_path: Path) -> None:
    ctx = make_exec_ctx(tmp_path, is_home_mode=False)
    artifacts = Path(ctx.artifacts_dir)
    state = _state(artifacts)
    _write_marker(
        artifacts,
        ".sase_monitor_pending",
        {
            "monitor_id": "m123",
            "member_artifacts_dir": "/tmp/member",
            "member_agent_name": "agent--mon",
            "timestamp": 99.0,
        },
    )

    with patch("sase.axe.run_agent_exec.killed_at", return_value=100.0):
        outcome = _handle_killed_iteration(ctx, state)

    assert outcome == "killed"
    assert (artifacts / ".sase_monitor_pending").exists()


def test_pending_pipe_marker_is_not_adopted_on_external_kill(tmp_path: Path) -> None:
    ctx = make_exec_ctx(tmp_path, is_home_mode=False)
    artifacts = Path(ctx.artifacts_dir)
    state = _state(artifacts)
    _write_marker(
        artifacts,
        ".sase_pipe_pending",
        {
            "prompt": "continue the work",
            "reason": "hand off",
            "model": None,
            "name_token": None,
            "fresh": False,
            "pipe_depth": 0,
            "timestamp": 99.0,
        },
    )

    with patch("sase.axe.run_agent_exec.killed_at", return_value=100.0):
        outcome = _handle_killed_iteration(ctx, state)

    assert outcome == "killed"
    assert (artifacts / ".sase_pipe_pending").exists()


def test_user_kill_discards_staged_and_pending(
    tmp_path: Path,
    monkeypatch,
) -> None:
    ctx = make_exec_ctx(tmp_path, is_home_mode=False)
    artifacts = Path(ctx.artifacts_dir)
    state = _state(artifacts)
    monkeypatch.setenv("SASE_AGENT", "1")
    staged_record = build_plan_staged_record(
        plan_file="/tmp/plan.md",
        original_file="/tmp/scratch.md",
        dirty_obligations_at_stage=[],
        staged_id="aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee",
        created_at="2026-10-28T12:00:00Z",
    )
    write_staged_handoff(staged_record, artifacts_dir=str(artifacts))
    write_staged_handoff_response(
        str(staged_record["staged_id"]),
        "planner response",
        artifacts_dir=str(artifacts),
    )
    _write_marker(
        artifacts,
        USER_KILL_INTENT_MARKER,
        {"schema_version": 1, "timestamp": 50.0, "pid": 123, "source": "test"},
    )
    _write_pending_call(artifacts)
    _write_marker(
        artifacts,
        ".sase_plan_pending",
        {"plan_file": "/tmp/plan.md", "timestamp": 49.0},
    )

    with patch("sase.axe.run_agent_exec.killed_at", return_value=100.0):
        outcome = _handle_killed_iteration(ctx, state)

    assert outcome == "killed"
    assert (artifacts / USER_KILL_INTENT_MARKER).exists()
    assert not (artifacts / ".sase_plan_pending").exists()
    assert read_staged_handoff(str(artifacts)) is None
    assert not (artifacts / STAGED_HANDOFF_RESPONSE_FILENAME).exists()
    result = _tool_call_records(artifacts)[-1]
    assert result["event"] == "ToolResult"
    assert result["status"] == "interrupted"


def test_hijack_intent_returns_hijacked_and_discards_markers(
    tmp_path: Path,
    monkeypatch,
) -> None:
    ctx = make_exec_ctx(tmp_path, is_home_mode=False)
    state = _state(Path(ctx.artifacts_dir))
    artifacts = Path(ctx.artifacts_dir)
    monkeypatch.setenv("SASE_AGENT", "1")
    staged_record = build_plan_staged_record(
        plan_file="/tmp/plan.md",
        original_file="/tmp/scratch.md",
        dirty_obligations_at_stage=[],
        staged_id="aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee",
        created_at="2026-10-28T12:00:00Z",
    )
    write_staged_handoff(staged_record, artifacts_dir=str(artifacts))
    write_staged_handoff_response(
        str(staged_record["staged_id"]),
        "planner response",
        artifacts_dir=str(artifacts),
    )
    _write_marker(
        artifacts,
        USER_KILL_INTENT_MARKER,
        {
            "schema_version": 1,
            "timestamp": 50.0,
            "pid": 123,
            "source": "test",
            "mode": "hijack",
            "hijack_id": "h-1",
        },
    )
    _write_pending_call(artifacts)
    _write_marker(
        artifacts,
        ".sase_plan_pending",
        {"plan_file": "/tmp/plan.md", "timestamp": 49.0},
    )

    with patch("sase.axe.run_agent_exec.killed_at", return_value=100.0):
        outcome = _handle_killed_iteration(ctx, state)

    assert outcome == "hijacked"
    assert (artifacts / USER_KILL_INTENT_MARKER).exists()
    assert not (artifacts / ".sase_plan_pending").exists()
    assert read_staged_handoff(str(artifacts)) is None
    assert not (artifacts / STAGED_HANDOFF_RESPONSE_FILENAME).exists()
    result = _tool_call_records(artifacts)[-1]
    assert result["event"] == "ToolResult"
    assert result["status"] == "interrupted"


def test_user_kill_intent_discards_monitor_marker(tmp_path: Path) -> None:
    ctx = make_exec_ctx(tmp_path, is_home_mode=False)
    artifacts = Path(ctx.artifacts_dir)
    state = _state(artifacts)
    _write_marker(
        artifacts,
        USER_KILL_INTENT_MARKER,
        {"schema_version": 1, "timestamp": 50.0, "pid": 123, "source": "test"},
    )
    _write_marker(
        artifacts,
        ".sase_monitor_pending",
        {
            "monitor_id": "m123",
            "member_artifacts_dir": "/tmp/member",
            "member_agent_name": "agent--mon",
            "timestamp": 49.0,
        },
    )

    with patch("sase.axe.run_agent_exec.killed_at", return_value=100.0):
        outcome = _handle_killed_iteration(ctx, state)

    assert outcome == "killed"
    assert (artifacts / USER_KILL_INTENT_MARKER).exists()
    assert not (artifacts / ".sase_monitor_pending").exists()


def test_user_kill_intent_discards_pipe_marker(tmp_path: Path) -> None:
    ctx = make_exec_ctx(tmp_path, is_home_mode=False)
    artifacts = Path(ctx.artifacts_dir)
    state = _state(artifacts)
    _write_marker(
        artifacts,
        USER_KILL_INTENT_MARKER,
        {"schema_version": 1, "timestamp": 50.0, "pid": 123, "source": "test"},
    )
    _write_marker(
        artifacts,
        ".sase_pipe_pending",
        {"prompt": "continue the work", "timestamp": 49.0},
    )

    with patch("sase.axe.run_agent_exec.killed_at", return_value=100.0):
        outcome = _handle_killed_iteration(ctx, state)

    assert outcome == "killed"
    assert (artifacts / USER_KILL_INTENT_MARKER).exists()
    assert not (artifacts / ".sase_pipe_pending").exists()


def test_external_kill_leaves_staged_record(
    tmp_path: Path,
    monkeypatch,
) -> None:
    ctx = make_exec_ctx(tmp_path, is_home_mode=False)
    artifacts = Path(ctx.artifacts_dir)
    state = _state(artifacts)
    monkeypatch.setenv("SASE_AGENT", "1")
    staged_record = build_plan_staged_record(
        plan_file="/tmp/plan.md",
        original_file="/tmp/scratch.md",
        dirty_obligations_at_stage=[],
        staged_id="aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee",
        created_at="2026-10-28T12:00:00Z",
    )
    write_staged_handoff(staged_record, artifacts_dir=str(artifacts))

    with patch("sase.axe.run_agent_exec.killed_at", return_value=100.0):
        outcome = _handle_killed_iteration(ctx, state)

    assert outcome == "killed"
    assert read_staged_handoff(str(artifacts)) is not None

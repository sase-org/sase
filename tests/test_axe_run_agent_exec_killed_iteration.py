"""Tests for killed agent iteration handoff classification."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

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


def test_plan_marker_older_than_sigterm_is_handoff(tmp_path: Path) -> None:
    ctx = make_exec_ctx(tmp_path, is_home_mode=False)
    state = _state(Path(ctx.artifacts_dir))
    _write_marker(
        Path(ctx.artifacts_dir),
        ".sase_plan_pending",
        {"plan_file": "/tmp/plan.md", "timestamp": 99.0},
    )
    _write_pending_call(Path(ctx.artifacts_dir))

    with (
        patch("sase.axe.run_agent_exec.killed_at", return_value=100.0),
        patch("sase.axe.run_agent_exec.handle_plan_marker", return_value=None) as plan,
    ):
        outcome = _handle_killed_iteration(ctx, state)

    assert outcome is None
    plan.assert_called_once()
    marker = plan.call_args.args[0]
    assert marker == {"plan_file": "/tmp/plan.md", "timestamp": 99.0}
    result = _tool_call_records(Path(ctx.artifacts_dir))[-1]
    assert result["event"] == "ToolResult"
    assert result["status"] == "interrupted"
    assert result["completed_at"] == "1970-01-01T00:01:40+00:00"


def test_plan_marker_newer_than_sigterm_is_ignored_as_user_kill(
    tmp_path: Path,
) -> None:
    ctx = make_exec_ctx(tmp_path, is_home_mode=False)
    state = _state(Path(ctx.artifacts_dir))
    marker_path = Path(ctx.artifacts_dir) / ".sase_plan_pending"
    _write_marker(
        Path(ctx.artifacts_dir),
        marker_path.name,
        {"plan_file": "/tmp/plan.md", "timestamp": 101.0},
    )

    with (
        patch("sase.axe.run_agent_exec.killed_at", return_value=100.0),
        patch("sase.axe.run_agent_exec.handle_plan_marker") as plan,
    ):
        outcome = _handle_killed_iteration(ctx, state)

    assert outcome == "killed"
    plan.assert_not_called()
    assert not marker_path.exists()


def test_monitor_marker_older_than_sigterm_is_handoff(tmp_path: Path) -> None:
    ctx = make_exec_ctx(tmp_path, is_home_mode=False)
    state = _state(Path(ctx.artifacts_dir))
    _write_marker(
        Path(ctx.artifacts_dir),
        ".sase_monitor_pending",
        {
            "monitor_id": "m123",
            "member_artifacts_dir": "/tmp/member",
            "member_agent_name": "agent--mon",
            "timestamp": 99.0,
        },
    )

    with (
        patch("sase.axe.run_agent_exec.killed_at", return_value=100.0),
        patch(
            "sase.axe.run_agent_exec.handle_monitor_marker",
            return_value="monitored",
        ) as monitor,
    ):
        outcome = _handle_killed_iteration(ctx, state)

    assert outcome == "monitored"
    monitor.assert_called_once()
    marker = monitor.call_args.args[0]
    assert marker["monitor_id"] == "m123"


def test_monitor_marker_newer_than_sigterm_is_ignored_as_user_kill(
    tmp_path: Path,
) -> None:
    ctx = make_exec_ctx(tmp_path, is_home_mode=False)
    state = _state(Path(ctx.artifacts_dir))
    marker_path = Path(ctx.artifacts_dir) / ".sase_monitor_pending"
    _write_marker(
        Path(ctx.artifacts_dir),
        marker_path.name,
        {
            "monitor_id": "m123",
            "member_artifacts_dir": "/tmp/member",
            "member_agent_name": "agent--mon",
            "timestamp": 101.0,
        },
    )

    with (
        patch("sase.axe.run_agent_exec.killed_at", return_value=100.0),
        patch("sase.axe.run_agent_exec.handle_monitor_marker") as monitor,
    ):
        outcome = _handle_killed_iteration(ctx, state)

    assert outcome == "killed"
    monitor.assert_not_called()
    assert not marker_path.exists()


def test_user_kill_intent_wins_over_plan_marker(tmp_path: Path) -> None:
    ctx = make_exec_ctx(tmp_path, is_home_mode=False)
    state = _state(Path(ctx.artifacts_dir))
    artifacts = Path(ctx.artifacts_dir)
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

    with (
        patch("sase.axe.run_agent_exec.killed_at", return_value=100.0),
        patch("sase.axe.run_agent_exec.handle_plan_marker") as plan,
    ):
        outcome = _handle_killed_iteration(ctx, state)

    assert outcome == "killed"
    plan.assert_not_called()
    assert (artifacts / USER_KILL_INTENT_MARKER).exists()
    assert not (artifacts / ".sase_plan_pending").exists()
    result = _tool_call_records(artifacts)[-1]
    assert result["event"] == "ToolResult"
    assert result["status"] == "interrupted"


def test_user_kill_intent_discards_monitor_marker(tmp_path: Path) -> None:
    ctx = make_exec_ctx(tmp_path, is_home_mode=False)
    state = _state(Path(ctx.artifacts_dir))
    artifacts = Path(ctx.artifacts_dir)
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

    with (
        patch("sase.axe.run_agent_exec.killed_at", return_value=100.0),
        patch("sase.axe.run_agent_exec.handle_monitor_marker") as monitor,
    ):
        outcome = _handle_killed_iteration(ctx, state)

    assert outcome == "killed"
    monitor.assert_not_called()
    assert (artifacts / USER_KILL_INTENT_MARKER).exists()
    assert not (artifacts / ".sase_monitor_pending").exists()


def test_pipe_marker_older_than_sigterm_is_handoff(tmp_path: Path) -> None:
    ctx = make_exec_ctx(tmp_path, is_home_mode=False)
    state = _state(Path(ctx.artifacts_dir))
    _write_marker(
        Path(ctx.artifacts_dir),
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

    with (
        patch("sase.axe.run_agent_exec.killed_at", return_value=100.0),
        patch("sase.axe.run_agent_exec.handle_pipe_marker", return_value=None) as pipe,
    ):
        outcome = _handle_killed_iteration(ctx, state)

    assert outcome is None
    pipe.assert_called_once()
    marker = pipe.call_args.args[0]
    assert marker["prompt"] == "continue the work"


def test_pipe_marker_newer_than_sigterm_is_ignored_as_user_kill(
    tmp_path: Path,
) -> None:
    ctx = make_exec_ctx(tmp_path, is_home_mode=False)
    state = _state(Path(ctx.artifacts_dir))
    marker_path = Path(ctx.artifacts_dir) / ".sase_pipe_pending"
    _write_marker(
        Path(ctx.artifacts_dir),
        marker_path.name,
        {
            "prompt": "continue the work",
            "timestamp": 101.0,
        },
    )

    with (
        patch("sase.axe.run_agent_exec.killed_at", return_value=100.0),
        patch("sase.axe.run_agent_exec.handle_pipe_marker") as pipe,
    ):
        outcome = _handle_killed_iteration(ctx, state)

    assert outcome == "killed"
    pipe.assert_not_called()
    assert not marker_path.exists()


def test_user_kill_intent_discards_pipe_marker(tmp_path: Path) -> None:
    ctx = make_exec_ctx(tmp_path, is_home_mode=False)
    state = _state(Path(ctx.artifacts_dir))
    artifacts = Path(ctx.artifacts_dir)
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

    with (
        patch("sase.axe.run_agent_exec.killed_at", return_value=100.0),
        patch("sase.axe.run_agent_exec.handle_pipe_marker") as pipe,
    ):
        outcome = _handle_killed_iteration(ctx, state)

    assert outcome == "killed"
    pipe.assert_not_called()
    assert (artifacts / USER_KILL_INTENT_MARKER).exists()
    assert not (artifacts / ".sase_pipe_pending").exists()

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


def test_plan_marker_older_than_sigterm_is_handoff(tmp_path: Path) -> None:
    ctx = make_exec_ctx(tmp_path, is_home_mode=False)
    state = _state(Path(ctx.artifacts_dir))
    _write_marker(
        Path(ctx.artifacts_dir),
        ".sase_plan_pending",
        {"plan_file": "/tmp/plan.md", "timestamp": 99.0},
    )

    with (
        patch("sase.axe.run_agent_exec.killed_at", return_value=100.0),
        patch("sase.axe.run_agent_exec.handle_plan_marker", return_value=None) as plan,
    ):
        outcome = _handle_killed_iteration(ctx, state)

    assert outcome is None
    plan.assert_called_once()


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


def test_user_kill_intent_wins_over_plan_marker(tmp_path: Path) -> None:
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

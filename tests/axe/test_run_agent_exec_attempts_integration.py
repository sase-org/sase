"""Integration tests: retry flow writes attempts/<N>/ snapshots."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from sase.axe.run_agent_exec import AgentExecContext, LoopState
from sase.axe.run_agent_exec_retry import RetryTracker, handle_workflow_error
from sase.llm_provider.retry_config import ProviderRetryConfig


def _make_ctx(tmp_path: Path) -> AgentExecContext:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    return AgentExecContext(
        cl_name="test-cl",
        project_file=str(tmp_path / "project.gp"),
        workspace_dir=str(tmp_path),
        output_path=str(tmp_path / "output.log"),
        workspace_num=1,
        timestamp="20260422_120000",
        update_target="",
        project_name="sase",
        is_home_mode=False,
        artifacts_dir=str(artifacts),
        artifacts_timestamp="20260422_120000",
        vcs_tag=None,
        agent_name="agent",
        agent_model="claude-sonnet-4-5",
        agent_llm_provider="claude",
        agent_vcs_provider=None,
        agent_hidden=False,
        agent_meta={},
        local_xprompts={},
    )


def _make_state(ctx: AgentExecContext, prompt: str = "Do the work.") -> LoopState:
    return LoopState(
        current_prompt=prompt,
        current_role_suffix="",
        current_artifacts_dir=ctx.artifacts_dir,
        loop_outcome="completed",
        sdd_spec_path=None,
        original_prompt=prompt,
    )


def _retry_cfg(max_retries: int = 2) -> ProviderRetryConfig:
    return ProviderRetryConfig(
        max_retries=max_retries,
        error_patterns=["Prompt is too long"],
        wait_times=[0],
    )


def _fallback_cfg() -> ProviderRetryConfig:
    return ProviderRetryConfig(
        max_retries=0,
        error_patterns=["Prompt is too long"],
        wait_times=[0],
        fallback_model="backup-model",
    )


def _pump_reply_bytes(artifacts_dir: Path, content: str) -> None:
    """Simulate the subprocess streaming some bytes before failing."""
    (artifacts_dir / "live_reply.md").write_text(content, encoding="utf-8")
    (artifacts_dir / "live_reply_timestamps.jsonl").write_text(
        '{"byte_offset": 0, "timestamp": "2026-04-22T12:00:00+00:00"}\n',
        encoding="utf-8",
    )


def test_retry_branch_snapshots_failed_attempt(tmp_path: Path) -> None:
    ctx = _make_ctx(tmp_path)
    state = _make_state(ctx)
    tracker = RetryTracker(retry_cfg=_retry_cfg())
    _pump_reply_bytes(Path(ctx.artifacts_dir), "attempt 1 partial output")

    with (
        patch("sase.axe.run_agent_exec_retry.time.sleep", MagicMock()),
        patch("sase.axe.run_agent_exec_retry.was_killed", return_value=False),
        patch("sase.axe.run_agent_exec_retry.prepare_workspace", MagicMock()),
    ):
        action = handle_workflow_error(
            RuntimeError("API Error: 400 - Prompt is too long"),
            tracker,
            ctx,
            state,
        )

    assert action == "continue"
    snap = Path(ctx.artifacts_dir) / "attempts" / "01" / "attempt_meta.json"
    assert snap.exists()
    meta = json.loads(snap.read_text())
    assert meta["attempt_number"] == 1
    assert meta["status"] == "failed"
    assert meta["model"] == "claude-sonnet-4-5"
    assert meta["used_fallback"] is False

    # The preserved reply content matches what was streamed pre-retry.
    snap_reply = Path(ctx.artifacts_dir) / "attempts" / "01" / "live_reply.md"
    assert snap_reply.read_text() == "attempt 1 partial output"
    # Root file is truncated so attempt 2 streams into a clean slate.
    assert (Path(ctx.artifacts_dir) / "live_reply.md").read_text() == ""


def test_exhausted_retries_snapshots_final_as_raised(tmp_path: Path) -> None:
    ctx = _make_ctx(tmp_path)
    state = _make_state(ctx)
    tracker = RetryTracker(retry_cfg=_retry_cfg(max_retries=1), retry_count=1)
    _pump_reply_bytes(Path(ctx.artifacts_dir), "final attempt output")

    with (
        patch("sase.axe.run_agent_exec_retry.time.sleep", MagicMock()),
        patch("sase.axe.run_agent_exec_retry.was_killed", return_value=False),
        patch("sase.axe.run_agent_exec_retry.prepare_workspace", MagicMock()),
    ):
        action = handle_workflow_error(
            RuntimeError("Prompt is too long"), tracker, ctx, state
        )

    assert action == "raise"
    # retry_count+1 = attempt 2 — the final failed attempt
    snap = Path(ctx.artifacts_dir) / "attempts" / "02" / "attempt_meta.json"
    assert snap.exists()
    meta = json.loads(snap.read_text())
    assert meta["status"] == "raised"


def test_fallback_branch_snapshots_with_primary_model_marker(tmp_path: Path) -> None:
    ctx = _make_ctx(tmp_path)
    state = _make_state(ctx)
    # max_retries=0 routes straight to fallback branch.
    tracker = RetryTracker(retry_cfg=_fallback_cfg())
    _pump_reply_bytes(Path(ctx.artifacts_dir), "primary-model attempt output")

    with (
        patch("sase.axe.run_agent_exec_retry.time.sleep", MagicMock()),
        patch("sase.axe.run_agent_exec_retry.was_killed", return_value=False),
        patch("sase.axe.run_agent_exec_retry.prepare_workspace", MagicMock()),
    ):
        action = handle_workflow_error(
            RuntimeError("Prompt is too long"), tracker, ctx, state
        )

    assert action == "continue"
    assert tracker.using_fallback is True
    snap = Path(ctx.artifacts_dir) / "attempts" / "01" / "attempt_meta.json"
    meta = json.loads(snap.read_text())
    # The attempt that triggered fallback ran on the PRIMARY model, so
    # used_fallback at snapshot time is False.
    assert meta["used_fallback"] is False

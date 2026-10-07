"""Integration tests: retry flow writes attempts/<N>/ snapshots."""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sase.axe.run_agent_exec import AgentExecContext, LoopState
from sase.axe.run_agent_exec_retry import RetryTracker, handle_workflow_error
from sase.llm_provider.retry_config import ProviderRetryConfig


@pytest.fixture(autouse=True)
def _restore_model_override_env():
    original = os.environ.get("SASE_MODEL_OVERRIDE")
    yield
    if original is None:
        os.environ.pop("SASE_MODEL_OVERRIDE", None)
    else:
        os.environ["SASE_MODEL_OVERRIDE"] = original


def _make_ctx(tmp_path: Path) -> AgentExecContext:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    return AgentExecContext(
        cl_name="test-cl",
        project_file=str(tmp_path / "project.sase"),
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
        local_macros={},
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
    snap_continuation = Path(ctx.artifacts_dir) / "attempts" / "01" / "continuation"
    assert (snap_continuation / "manifest.json").exists()
    attempt_manifest = json.loads(
        (snap_continuation / "manifest.json").read_text(encoding="utf-8")
    )
    assert attempt_manifest["status"] == "failed"
    # Root file is truncated so attempt 2 streams into a clean slate.
    assert (Path(ctx.artifacts_dir) / "live_reply.md").read_text() == ""
    assert (Path(ctx.artifacts_dir) / "continuation" / "workspace_facts.json").exists()


def test_retry_branch_releases_attempt_continuation_pointers(tmp_path: Path) -> None:
    from sase.continuation_capture import persist_agent_delta

    ctx = _make_ctx(tmp_path)
    artifacts = Path(ctx.artifacts_dir)
    (artifacts / "agent_meta.json").write_text(
        json.dumps(
            {
                "name": "agent",
                "continuation_parent_node_ids": ["agent-delta:launch:parent"],
                "continuation_node_id": "agent-delta:stale:attempt1",
                "continuation_node_ref": "local:continuation/nodes/stale.json",
                "continuation_manifest_ref": "local:continuation/manifest.json",
            }
        ),
        encoding="utf-8",
    )
    state = _make_state(ctx)
    state.continuation_node_id = "agent-delta:stale:attempt1"
    state.continuation_manifest_ref = "local:continuation/manifest.json"
    tracker = RetryTracker(retry_cfg=_retry_cfg())
    _pump_reply_bytes(artifacts, "attempt 1 partial output")

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
    meta = json.loads((artifacts / "agent_meta.json").read_text(encoding="utf-8"))
    assert "continuation_node_id" not in meta
    assert "continuation_node_ref" not in meta
    assert "continuation_manifest_ref" not in meta
    assert meta["continuation_parent_node_ids"] == ["agent-delta:launch:parent"]
    assert state.continuation_node_id is None

    attempt_manifest = json.loads(
        (artifacts / "attempts" / "01" / "continuation" / "manifest.json").read_text(
            encoding="utf-8"
        )
    )
    published = persist_agent_delta(
        ctx,
        state,
        status="completed",
        final_response="ATTEMPT_2_DONE",
    )
    node = json.loads(
        (artifacts / "continuation" / "nodes" / f"{published.node_id}.json").read_text(
            encoding="utf-8"
        )
    )
    assert node["parent_ids"] == ["agent-delta:launch:parent"]
    assert attempt_manifest["node_id"] not in node["parent_ids"]


def test_fallback_branch_releases_attempt_continuation_pointers(
    tmp_path: Path,
) -> None:
    ctx = _make_ctx(tmp_path)
    artifacts = Path(ctx.artifacts_dir)
    (artifacts / "agent_meta.json").write_text(
        json.dumps(
            {
                "name": "agent",
                "continuation_parent_node_ids": ["agent-delta:launch:parent"],
                "continuation_node_id": "agent-delta:stale:attempt1",
                "continuation_node_ref": "local:continuation/nodes/stale.json",
                "continuation_manifest_ref": "local:continuation/manifest.json",
            }
        ),
        encoding="utf-8",
    )
    state = _make_state(ctx)
    state.continuation_node_id = "agent-delta:stale:attempt1"
    state.continuation_manifest_ref = "local:continuation/manifest.json"
    # max_retries=0 routes straight to fallback branch.
    tracker = RetryTracker(retry_cfg=_fallback_cfg())
    _pump_reply_bytes(artifacts, "primary-model attempt output")

    with (
        patch("sase.axe.run_agent_exec_retry.time.sleep", MagicMock()),
        patch("sase.axe.run_agent_exec_retry.was_killed", return_value=False),
        patch("sase.axe.run_agent_exec_retry.prepare_workspace", MagicMock()),
    ):
        action = handle_workflow_error(
            RuntimeError("Prompt is too long"), tracker, ctx, state
        )

    assert action == "continue"
    meta = json.loads((artifacts / "agent_meta.json").read_text(encoding="utf-8"))
    assert "continuation_node_id" not in meta
    assert "continuation_node_ref" not in meta
    assert "continuation_manifest_ref" not in meta
    assert meta["continuation_parent_node_ids"] == ["agent-delta:launch:parent"]
    assert state.continuation_node_id is None


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

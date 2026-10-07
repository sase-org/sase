"""Retry-splice tests for continuation replay."""

from __future__ import annotations

import json
from pathlib import Path

from sase.axe.run_agent_exec import LoopState
from sase.axe.run_agent_exec_attempts import snapshot_attempt
from sase.axe.run_agent_exec_types import AgentExecContext
from sase.continuation_capture import persist_agent_delta
from sase.history.chat_fork.build import build_fork_injected_history as build_fork
from sase.history.chat_fork.continuation import replay_versioned_continuation_history
from tests.history._continuation_replay_hydration_helpers import (
    agent_member,
    publish_agent_delta,
    write_agent_node,
    write_json,
)


def test_legacy_retried_attempt_edge_spliced_from_replay(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "artifacts" / "20260911010101"
    failed = publish_agent_delta(
        tmp_path,
        run_dir,
        name="acme--0",
        prompt="Do the work.",
        response="FAILED_REPLY",
        status="failed",
    )
    snapshot_attempt(
        str(run_dir),
        1,
        status="failed",
        start_epoch=1.0,
        end_epoch=2.0,
        error_full="boom",
        error_snippet="boom",
        model=None,
        used_fallback=False,
    )
    archived_manifest = json.loads(
        (run_dir / "attempts" / "01" / "continuation" / "manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert archived_manifest["node_id"] == failed.node_id
    # Old writer shape: the completed retry node is parented on the archived
    # failed attempt.
    write_agent_node(
        run_dir,
        name="acme--0",
        node_id="agent-delta-retry-completed",
        parents=[failed.node_id],
        prompt="Do the work.",
        response="COMPLETED_REPLY",
    )

    source = agent_member(tmp_path, "20260911010101", "acme--0")
    result = replay_versioned_continuation_history([source])

    assert result is not None
    assert result.refusals == ()
    kinds = {omission.get("kind") for omission in result.manifest.get("omissions", [])}
    assert "missing_parent" not in kinds
    assert "COMPLETED_REPLY" in result.rendered
    assert "FAILED_REPLY" not in result.rendered
    build_fork([source], automatic=True)


def test_multi_attempt_chain_spliced_recursively(tmp_path: Path) -> None:
    run_dir = tmp_path / "artifacts" / "20260911010101"
    first = publish_agent_delta(
        tmp_path,
        run_dir,
        name="acme--0",
        prompt="Do the work.",
        response="FIRST_REPLY",
        status="failed",
    )
    snapshot_attempt(
        str(run_dir),
        1,
        status="failed",
        start_epoch=1.0,
        end_epoch=2.0,
        error_full="boom",
        error_snippet="boom",
        model=None,
        used_fallback=False,
    )
    write_agent_node(
        run_dir,
        name="acme--0",
        node_id="agent-delta-retry-second",
        parents=[first.node_id],
        prompt="Do the work.",
        response="SECOND_REPLY",
    )
    snapshot_attempt(
        str(run_dir),
        2,
        status="failed",
        start_epoch=3.0,
        end_epoch=4.0,
        error_full="boom again",
        error_snippet="boom again",
        model=None,
        used_fallback=False,
    )
    write_agent_node(
        run_dir,
        name="acme--0",
        node_id="agent-delta-retry-third",
        parents=["agent-delta-retry-second"],
        prompt="Do the work.",
        response="THIRD_REPLY",
    )

    source = agent_member(tmp_path, "20260911010101", "acme--0")
    result = replay_versioned_continuation_history([source])

    assert result is not None
    assert result.refusals == ()
    assert "THIRD_REPLY" in result.rendered
    assert "FIRST_REPLY" not in result.rendered
    assert "SECOND_REPLY" not in result.rendered
    build_fork([source], automatic=True)


def test_superseded_splice_preserves_launch_ancestry(tmp_path: Path) -> None:
    artifacts = tmp_path / "artifacts"
    base_dir = artifacts / "20260911010101"
    run_dir = artifacts / "20260911010202"
    publish_agent_delta(
        tmp_path,
        base_dir,
        name="acme--0",
        prompt="Keep BASE_CONSTRAINT in every successor.",
        response="BASE_REPLY",
    )
    base_id = json.loads(
        (base_dir / "continuation" / "manifest.json").read_text(encoding="utf-8")
    )["node_id"]
    failed = publish_agent_delta(
        tmp_path,
        run_dir,
        name="acme--1",
        prompt="Continue from the stored base.",
        response="FAILED_REPLY",
        parents=[base_id],
        status="failed",
    )
    snapshot_attempt(
        str(run_dir),
        1,
        status="failed",
        start_epoch=1.0,
        end_epoch=2.0,
        error_full="boom",
        error_snippet="boom",
        model=None,
        used_fallback=False,
    )
    write_agent_node(
        run_dir,
        name="acme--1",
        node_id="agent-delta-retry-completed",
        parents=[failed.node_id],
        prompt="Continue from the stored base.",
        response="COMPLETED_REPLY",
    )

    source = agent_member(tmp_path, "20260911010202", "acme--1")
    result = replay_versioned_continuation_history([source])

    assert result is not None
    assert result.refusals == ()
    assert "BASE_REPLY" in result.rendered
    assert "COMPLETED_REPLY" in result.rendered
    assert "FAILED_REPLY" not in result.rendered
    assert result.rendered.index("BASE_REPLY") < result.rendered.index(
        "COMPLETED_REPLY"
    )
    build_fork([source], automatic=True)


def test_retry_then_fork_replay_end_to_end(tmp_path: Path) -> None:
    from unittest.mock import MagicMock, patch

    from sase.axe.run_agent_exec_retry import RetryTracker, handle_workflow_error
    from sase.llm_provider.retry_config import ProviderRetryConfig

    run_dir = tmp_path / "artifacts" / "20260911010101"
    run_dir.mkdir(parents=True)
    write_json(
        run_dir / "agent_meta.json",
        {
            "name": "acme--0",
            "continuation_parent_node_ids": [],
        },
    )
    ctx = AgentExecContext(
        cl_name="test-cl",
        project_file=str(tmp_path / "project.sase"),
        workspace_dir=str(tmp_path),
        output_path=str(tmp_path / "output.log"),
        workspace_num=1,
        timestamp="20260911010101",
        update_target="",
        project_name="sase",
        is_home_mode=False,
        artifacts_dir=str(run_dir),
        artifacts_timestamp="20260911010101",
        vcs_tag=None,
        agent_name="acme--0",
        agent_model="claude-sonnet-4-5",
        agent_llm_provider="claude",
        agent_vcs_provider=None,
        agent_hidden=False,
        agent_meta={"continuation_parent_node_ids": []},
        local_macros={},
    )
    state = LoopState(
        current_prompt="Do the work.",
        current_role_suffix="",
        current_artifacts_dir=str(run_dir),
        loop_outcome="completed",
        sdd_spec_path=None,
        original_prompt="Do the work.",
    )
    tracker = RetryTracker(
        retry_cfg=ProviderRetryConfig(
            max_retries=2,
            error_patterns=["Prompt is too long"],
            wait_times=[0],
        )
    )
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

    published = persist_agent_delta(
        ctx,
        state,
        status="completed",
        final_response="RETRY_COMPLETED_REPLY",
    )
    assert published.node_id
    source = agent_member(tmp_path, "20260911010101", "acme--0")
    result = replay_versioned_continuation_history([source])

    assert result is not None
    assert result.refusals == ()
    assert "RETRY_COMPLETED_REPLY" in result.rendered
    build_fork([source], automatic=True)

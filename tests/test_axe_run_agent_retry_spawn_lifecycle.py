"""Retry-spawn lifecycle tests outside the core handoff path."""

from __future__ import annotations

import json
from pathlib import Path


# ---------------------------------------------------------------------------
# Workspace claim transfer
# ---------------------------------------------------------------------------


class TestTransferWorkspaceClaim:
    def test_updates_pid_workflow_and_timestamp_in_place(self, tmp_path: Path) -> None:
        from sase.running_field import (
            claim_workspace,
            get_claimed_workspaces,
            transfer_workspace_claim,
        )

        project_file = str(tmp_path / "project.sase")
        Path(project_file).write_text("")

        assert claim_workspace(
            project_file,
            workspace_num=42,
            workflow="ace(run)-260424_120000",
            pid=11111,
            cl_name="branch-x",
            artifacts_timestamp="20260424120000",
        ).success

        ok = transfer_workspace_claim(
            project_file,
            workspace_num=42,
            from_pid=11111,
            to_pid=22222,
            new_workflow="ace(run)-260424_130000",
            new_artifacts_timestamp="20260424130000",
            cl_name="branch-x",
        )
        assert ok.success is True

        claims = get_claimed_workspaces(project_file)
        assert len(claims) == 1
        c = claims[0]
        assert c.workspace_num == 42
        assert c.pid == 22222
        assert c.workflow == "ace(run)-260424_130000"
        assert c.artifacts_timestamp == "20260424130000"
        assert c.cl_name == "branch-x"

    def test_returns_false_when_no_match(self, tmp_path: Path) -> None:
        from sase.running_field import (
            claim_workspace,
            transfer_workspace_claim,
        )

        project_file = str(tmp_path / "project.sase")
        Path(project_file).write_text("")
        assert claim_workspace(
            project_file,
            workspace_num=42,
            workflow="ace(run)-x",
            pid=11111,
            cl_name="branch-x",
            artifacts_timestamp="20260424120000",
        ).success
        # Wrong from_pid -> returns failure ClaimResult with reason, no change
        ok = transfer_workspace_claim(
            project_file,
            workspace_num=42,
            from_pid=99999,
            to_pid=22222,
            new_workflow="ace(run)-y",
            new_artifacts_timestamp="20260424130000",
            cl_name="branch-x",
        )
        assert ok.success is False
        assert ok.error is not None


# ---------------------------------------------------------------------------
# Agent loader builds retry_chain_siblings linkage
# ---------------------------------------------------------------------------


class TestAgentLoaderRetryChain:
    def test_chain_linkage_built_after_load(self) -> None:
        from sase.ace.tui.models.agent_loader import _apply_status_overrides
        from sase.ace.tui.models.agent import Agent, AgentType

        parent = Agent(
            agent_type=AgentType.RUNNING,
            cl_name="branch-x",
            project_file="/tmp/p.sase",
            status="FAILED (RETRIED)",
            start_time=None,
            raw_suffix="20260424120000",
            retried_as_timestamp="20260424130000",
        )
        child1 = Agent(
            agent_type=AgentType.RUNNING,
            cl_name="branch-x",
            project_file="/tmp/p.sase",
            status="FAILED (RETRIED)",
            start_time=None,
            raw_suffix="20260424130000",
            retry_of_timestamp="20260424120000",
            retry_attempt=1,
            retry_chain_root_timestamp="20260424120000",
            retried_as_timestamp="20260424140000",
        )
        child2 = Agent(
            agent_type=AgentType.RUNNING,
            cl_name="branch-x",
            project_file="/tmp/p.sase",
            status="RUNNING",
            start_time=None,
            raw_suffix="20260424140000",
            retry_of_timestamp="20260424130000",
            retry_attempt=2,
            retry_chain_root_timestamp="20260424120000",
        )

        _apply_status_overrides([parent, child1, child2])

        # parent has child1 in its retry_chain_siblings
        assert child1 in parent.retry_chain_siblings
        # child1 has child2
        assert child2 in child1.retry_chain_siblings
        # child2 has nothing
        assert child2.retry_chain_siblings == []

    def test_is_retry_attempt_and_is_retried_parent(self) -> None:
        from sase.ace.tui.models.agent import Agent, AgentType

        a = Agent(
            agent_type=AgentType.RUNNING,
            cl_name="x",
            project_file="/p.sase",
            status="RUNNING",
            start_time=None,
            retry_attempt=2,
        )
        assert a.is_retry_attempt is True
        assert a.is_retried_parent is False

        b = Agent(
            agent_type=AgentType.RUNNING,
            cl_name="x",
            project_file="/p.sase",
            status="FAILED (RETRIED)",
            start_time=None,
            retried_as_timestamp="20260424140000",
        )
        assert b.is_retry_attempt is False
        assert b.is_retried_parent is True


# ---------------------------------------------------------------------------
# done.json loader picks up FAILED (RETRIED) status
# ---------------------------------------------------------------------------


class TestDoneJsonRetriedStatus:
    def test_failed_with_retried_as_timestamp_displays_retried_status(
        self, tmp_path: Path
    ) -> None:
        from sase.ace.tui.models._loaders._done_loaders import (
            _load_done_agent_for_dir,
        )

        # Build a done.json artifact dir
        artifact_dir = tmp_path / "20260424120000"
        artifact_dir.mkdir()
        done = {
            "cl_name": "branch-x",
            "project_file": str(tmp_path / "project.sase"),
            "outcome": "failed",
            "workspace_num": 7,
            "output_path": str(tmp_path / "out.log"),
            "error": "Prompt is too long",
            "retried_as_timestamp": "20260424130000",
            "retry_chain_root_timestamp": "20260424120000",
            "retry_error_category": "context_overflow",
        }
        (artifact_dir / "done.json").write_text(json.dumps(done))

        # Bypass the load_json_cached lru_cache by running directly.
        agent = _load_done_agent_for_dir(artifact_dir, "ace-run", {}, {})
        assert agent is not None
        assert agent.status == "FAILED (RETRIED)"
        assert agent.retried_as_timestamp == "20260424130000"
        assert agent.retry_chain_root_timestamp == "20260424120000"
        assert agent.retry_error_category == "context_overflow"

    def test_failed_without_retry_displays_plain_failed(self, tmp_path: Path) -> None:
        from sase.ace.tui.models._loaders._done_loaders import (
            _load_done_agent_for_dir,
        )

        artifact_dir = tmp_path / "20260424120000"
        artifact_dir.mkdir()
        done = {
            "cl_name": "branch-x",
            "project_file": str(tmp_path / "project.sase"),
            "outcome": "failed",
            "workspace_num": 7,
            "output_path": str(tmp_path / "out.log"),
            "error": "Boom",
        }
        (artifact_dir / "done.json").write_text(json.dumps(done))

        agent = _load_done_agent_for_dir(artifact_dir, "ace-run", {}, {})
        assert agent is not None
        assert agent.status == "FAILED"
        assert agent.retried_as_timestamp is None

    def test_plan_rejected_displays_plan_rejected(self, tmp_path: Path) -> None:
        from sase.ace.tui.models._loaders._done_loaders import (
            _load_done_agent_for_dir,
        )

        artifact_dir = tmp_path / "20260424120000"
        artifact_dir.mkdir()
        done = {
            "cl_name": "branch-x",
            "project_file": str(tmp_path / "project.sase"),
            "outcome": "plan_rejected",
            "workspace_num": 7,
            "output_path": str(tmp_path / "out.log"),
        }
        (artifact_dir / "done.json").write_text(json.dumps(done))

        agent = _load_done_agent_for_dir(artifact_dir, "ace-run", {}, {})
        assert agent is not None
        assert agent.status == "PLAN REJECTED"

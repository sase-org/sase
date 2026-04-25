"""Tests for the spawn-on-retry machinery (run_agent_retry_spawn)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from sase.axe.run_agent_exec import AgentExecContext, LoopState
from sase.axe.run_agent_exec_retry import RetryTracker, handle_workflow_error
from sase.axe.run_agent_retry_spawn import (
    RETRY_HANDOFF_FILENAME,
    RetryHandoff,
    _classify_error,
    _build_handoff,
    mark_parent_retried,
)
from sase.llm_provider.retry_config import ProviderRetryConfig


def _make_ctx(tmp_path: Path) -> AgentExecContext:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    return AgentExecContext(
        cl_name="branch-x",
        project_file=str(tmp_path / "project.gp"),
        workspace_dir=str(tmp_path),
        output_path=str(tmp_path / "output.log"),
        workspace_num=7,
        timestamp="260424_120000",
        update_target="trunk",
        project_name="sase",
        is_home_mode=False,
        artifacts_dir=str(artifacts),
        artifacts_timestamp="20260424120000",
        vcs_tag=None,
        agent_name="parent_agent",
        agent_model="opus",
        agent_llm_provider="claude",
        agent_vcs_provider=None,
        agent_hidden=False,
        agent_meta={},
        local_xprompts={},
    )


def _make_state(prompt: str = "Do the work.") -> LoopState:
    return LoopState(
        current_prompt=prompt,
        current_role_suffix="",
        current_artifacts_dir="",
        loop_outcome="completed",
        sdd_spec_path=None,
        original_prompt=prompt,
    )


def _make_tracker(spawn: bool = True) -> RetryTracker:
    cfg = ProviderRetryConfig(
        max_retries=3,
        error_patterns=["Prompt is too long"],
        wait_times=[0],
        continuation_prompt="Resume work.",
        spawn_new_agent=spawn,
    )
    return RetryTracker(retry_cfg=cfg)


# ---------------------------------------------------------------------------
# Error classification
# ---------------------------------------------------------------------------


class TestClassifyError:
    def test_context_overflow(self) -> None:
        assert _classify_error("Prompt is too long for the context limit") == (
            "context_overflow"
        )

    def test_rate_limit(self) -> None:
        assert _classify_error("HTTP 429 rate limit hit") == "rate_limit"

    def test_transient(self) -> None:
        assert _classify_error("503 service overloaded") == "transient"

    def test_other(self) -> None:
        assert _classify_error("disk write failed") == "other"


# ---------------------------------------------------------------------------
# Handoff write/read round-trip
# ---------------------------------------------------------------------------


class TestRetryHandoffRoundTrip:
    def test_writes_then_reads_with_same_fields(self, tmp_path: Path) -> None:
        h = RetryHandoff(
            parent_timestamp="20260424120000",
            retry_attempt=1,
            chain_root_timestamp="20260424120000",
            error_snippet="Prompt is too long",
            error_category="context_overflow",
            continuation_prompt="Resume work.",
            original_prompt="Implement X.",
            chat_path="/tmp/chat.md",
            plan_path=None,
            role_suffix=None,
            workspace_num=7,
            workspace_dir=str(tmp_path),
            vcs_ref=None,
            cl_name="branch-x",
            project_file=str(tmp_path / "project.gp"),
            project_name="sase",
            update_target="trunk",
            is_home_mode=False,
            agent_name="parent_agent",
            agent_model="opus",
            agent_llm_provider="claude",
            agent_vcs_provider=None,
            fallback_model=None,
            use_fallback=False,
        )
        path = h.write_to(str(tmp_path))
        assert path.endswith(RETRY_HANDOFF_FILENAME)

        loaded = RetryHandoff.read_from_path(path)
        assert loaded is not None
        assert loaded.parent_timestamp == "20260424120000"
        assert loaded.retry_attempt == 1
        assert loaded.error_category == "context_overflow"
        assert loaded.workspace_num == 7
        assert loaded.cl_name == "branch-x"

    def test_read_returns_none_for_missing_file(self, tmp_path: Path) -> None:
        assert RetryHandoff.read_from_path(str(tmp_path / "nope.json")) is None


# ---------------------------------------------------------------------------
# build_handoff seeds chain root and increments retry_attempt
# ---------------------------------------------------------------------------


class TestBuildHandoff:
    def test_first_retry_uses_parent_as_chain_root(self, tmp_path: Path) -> None:
        ctx = _make_ctx(tmp_path)
        state = _make_state("Implement X.")
        tracker = _make_tracker()

        handoff = _build_handoff(
            ctx=ctx,
            state=state,
            tracker=tracker,
            error_snippet="Prompt is too long",
            continuation_prompt="Resume work.",
        )
        assert handoff.parent_timestamp == ctx.artifacts_timestamp
        assert handoff.chain_root_timestamp == ctx.artifacts_timestamp
        assert handoff.retry_attempt == 1
        assert handoff.error_category == "context_overflow"
        assert handoff.cl_name == ctx.cl_name
        assert handoff.workspace_num == ctx.workspace_num

    def test_subsequent_retry_walks_back_to_chain_root(self, tmp_path: Path) -> None:
        # Pre-seed a handoff in the parent's artifacts dir (as if this parent
        # itself was already a retry).
        ctx = _make_ctx(tmp_path)
        state = _make_state("Implement X.")
        tracker = _make_tracker()

        existing = {
            "parent_timestamp": ctx.artifacts_timestamp,
            "retry_attempt": 1,
            "chain_root_timestamp": "20260424100000",  # earlier root
            "error_snippet": "x",
            "error_category": "other",
            "continuation_prompt": None,
            "original_prompt": "x",
            "chat_path": None,
            "plan_path": None,
            "role_suffix": None,
            "workspace_num": 7,
            "workspace_dir": str(tmp_path),
            "vcs_ref": None,
            "cl_name": ctx.cl_name,
            "project_file": ctx.project_file,
            "project_name": ctx.project_name,
            "update_target": ctx.update_target,
            "is_home_mode": False,
            "agent_name": "parent_agent",
            "agent_model": None,
            "agent_llm_provider": "claude",
            "agent_vcs_provider": None,
            "fallback_model": None,
            "use_fallback": False,
            "qa_sections": [],
            "feedback_bullets": [],
        }
        (Path(ctx.artifacts_dir) / RETRY_HANDOFF_FILENAME).write_text(
            json.dumps(existing)
        )

        handoff = _build_handoff(
            ctx=ctx,
            state=state,
            tracker=tracker,
            error_snippet="429 rate limit",
            continuation_prompt=None,
        )
        # Chain root short-circuits to the earlier root
        assert handoff.chain_root_timestamp == "20260424100000"
        assert handoff.retry_attempt == 2
        assert handoff.error_category == "rate_limit"


# ---------------------------------------------------------------------------
# mark_parent_retried updates agent_meta.json
# ---------------------------------------------------------------------------


class TestMarkParentRetried:
    def test_creates_or_updates_meta(self, tmp_path: Path) -> None:
        meta_path = tmp_path / "agent_meta.json"
        meta_path.write_text(json.dumps({"name": "parent"}))

        mark_parent_retried(
            artifacts_dir=str(tmp_path),
            child_artifacts_timestamp="20260424130000",
            chain_root_timestamp="20260424120000",
            handoff_path=str(tmp_path / "retry_handoff.json"),
            error_category="context_overflow",
        )
        data = json.loads(meta_path.read_text())
        assert data["retried_as_timestamp"] == "20260424130000"
        assert data["retry_chain_root_timestamp"] == "20260424120000"
        assert data["retry_terminal"] is True
        assert data["retry_error_category"] == "context_overflow"
        # Pre-existing fields preserved
        assert data["name"] == "parent"

    def test_creates_meta_when_missing(self, tmp_path: Path) -> None:
        # No agent_meta.json — function should create one.
        mark_parent_retried(
            artifacts_dir=str(tmp_path),
            child_artifacts_timestamp="20260424130000",
            chain_root_timestamp="20260424120000",
            handoff_path="/tmp/x.json",
            error_category="other",
        )
        meta_path = tmp_path / "agent_meta.json"
        assert meta_path.exists()
        data = json.loads(meta_path.read_text())
        assert data["retried_as_timestamp"] == "20260424130000"


# ---------------------------------------------------------------------------
# handle_workflow_error: spawn-mode invokes spawn_retry_agent
# ---------------------------------------------------------------------------


class TestHandleWorkflowErrorSpawnMode:
    def test_spawn_success_marks_parent_and_breaks(self, tmp_path: Path) -> None:
        ctx = _make_ctx(tmp_path)
        state = _make_state("Implement X.")
        tracker = _make_tracker(spawn=True)

        fake_spawn = MagicMock(
            return_value={
                "pid": 99999,
                "child_timestamp": "260424_140000",
                "child_artifacts_timestamp": "20260424140000",
                "retry_attempt": 1,
                "chain_root_timestamp": ctx.artifacts_timestamp,
                "handoff_path": str(Path(ctx.artifacts_dir) / RETRY_HANDOFF_FILENAME),
                "error_category": "context_overflow",
            }
        )
        with patch("sase.axe.run_agent_retry_spawn.spawn_retry_agent", fake_spawn):
            action = handle_workflow_error(
                Exception("Prompt is too long"),
                tracker,
                ctx,
                state,
            )
        assert action == "break"
        assert state.loop_outcome == "failed_retried"
        assert fake_spawn.called

        # mark_parent_retried wrote the forward pointer into agent_meta.json
        meta = json.loads((Path(ctx.artifacts_dir) / "agent_meta.json").read_text())
        assert meta["retried_as_timestamp"] == "20260424140000"
        assert meta["retry_terminal"] is True

    def test_spawn_failure_falls_back_to_in_process(self, tmp_path: Path) -> None:
        ctx = _make_ctx(tmp_path)
        state = _make_state("Implement X.")
        tracker = _make_tracker(spawn=True)

        # Spawn returns None → fall back to legacy in-process retry path.
        with (
            patch(
                "sase.axe.run_agent_retry_spawn.spawn_retry_agent",
                MagicMock(return_value=None),
            ),
            patch("sase.axe.run_agent_exec_retry.prepare_workspace") as prep,
            patch("sase.axe.run_agent_exec_retry.os.chdir"),
        ):
            action = handle_workflow_error(
                Exception("Prompt is too long"),
                tracker,
                ctx,
                state,
            )
        # Falls through to in-process: returns "continue" (or "break" if
        # killed).  A successful in-process retry returns "continue".
        assert action == "continue"
        # prepare_workspace gets called for in-process retry path
        prep.assert_called()

    def test_spawn_disabled_uses_in_process(self, tmp_path: Path) -> None:
        ctx = _make_ctx(tmp_path)
        state = _make_state("Implement X.")
        tracker = _make_tracker(spawn=False)

        with (
            patch("sase.axe.run_agent_retry_spawn.spawn_retry_agent") as fake_spawn,
            patch("sase.axe.run_agent_exec_retry.prepare_workspace"),
            patch("sase.axe.run_agent_exec_retry.os.chdir"),
        ):
            action = handle_workflow_error(
                Exception("Prompt is too long"),
                tracker,
                ctx,
                state,
            )
        # spawn_retry_agent never called when flag is False
        assert not fake_spawn.called
        assert action == "continue"


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

        project_file = str(tmp_path / "project.gp")
        Path(project_file).write_text("")

        assert claim_workspace(
            project_file,
            workspace_num=42,
            workflow="ace(run)-260424_120000",
            pid=11111,
            cl_name="branch-x",
            artifacts_timestamp="20260424120000",
        )

        ok = transfer_workspace_claim(
            project_file,
            workspace_num=42,
            from_pid=11111,
            to_pid=22222,
            new_workflow="ace(run)-260424_130000",
            new_artifacts_timestamp="20260424130000",
            cl_name="branch-x",
        )
        assert ok is True

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

        project_file = str(tmp_path / "project.gp")
        Path(project_file).write_text("")
        assert claim_workspace(
            project_file,
            workspace_num=42,
            workflow="ace(run)-x",
            pid=11111,
            cl_name="branch-x",
            artifacts_timestamp="20260424120000",
        )
        # Wrong from_pid → returns False, no change
        ok = transfer_workspace_claim(
            project_file,
            workspace_num=42,
            from_pid=99999,
            to_pid=22222,
            new_workflow="ace(run)-y",
            new_artifacts_timestamp="20260424130000",
            cl_name="branch-x",
        )
        assert ok is False


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
            project_file="/tmp/p.gp",
            status="FAILED (RETRIED)",
            start_time=None,
            raw_suffix="20260424120000",
            retried_as_timestamp="20260424130000",
        )
        child1 = Agent(
            agent_type=AgentType.RUNNING,
            cl_name="branch-x",
            project_file="/tmp/p.gp",
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
            project_file="/tmp/p.gp",
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
            project_file="/p.gp",
            status="RUNNING",
            start_time=None,
            retry_attempt=2,
        )
        assert a.is_retry_attempt is True
        assert a.is_retried_parent is False

        b = Agent(
            agent_type=AgentType.RUNNING,
            cl_name="x",
            project_file="/p.gp",
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
        from sase.ace.tui.models._loaders._artifact_loaders import (
            _load_done_agent_for_dir,
        )

        # Build a done.json artifact dir
        artifact_dir = tmp_path / "20260424120000"
        artifact_dir.mkdir()
        done = {
            "cl_name": "branch-x",
            "project_file": str(tmp_path / "project.gp"),
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
        from sase.ace.tui.models._loaders._artifact_loaders import (
            _load_done_agent_for_dir,
        )

        artifact_dir = tmp_path / "20260424120000"
        artifact_dir.mkdir()
        done = {
            "cl_name": "branch-x",
            "project_file": str(tmp_path / "project.gp"),
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


# ---------------------------------------------------------------------------
# ProviderRetryConfig spawn_new_agent merge precedence
# ---------------------------------------------------------------------------


class TestSpawnNewAgentMerge:
    def test_user_dict_override_takes_precedence(self) -> None:
        from sase.llm_provider.retry_config import (
            ProviderRetryConfig,
            _config_from_user_dict,
            _merge_with_built_in,
        )

        built_in = ProviderRetryConfig(
            max_retries=2,
            error_patterns=["foo"],
            spawn_new_agent=False,
        )
        user_dict = {"spawn_new_agent": True}
        merged = _merge_with_built_in(user_dict, built_in)
        assert merged.spawn_new_agent is True

        user_only = _config_from_user_dict({"spawn_new_agent": True})
        assert user_only.spawn_new_agent is True

        merged_default = _merge_with_built_in({}, built_in)
        assert merged_default.spawn_new_agent is False

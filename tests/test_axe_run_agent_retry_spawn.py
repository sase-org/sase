"""Tests for the spawn-on-retry machinery (run_agent_retry_spawn)."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from sase.agent.launch_types import AgentLaunchResult
from sase.axe.run_agent_exec import AgentExecContext, LoopState
from sase.axe.run_agent_exec_retry import RetryTracker, handle_workflow_error
from sase.axe.run_agent_retry_spawn import (
    ENV_RETRY_OF_TIMESTAMP,
    RETRY_HANDOFF_FILENAME,
    RetryHandoff,
    _classify_error,
    _build_handoff,
    mark_parent_retried,
    spawn_retry_agent,
)
from sase.llm_provider.retry_config import ProviderRetryConfig


def _make_ctx(tmp_path: Path) -> AgentExecContext:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    return AgentExecContext(
        cl_name="branch-x",
        project_file=str(tmp_path / "project.sase"),
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
            project_file=str(tmp_path / "project.sase"),
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

    def test_qa_rounds_round_trips_through_json(self, tmp_path: Path) -> None:
        """Non-empty qa_rounds survives asdict → json → fromdict."""
        qa_rounds = [
            {
                "questions": [
                    {"question": "First?", "options": [], "header": "Repro"},
                ],
                "answers": [{"selected": ["A"], "custom_feedback": None}],
                "global_note": "note",
            },
            {
                "questions": [
                    {"question": "Second?", "options": [], "header": "Symptom"},
                ],
                "answers": [{"selected": ["B"], "custom_feedback": None}],
                "global_note": None,
            },
        ]
        h = RetryHandoff(
            parent_timestamp="20260424120000",
            retry_attempt=1,
            chain_root_timestamp="20260424120000",
            error_snippet="x",
            error_category="other",
            continuation_prompt=None,
            original_prompt="prompt",
            chat_path=None,
            plan_path=None,
            role_suffix=None,
            workspace_num=1,
            workspace_dir=str(tmp_path),
            vcs_ref=None,
            cl_name="x",
            project_file=str(tmp_path / "p.sase"),
            project_name="sase",
            update_target="trunk",
            is_home_mode=False,
            agent_name="a",
            agent_model=None,
            agent_llm_provider=None,
            agent_vcs_provider=None,
            fallback_model=None,
            use_fallback=False,
            qa_rounds=qa_rounds,
        )
        path = h.write_to(str(tmp_path))
        loaded = RetryHandoff.read_from_path(path)
        assert loaded is not None
        assert loaded.qa_rounds == qa_rounds

    def test_legacy_qa_sections_field_is_dropped_gracefully(
        self, tmp_path: Path
    ) -> None:
        """A handoff file written by an older version (with qa_sections)
        deserializes to an empty qa_rounds rather than crashing."""
        legacy = {
            "parent_timestamp": "20260424120000",
            "retry_attempt": 1,
            "chain_root_timestamp": "20260424120000",
            "error_snippet": "x",
            "error_category": "other",
            "continuation_prompt": None,
            "original_prompt": "prompt",
            "chat_path": None,
            "plan_path": None,
            "role_suffix": None,
            "workspace_num": 1,
            "workspace_dir": str(tmp_path),
            "vcs_ref": None,
            "cl_name": "x",
            "project_file": str(tmp_path / "p.sase"),
            "project_name": "sase",
            "update_target": "trunk",
            "is_home_mode": False,
            "agent_name": "a",
            "agent_model": None,
            "agent_llm_provider": None,
            "agent_vcs_provider": None,
            "fallback_model": None,
            "use_fallback": False,
            "qa_sections": ["legacy-text"],
            "feedback_bullets": [],
        }
        path = tmp_path / RETRY_HANDOFF_FILENAME
        path.write_text(json.dumps(legacy))

        loaded = RetryHandoff.read_from_path(str(path))
        assert loaded is not None
        assert loaded.qa_rounds == []


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
            "qa_rounds": [],
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
        calls: list[str] = []

        with patch(
            "sase.axe.run_agent_retry_spawn."
            "update_agent_artifact_index_for_marker_mutation",
            side_effect=lambda path: calls.append(path),
        ):
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
        assert calls == [str(tmp_path)]

    def test_creates_meta_when_missing(self, tmp_path: Path) -> None:
        # No agent_meta.json — function should create one.
        calls: list[str] = []

        with patch(
            "sase.axe.run_agent_retry_spawn."
            "update_agent_artifact_index_for_marker_mutation",
            side_effect=lambda path: calls.append(path),
        ):
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
        assert calls == [str(tmp_path)]


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
        index_update = MagicMock()
        with (
            patch("sase.axe.run_agent_retry_spawn.spawn_retry_agent", fake_spawn),
            patch(
                "sase.axe.run_agent_retry_spawn."
                "update_agent_artifact_index_for_marker_mutation",
                index_update,
            ),
        ):
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
        index_update.assert_called_once_with(ctx.artifacts_dir)

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
# spawn_retry_agent delegates the actual spawn to the shared detached_child
# primitive (sase.agent.detached_child.spawn_detached_child).
# ---------------------------------------------------------------------------


class TestSpawnRetryAgentUsesSharedPrimitive:
    def test_calls_spawn_agent_subprocess_via_spawn_detached_child(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ctx = _make_ctx(tmp_path)
        state = _make_state("Implement X.")
        tracker = _make_tracker(spawn=True)

        captured: dict[str, Any] = {}

        def fake_spawn(**kwargs: Any) -> AgentLaunchResult:
            captured.update(kwargs)
            return AgentLaunchResult(
                pid=555,
                workspace_num=kwargs["workspace_num"],
                workspace_dir=kwargs["workspace_dir"],
                output_path="/tmp/out.txt",
                timestamp=kwargs["timestamp"],
            )

        monkeypatch.setattr("sase.agent.launcher.spawn_agent_subprocess", fake_spawn)

        result = spawn_retry_agent(
            ctx=ctx,
            state=state,
            tracker=tracker,
            error_snippet="Prompt is too long",
            continuation_prompt="Resume work.",
        )

        assert result is not None
        assert result["pid"] == 555
        assert captured["cl_name"] == ctx.cl_name
        assert captured["project_file"] == ctx.project_file
        assert captured["workspace_dir"] == ctx.workspace_dir
        assert captured["workspace_num"] == ctx.workspace_num
        assert captured["update_target"] == ctx.update_target
        assert captured["is_home_mode"] == ctx.is_home_mode
        assert captured["workflow_name"] == f"ace(run)-{captured['timestamp']}"
        assert captured["retry_transfer_from_pid"] == os.getpid()
        assert captured["extra_env"][ENV_RETRY_OF_TIMESTAMP] == ctx.artifacts_timestamp
        assert result["child_timestamp"] == captured["timestamp"]

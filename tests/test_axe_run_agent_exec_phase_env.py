"""Tests for run_agent_exec phase environment handling."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from sase.axe.run_agent_exec import (
    AgentExecContext,
    LoopState,
    _AgentExecResult,
    _finalize_loop,
    _publish_phase_env,
    run_execution_loop,
)
from sase.axe.run_agent_exec_retry import RetryTracker

from tests._axe_run_agent_exec_helpers import make_exec_ctx


@pytest.mark.parametrize("outcome", ["completed", "epic_approved"])
def test_finalize_loop_handles_killed_iteration_without_result(
    tmp_path: Path,
    outcome: str,
) -> None:
    """A killed plan iteration never crashes finalization when result is None."""
    ctx = make_exec_ctx(tmp_path, is_home_mode=True, project_name="home")
    state = LoopState(
        current_prompt="prompt",
        current_role_suffix="--plan",
        current_artifacts_dir=ctx.artifacts_dir,
        loop_outcome=outcome,
        sdd_spec_path=None,
        original_prompt="prompt",
    )

    with (
        patch(
            "sase.axe.run_agent_exec_finalize.save_chat_history",
            return_value=str(tmp_path / "chat.md"),
        ),
        patch(
            "sase.axe.image_attachments.collect_agent_markdown_paths",
            return_value=[],
        ),
        patch("sase.axe.image_attachments.collect_agent_image_paths", return_value=[]),
    ):
        result = _finalize_loop(ctx, state, RetryTracker(retry_cfg=None), None)

    assert result.success is True
    assert result.outcome == outcome


def test_publish_phase_env_sets_both_vars_to_phase(tmp_path: Path, monkeypatch) -> None:
    """The helper publishes the current phase's artifacts dir + 14-digit timestamp."""
    monkeypatch.delenv("SASE_AGENT_TIMESTAMP", raising=False)
    monkeypatch.delenv("SASE_ARTIFACTS_DIR", raising=False)
    monkeypatch.setenv("SASE_AGENT_ROOT_TIMESTAMP", "20260501090000")

    phase_dir = tmp_path / "20260501123045"
    phase_dir.mkdir()
    _publish_phase_env(str(phase_dir))

    import os as _os

    assert _os.environ["SASE_ARTIFACTS_DIR"] == str(phase_dir)
    assert _os.environ["SASE_AGENT_TIMESTAMP"] == "20260501123045"
    assert _os.environ["SASE_AGENT_ROOT_TIMESTAMP"] == "20260501090000"


def test_run_execution_loop_publishes_phase_timestamp(
    tmp_path: Path, monkeypatch
) -> None:
    """The loop sets SASE_AGENT_TIMESTAMP to the current 14-digit phase timestamp."""
    monkeypatch.setenv("SASE_AGENT_TIMESTAMP", "260408_120000")
    monkeypatch.delenv("SASE_AGENT_ROOT_TIMESTAMP", raising=False)

    artifacts = tmp_path / "20260408120000"
    artifacts.mkdir()
    ctx = AgentExecContext(
        cl_name="test-cl",
        project_file=str(tmp_path / "project.sase"),
        workspace_dir=str(tmp_path),
        output_path=str(tmp_path / "output.log"),
        workspace_num=1,
        timestamp="20260408_120000",
        update_target="",
        project_name="sase",
        is_home_mode=False,
        artifacts_dir=str(artifacts),
        artifacts_timestamp="20260408_120000",
        vcs_tag=None,
        agent_name="agent",
        agent_model=None,
        agent_llm_provider=None,
        agent_vcs_provider=None,
        agent_hidden=False,
        agent_meta={},
        local_xprompts={},
    )
    anon_workflow = SimpleNamespace(name="anon", xprompts={})
    final_result = _AgentExecResult(success=True, current_artifacts_dir=str(artifacts))
    observed_timestamp: dict[str, str] = {}
    observed_root_timestamp: dict[str, str] = {}

    def _capture_env(*_args, **_kwargs):
        import os as _os

        observed_timestamp["value"] = _os.environ.get("SASE_AGENT_TIMESTAMP", "")
        observed_root_timestamp["value"] = _os.environ.get(
            "SASE_AGENT_ROOT_TIMESTAMP", ""
        )
        return SimpleNamespace(response_text="")

    with (
        patch("sase.history.chat.generate_chat_filename", return_value="test_chat"),
        patch(
            "sase.history.chat.get_chat_file_path",
            return_value="/tmp/test_chat.md",
        ),
        patch(
            "sase.xprompt.models.create_anonymous_workflow",
            return_value=anon_workflow,
        ),
        patch(
            "sase.xprompt.workflow_runner.execute_workflow",
            side_effect=_capture_env,
        ),
        patch("sase.axe.run_agent_exec.was_killed", return_value=False),
        patch("sase.axe.run_agent_exec.reset_killed"),
        patch("sase.axe.run_agent_exec._finalize_loop", return_value=final_result),
    ):
        run_execution_loop(ctx, "prompt")

    assert observed_timestamp["value"] == "20260408120000"
    assert observed_root_timestamp["value"] == "20260408120000"


def test_finalize_loop_restores_original_agent_timestamp(
    tmp_path: Path, monkeypatch
) -> None:
    """_finalize_loop restores SASE_AGENT_TIMESTAMP to its pre-loop value."""
    monkeypatch.setenv("SASE_AGENT_TIMESTAMP", "260408_120000")
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", "/should/be/cleared")
    monkeypatch.setenv("SASE_AGENT_ROOT_TIMESTAMP", "20260408120000")

    ctx = make_exec_ctx(tmp_path, is_home_mode=True, project_name="home")
    state = LoopState(
        current_prompt="prompt",
        current_role_suffix="",
        current_artifacts_dir=ctx.artifacts_dir,
        loop_outcome="completed",
        sdd_spec_path=None,
        original_prompt="prompt",
        original_agent_timestamp="260408_120000",
    )
    chat = tmp_path / "chat.md"

    import os as _os

    _os.environ["SASE_AGENT_TIMESTAMP"] = "20260408120000"
    _os.environ["SASE_AGENT_ROOT_TIMESTAMP"] = "20260408120000"

    with (
        patch(
            "sase.axe.run_agent_exec_finalize.save_chat_history",
            return_value=str(chat),
        ),
        patch(
            "sase.axe.image_attachments.collect_agent_markdown_paths",
            return_value=[],
        ),
        patch("sase.axe.image_attachments.collect_agent_image_paths", return_value=[]),
    ):
        _finalize_loop(
            ctx,
            state,
            RetryTracker(retry_cfg=None),
            SimpleNamespace(response_text="done"),
        )

    assert _os.environ.get("SASE_AGENT_TIMESTAMP") == "260408_120000"
    assert "SASE_ARTIFACTS_DIR" not in _os.environ
    assert "SASE_AGENT_ROOT_TIMESTAMP" not in _os.environ


def test_finalize_loop_clears_agent_timestamp_when_unset_at_entry(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Finalize clears the per-phase value when no timestamp existed at loop entry."""
    monkeypatch.delenv("SASE_AGENT_TIMESTAMP", raising=False)

    ctx = make_exec_ctx(tmp_path, is_home_mode=True, project_name="home")
    state = LoopState(
        current_prompt="prompt",
        current_role_suffix="",
        current_artifacts_dir=ctx.artifacts_dir,
        loop_outcome="completed",
        sdd_spec_path=None,
        original_prompt="prompt",
        original_agent_timestamp=None,
    )
    chat = tmp_path / "chat.md"

    import os as _os

    _os.environ["SASE_AGENT_TIMESTAMP"] = "20260408120000"
    _os.environ["SASE_AGENT_ROOT_TIMESTAMP"] = "20260408120000"

    with (
        patch(
            "sase.axe.run_agent_exec_finalize.save_chat_history",
            return_value=str(chat),
        ),
        patch(
            "sase.axe.image_attachments.collect_agent_markdown_paths",
            return_value=[],
        ),
        patch("sase.axe.image_attachments.collect_agent_image_paths", return_value=[]),
    ):
        _finalize_loop(
            ctx,
            state,
            RetryTracker(retry_cfg=None),
            SimpleNamespace(response_text="done"),
        )

    assert "SASE_AGENT_TIMESTAMP" not in _os.environ
    assert "SASE_AGENT_ROOT_TIMESTAMP" not in _os.environ

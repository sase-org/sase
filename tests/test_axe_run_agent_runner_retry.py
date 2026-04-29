"""Tests for retry logic in the agent runner."""

import json
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from sase.axe.run_agent_phases import _AgentInfo
from sase.llm_provider.retry_config import (
    RETRY_STATE_FILENAME,
    ProviderRetryConfig,
    truncate_error_snippet,
)

# --- truncate_error_snippet tests ---


class TestTruncateErrorSnippet:
    def test_short_string_unchanged(self) -> None:
        assert truncate_error_snippet("short error") == "short error"

    def test_exact_max_len_unchanged(self) -> None:
        s = "a" * 100
        assert truncate_error_snippet(s) == s

    def test_long_string_truncated(self) -> None:
        s = "a" * 150
        result = truncate_error_snippet(s)
        assert result == "a" * 100 + "..."
        assert len(result) == 103

    def test_custom_max_len(self) -> None:
        result = truncate_error_snippet("hello world", max_len=5)
        assert result == "hello..."

    def test_strips_whitespace(self) -> None:
        assert truncate_error_snippet("  error  ") == "error"

    def test_empty_string(self) -> None:
        assert truncate_error_snippet("") == ""

    def test_whitespace_only(self) -> None:
        assert truncate_error_snippet("   ") == ""


# --- Retry loop integration tests ---


def _make_retry_config(
    max_retries: int = 2,
    error_patterns: list[str] | None = None,
    wait_times: list[int] | None = None,
    fallback_model: str | None = None,
) -> ProviderRetryConfig:
    return ProviderRetryConfig(
        max_retries=max_retries,
        error_patterns=error_patterns or ["rate limit"],
        wait_times=wait_times or [1],
        fallback_model=fallback_model,
    )


_AGENT_INFO = _AgentInfo(
    name="test-agent",
    wait_names=[],
    wait_duration=None,
    wait_until=None,
    model="test-model",
    llm_provider="test-provider",
    vcs_provider=None,
    hidden=False,
    approve=False,
    plan=False,
    tag=None,
    meta={"pid": 1},
    local_xprompts={},
)


class _WorkflowResult:
    """Minimal stand-in for a workflow result object."""

    def __init__(self, response_text: str = "done") -> None:
        self.response_text = response_text


_RUNNER = "sase.axe.run_agent_runner"
_SETUP = "sase.axe.run_agent_runner_setup"
_FINALIZE = "sase.axe.run_agent_runner_finalize"
_EXEC = "sase.axe.run_agent_exec"
_RETRY = "sase.axe.run_agent_exec_retry"


def _base_patches(artifacts_dir: str) -> dict[str, Any]:
    """Return a dict of common mock targets and their return values."""
    # Shared mocks for names imported into both runner and exec modules
    was_killed_mock = MagicMock(return_value=False)
    prepare_ws_mock = MagicMock(return_value=True)
    return {
        # --- runner module ---
        f"{_SETUP}.prepare_workspace": prepare_ws_mock,
        f"{_RUNNER}.extract_directives_and_write_meta": MagicMock(
            return_value=_AGENT_INFO
        ),
        f"{_SETUP}.convert_timestamp_to_artifacts_format": MagicMock(
            return_value="20260316_120000"
        ),
        f"{_SETUP}.create_artifacts_directory": MagicMock(return_value=artifacts_dir),
        # Prevent tests from writing real notifications to the store
        "sase.notifications.senders.append_notification": MagicMock(),
        f"{_RUNNER}.format_duration": MagicMock(return_value="1s"),
        f"{_FINALIZE}.record_stop_time": MagicMock(),
        f"{_RUNNER}.was_killed": was_killed_mock,
        f"{_RUNNER}.all_steps_hidden": MagicMock(return_value=True),
        # --- exec module (execution loop) ---
        f"{_EXEC}.was_killed": was_killed_mock,
        f"{_EXEC}.reset_killed": MagicMock(),
        # --- retry module (error/retry handler) ---
        f"{_RETRY}.prepare_workspace": prepare_ws_mock,
        f"{_RETRY}.was_killed": was_killed_mock,
        f"{_EXEC}.save_chat_history": MagicMock(return_value="/tmp/history.md"),
        f"{_EXEC}.format_extra_sections": MagicMock(return_value=""),
        f"{_EXEC}.extract_step_output_and_diff_path": MagicMock(
            return_value=(None, None)
        ),
        # --- chat history (patched at source so shell commands are skipped) ---
        "sase.history.chat.generate_chat_filename": MagicMock(return_value="test_chat"),
        "sase.history.chat.get_chat_file_path": MagicMock(
            return_value="/tmp/test_chat.md"
        ),
        # --- xprompt (patched at source) ---
        "sase.xprompt.resolve_xprompt_aliases": MagicMock(side_effect=lambda x: x),
        "sase.xprompt._parsing.extract_vcs_workflow_tag": MagicMock(return_value=None),
        "sase.xprompt.processor.process_xprompt_references": MagicMock(
            side_effect=lambda x: x
        ),
        "sase.xprompt.models.create_anonymous_workflow": MagicMock(),
    }


def _run_main(
    patches: dict[str, Any],
    tmp_path: Path,
    *,
    update_target: str = "",
    workspace_dir: Path | None = None,
    workspace_num: str = "1",
    env: dict[str, str] | None = None,
) -> Path:
    """Run main() with the given patches dict. Returns the artifacts dir."""
    prompt_file = tmp_path / "prompt.txt"
    prompt_file.write_text("test prompt")
    output_file = tmp_path / "output.txt"
    output_file.write_text("")

    # Ensure the artifacts directory exists (read from mock)
    artifacts_dir_mock = patches.get(f"{_SETUP}.create_artifacts_directory")
    if artifacts_dir_mock:
        adir = Path(artifacts_dir_mock.return_value)
        adir.mkdir(parents=True, exist_ok=True)

    import sys

    argv = [
        "runner",
        "test-cl",
        str(tmp_path / "project.gp"),
        str(workspace_dir or tmp_path),
        str(output_file),
        workspace_num,
        "test-workflow",
        str(prompt_file),
        "20260316_120000",
        update_target,
        "test-project",
        "test-cl",
        "",  # is_home_mode
    ]

    stack: list[Any] = []
    saved_env = os.environ.copy()
    if env:
        os.environ.update(env)
    with patch.object(sys, "argv", argv):
        for target, value in patches.items():
            p = patch(target, value)
            p.start()
            stack.append(p)
        try:
            from sase.axe.run_agent_runner import main

            with pytest.raises(SystemExit):
                main()
        finally:
            for p in stack:
                p.stop()
            os.environ.clear()
            os.environ.update(saved_env)
    return adir  # type: ignore[possibly-undefined]


def _exec_result(artifacts_dir: str) -> SimpleNamespace:
    return SimpleNamespace(
        success=True,
        outcome="completed",
        saved_path=None,
        diff_path=None,
        current_artifacts_dir=artifacts_dir,
        step_output=None,
    )


class TestRetryLoop:
    def test_no_retry_when_config_is_none(self, tmp_path: Path) -> None:
        """When get_retry_config returns None, errors propagate normally."""
        patches = _base_patches(str(tmp_path / "artifacts"))
        execute_mock = MagicMock(side_effect=RuntimeError("rate limit exceeded"))
        patches[f"{_EXEC}.get_retry_config"] = MagicMock(return_value=None)
        patches["sase.xprompt.workflow_runner.execute_workflow"] = execute_mock

        _run_main(patches, tmp_path)

        assert execute_mock.call_count == 1

    def test_non_retryable_error_raises_immediately(self, tmp_path: Path) -> None:
        """Non-retryable errors skip retry and raise immediately."""
        patches = _base_patches(str(tmp_path / "artifacts"))
        config = _make_retry_config(error_patterns=["rate limit"])
        execute_mock = MagicMock(side_effect=RuntimeError("authentication failed"))
        patches[f"{_EXEC}.get_retry_config"] = MagicMock(return_value=config)
        patches["sase.xprompt.workflow_runner.execute_workflow"] = execute_mock

        _run_main(patches, tmp_path)

        assert execute_mock.call_count == 1

    def test_retry_on_retryable_error(self, tmp_path: Path) -> None:
        """Retryable errors trigger retry with correct number of attempts."""
        patches = _base_patches(str(tmp_path / "artifacts"))
        config = _make_retry_config(max_retries=2, wait_times=[0])
        execute_mock = MagicMock(
            side_effect=[
                RuntimeError("rate limit exceeded"),
                RuntimeError("rate limit exceeded"),
                _WorkflowResult("success"),
            ]
        )
        patches[f"{_EXEC}.get_retry_config"] = MagicMock(return_value=config)
        patches["sase.xprompt.workflow_runner.execute_workflow"] = execute_mock
        patches[f"{_RETRY}.time.sleep"] = MagicMock()

        _run_main(patches, tmp_path)

        assert execute_mock.call_count == 3  # 1 initial + 2 retries

    def test_retry_state_written_during_wait(self, tmp_path: Path) -> None:
        """retry_state.json is written with 'retrying' status during wait."""
        artifacts_dir = tmp_path / "artifacts"
        patches = _base_patches(str(artifacts_dir))
        config = _make_retry_config(max_retries=1, wait_times=[2])

        retry_states_seen: list[dict[str, Any]] = []

        def capture_sleep(_seconds: float) -> None:
            state_file = artifacts_dir / RETRY_STATE_FILENAME
            if state_file.exists():
                with open(state_file) as f:
                    retry_states_seen.append(json.load(f))

        execute_mock = MagicMock(
            side_effect=[
                RuntimeError("rate limit exceeded"),
                _WorkflowResult("success"),
            ]
        )
        patches[f"{_EXEC}.get_retry_config"] = MagicMock(return_value=config)
        patches["sase.xprompt.workflow_runner.execute_workflow"] = execute_mock
        patches[f"{_RETRY}.time.sleep"] = capture_sleep

        _run_main(patches, tmp_path)

        assert any(s.get("status") == "retrying" for s in retry_states_seen)

    def test_retry_state_deleted_on_completion(self, tmp_path: Path) -> None:
        """retry_state.json is cleaned up after successful completion."""
        artifacts_dir = tmp_path / "artifacts"
        patches = _base_patches(str(artifacts_dir))
        config = _make_retry_config(max_retries=1, wait_times=[0])
        execute_mock = MagicMock(
            side_effect=[
                RuntimeError("rate limit exceeded"),
                _WorkflowResult("success"),
            ]
        )
        patches[f"{_EXEC}.get_retry_config"] = MagicMock(return_value=config)
        patches["sase.xprompt.workflow_runner.execute_workflow"] = execute_mock
        patches[f"{_RETRY}.time.sleep"] = MagicMock()

        _run_main(patches, tmp_path)

        assert not (artifacts_dir / RETRY_STATE_FILENAME).exists()

    def test_fallback_model_tried_after_max_retries(self, tmp_path: Path) -> None:
        """Fallback model is used after all retries are exhausted."""
        patches = _base_patches(str(tmp_path / "artifacts"))
        config = _make_retry_config(
            max_retries=1,
            wait_times=[0],
            fallback_model="gemini-flash",
        )
        execute_mock = MagicMock(
            side_effect=[
                RuntimeError("rate limit exceeded"),
                RuntimeError("rate limit exceeded"),
                _WorkflowResult("success"),
            ]
        )
        patches[f"{_EXEC}.get_retry_config"] = MagicMock(return_value=config)
        patches["sase.xprompt.workflow_runner.execute_workflow"] = execute_mock
        patches[f"{_RETRY}.time.sleep"] = MagicMock()

        env_overrides: list[str] = []
        original_setitem = os.environ.__class__.__setitem__

        def track_env_set(self: Any, key: str, value: str) -> None:
            if key == "SASE_MODEL_OVERRIDE":
                env_overrides.append(value)
            original_setitem(self, key, value)

        with patch.object(os.environ.__class__, "__setitem__", track_env_set):
            _run_main(patches, tmp_path)

        assert execute_mock.call_count == 3  # initial + 1 retry + 1 fallback
        assert "gemini-flash" in env_overrides

        os.environ.pop("SASE_MODEL_OVERRIDE", None)

    def test_was_killed_during_wait_aborts_retry(self, tmp_path: Path) -> None:
        """was_killed() returning True during sleep aborts the retry loop."""
        patches = _base_patches(str(tmp_path / "artifacts"))
        config = _make_retry_config(max_retries=2, wait_times=[5])
        execute_mock = MagicMock(side_effect=RuntimeError("rate limit exceeded"))
        patches[f"{_EXEC}.get_retry_config"] = MagicMock(return_value=config)
        patches["sase.xprompt.workflow_runner.execute_workflow"] = execute_mock

        # was_killed returns False initially (for the re-raise check),
        # then True during the sleep loop
        kill_calls = 0

        def mock_was_killed() -> bool:
            nonlocal kill_calls
            kill_calls += 1
            return kill_calls >= 2

        # Override in all modules (runner finally block + exec loop + retry handler)
        patches[f"{_RUNNER}.was_killed"] = mock_was_killed
        patches[f"{_EXEC}.was_killed"] = mock_was_killed
        patches[f"{_RETRY}.was_killed"] = mock_was_killed
        patches[f"{_RETRY}.time.sleep"] = MagicMock()

        _run_main(patches, tmp_path)

        assert execute_mock.call_count == 1

    def test_done_json_includes_retry_metadata(self, tmp_path: Path) -> None:
        """done.json includes retry_metadata when retries occurred."""
        artifacts_dir = tmp_path / "artifacts"
        patches = _base_patches(str(artifacts_dir))
        config = _make_retry_config(max_retries=1, wait_times=[0])
        execute_mock = MagicMock(
            side_effect=[
                RuntimeError("rate limit exceeded"),
                _WorkflowResult("success"),
            ]
        )
        patches[f"{_EXEC}.get_retry_config"] = MagicMock(return_value=config)
        patches["sase.xprompt.workflow_runner.execute_workflow"] = execute_mock
        patches[f"{_RETRY}.time.sleep"] = MagicMock()

        _run_main(patches, tmp_path)

        done_path = artifacts_dir / "done.json"
        assert done_path.exists()
        done_data = json.loads(done_path.read_text())
        assert "retry_metadata" in done_data
        meta = done_data["retry_metadata"]
        assert meta["retry_count"] == 1
        assert len(meta["retry_errors"]) == 1
        assert "rate limit" in meta["retry_errors"][0]
        assert meta["used_fallback"] is False

    def test_no_retry_metadata_when_no_retries(self, tmp_path: Path) -> None:
        """done.json has no retry_metadata when workflow succeeds first try."""
        artifacts_dir = tmp_path / "artifacts"
        patches = _base_patches(str(artifacts_dir))
        patches[f"{_EXEC}.get_retry_config"] = MagicMock(return_value=None)
        patches["sase.xprompt.workflow_runner.execute_workflow"] = MagicMock(
            return_value=_WorkflowResult("success")
        )

        _run_main(patches, tmp_path)

        done_path = artifacts_dir / "done.json"
        assert done_path.exists()
        done_data = json.loads(done_path.read_text())
        assert "retry_metadata" not in done_data

    def test_cross_provider_retry_uses_fallback_config(self, tmp_path: Path) -> None:
        """When the agent's own provider has no retry config, retries still
        fire if another provider's error patterns match (e.g. outer workflow
        defaults to claude but inner step uses gemini)."""
        from sase.llm_provider.retry_config import ProviderRetryConfig

        patches = _base_patches(str(tmp_path / "artifacts"))
        # Agent's own provider (claude) has no retry config
        patches[f"{_EXEC}.get_retry_config"] = MagicMock(return_value=None)

        # But gemini's config matches the error
        gemini_cfg = ProviderRetryConfig(
            max_retries=1,
            error_patterns=["An unexpected critical error occurred:"],
            wait_times=[0],
        )
        patches[f"{_RETRY}.find_retry_config_for_error"] = MagicMock(
            return_value=gemini_cfg
        )

        execute_mock = MagicMock(
            side_effect=[
                RuntimeError(
                    "Step 'main' failed: An unexpected critical error occurred:[object Object]"
                ),
                _WorkflowResult("success"),
            ]
        )
        patches["sase.xprompt.workflow_runner.execute_workflow"] = execute_mock
        patches[f"{_RETRY}.time.sleep"] = MagicMock()

        _run_main(patches, tmp_path)

        assert execute_mock.call_count == 2  # 1 initial + 1 retry


class TestDeferredWorkspacePreparation:
    def test_claim_deferred_workspace_claims_and_returns_real_workspace(
        self, tmp_path: Path
    ) -> None:
        from sase.axe.run_agent_phases import claim_deferred_workspace

        workspace_dir = tmp_path / "ws7"
        release_mock = MagicMock()
        claim_mock = MagicMock(return_value=True)

        with (
            patch("sase.running_field.release_workspace", release_mock),
            patch("sase.running_field.get_first_available_axe_workspace") as first_ws,
            patch("sase.running_field.get_workspace_directory_for_num") as ws_dir,
            patch("sase.running_field.claim_workspace", claim_mock),
            patch("sase.axe.run_agent_phases.os.chdir") as chdir_mock,
        ):
            first_ws.return_value = 7
            ws_dir.return_value = (str(workspace_dir), None)

            workspace_num, actual_workspace_dir = claim_deferred_workspace(
                str(tmp_path / "project.gp"),
                "test-project",
                "test-workflow",
                "test-cl",
                "20260316_120000",
            )

        assert workspace_num == 7
        assert actual_workspace_dir == str(workspace_dir)
        release_mock.assert_called_once_with(
            str(tmp_path / "project.gp"), 0, "test-workflow", "test-cl"
        )
        claim_mock.assert_called_once()
        chdir_mock.assert_called_once_with(str(workspace_dir))

    def test_deferred_wait_prepares_claimed_workspace_after_wait(
        self, tmp_path: Path
    ) -> None:
        artifacts_dir = str(tmp_path / "artifacts")
        placeholder_ws = tmp_path / "placeholder"
        real_ws = tmp_path / "real-ws"
        placeholder_ws.mkdir()
        real_ws.mkdir()
        events: list[Any] = []

        wait_info = _AGENT_INFO._replace(wait_names=["dep"])
        patches = _base_patches(artifacts_dir)
        patches[f"{_RUNNER}.extract_directives_and_write_meta"] = MagicMock(
            return_value=wait_info
        )

        def wait_for_deps(*_args: Any, **_kwargs: Any) -> None:
            events.append("wait")

        def claim_deferred(*_args: Any, **_kwargs: Any) -> tuple[int, str]:
            events.append("claim")
            return 3, str(real_ws)

        def prepare_ws(workspace_dir: str, *_args: Any, **_kwargs: Any) -> bool:
            events.append(("prepare", workspace_dir))
            return True

        def run_loop(ctx: Any, _prompt: str) -> SimpleNamespace:
            events.append(("run", ctx.workspace_num, ctx.workspace_dir))
            return _exec_result(artifacts_dir)

        patches[f"{_RUNNER}.wait_for_dependencies"] = wait_for_deps
        patches[f"{_RUNNER}.resolve_wait_chat_paths"] = MagicMock(return_value=[])
        patches[f"{_RUNNER}.claim_deferred_workspace"] = claim_deferred
        patches[f"{_SETUP}.prepare_workspace"] = prepare_ws
        patches[f"{_RUNNER}.run_execution_loop"] = run_loop

        _run_main(
            patches,
            tmp_path,
            update_target="main",
            workspace_dir=placeholder_ws,
            workspace_num="0",
            env={"SASE_AGENT_DEFERRED_WORKSPACE": "1"},
        )

        assert events == [
            "wait",
            "claim",
            ("prepare", str(real_ws)),
            ("run", 3, str(real_ws)),
        ]

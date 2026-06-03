"""Tests for retry loop behavior in the agent runner."""

import json
import os
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

from sase.llm_provider.retry_config import RETRY_STATE_FILENAME, ProviderRetryConfig

from tests._axe_run_agent_runner_retry_helpers import (
    EXEC,
    RETRY,
    RUNNER,
    WorkflowResult,
    base_patches,
    make_retry_config,
    run_main,
)


class TestRetryLoop:
    def test_no_retry_when_config_is_none(self, tmp_path: Path) -> None:
        """When get_retry_config returns None, errors propagate normally.

        Uses an error string that matches no provider's built-in patterns so
        the ``find_retry_config_for_error`` fallback also returns None.
        """
        patches = base_patches(str(tmp_path / "artifacts"))
        execute_mock = MagicMock(side_effect=RuntimeError("authentication failed"))
        patches[f"{EXEC}.get_retry_config"] = MagicMock(return_value=None)
        patches["sase.xprompt.workflow_runner.execute_workflow"] = execute_mock

        run_main(patches, tmp_path)

        assert execute_mock.call_count == 1

    def test_non_retryable_error_raises_immediately(self, tmp_path: Path) -> None:
        """Non-retryable errors skip retry and raise immediately."""
        patches = base_patches(str(tmp_path / "artifacts"))
        config = make_retry_config(error_patterns=["rate limit"])
        execute_mock = MagicMock(side_effect=RuntimeError("authentication failed"))
        patches[f"{EXEC}.get_retry_config"] = MagicMock(return_value=config)
        patches["sase.xprompt.workflow_runner.execute_workflow"] = execute_mock

        run_main(patches, tmp_path)

        assert execute_mock.call_count == 1

    def test_retry_on_retryable_error(self, tmp_path: Path) -> None:
        """Retryable errors trigger retry with correct number of attempts."""
        patches = base_patches(str(tmp_path / "artifacts"))
        config = make_retry_config(max_retries=2, wait_times=[0])
        execute_mock = MagicMock(
            side_effect=[
                RuntimeError("rate limit exceeded"),
                RuntimeError("rate limit exceeded"),
                WorkflowResult("success"),
            ]
        )
        patches[f"{EXEC}.get_retry_config"] = MagicMock(return_value=config)
        patches["sase.xprompt.workflow_runner.execute_workflow"] = execute_mock
        patches[f"{RETRY}.time.sleep"] = MagicMock()

        run_main(patches, tmp_path)

        assert execute_mock.call_count == 3

    def test_retry_state_written_during_wait(self, tmp_path: Path) -> None:
        """retry_state.json is written with 'retrying' status during wait."""
        artifacts_dir = tmp_path / "artifacts"
        patches = base_patches(str(artifacts_dir))
        config = make_retry_config(max_retries=1, wait_times=[2])

        retry_states_seen: list[dict[str, Any]] = []

        def capture_sleep(_seconds: float) -> None:
            state_file = artifacts_dir / RETRY_STATE_FILENAME
            if state_file.exists():
                with open(state_file) as f:
                    retry_states_seen.append(json.load(f))

        execute_mock = MagicMock(
            side_effect=[
                RuntimeError("rate limit exceeded"),
                WorkflowResult("success"),
            ]
        )
        patches[f"{EXEC}.get_retry_config"] = MagicMock(return_value=config)
        patches["sase.xprompt.workflow_runner.execute_workflow"] = execute_mock
        patches[f"{RETRY}.time.sleep"] = capture_sleep

        run_main(patches, tmp_path)

        assert any(s.get("status") == "retrying" for s in retry_states_seen)

    def test_retry_state_deleted_on_completion(self, tmp_path: Path) -> None:
        """retry_state.json is cleaned up after successful completion."""
        artifacts_dir = tmp_path / "artifacts"
        patches = base_patches(str(artifacts_dir))
        config = make_retry_config(max_retries=1, wait_times=[0])
        execute_mock = MagicMock(
            side_effect=[
                RuntimeError("rate limit exceeded"),
                WorkflowResult("success"),
            ]
        )
        patches[f"{EXEC}.get_retry_config"] = MagicMock(return_value=config)
        patches["sase.xprompt.workflow_runner.execute_workflow"] = execute_mock
        patches[f"{RETRY}.time.sleep"] = MagicMock()

        run_main(patches, tmp_path)

        assert not (artifacts_dir / RETRY_STATE_FILENAME).exists()

    def test_fallback_model_tried_after_max_retries(self, tmp_path: Path) -> None:
        """Fallback model is used after all retries are exhausted."""
        patches = base_patches(str(tmp_path / "artifacts"))
        config = make_retry_config(
            max_retries=1,
            wait_times=[0],
            fallback_model="gemini-flash",
        )
        execute_mock = MagicMock(
            side_effect=[
                RuntimeError("rate limit exceeded"),
                RuntimeError("rate limit exceeded"),
                WorkflowResult("success"),
            ]
        )
        patches[f"{EXEC}.get_retry_config"] = MagicMock(return_value=config)
        patches["sase.xprompt.workflow_runner.execute_workflow"] = execute_mock
        patches[f"{RETRY}.time.sleep"] = MagicMock()

        env_overrides: list[str] = []
        original_setitem = os.environ.__class__.__setitem__

        def track_env_set(self: Any, key: str, value: str) -> None:
            if key == "SASE_MODEL_OVERRIDE":
                env_overrides.append(value)
            original_setitem(self, key, value)

        with patch.object(os.environ.__class__, "__setitem__", track_env_set):
            run_main(patches, tmp_path)

        assert execute_mock.call_count == 3
        assert "gemini-flash" in env_overrides

        os.environ.pop("SASE_MODEL_OVERRIDE", None)

    def test_was_killed_during_wait_aborts_retry(self, tmp_path: Path) -> None:
        """was_killed() returning True during sleep aborts the retry loop."""
        patches = base_patches(str(tmp_path / "artifacts"))
        config = make_retry_config(max_retries=2, wait_times=[5])
        execute_mock = MagicMock(side_effect=RuntimeError("rate limit exceeded"))
        patches[f"{EXEC}.get_retry_config"] = MagicMock(return_value=config)
        patches["sase.xprompt.workflow_runner.execute_workflow"] = execute_mock

        kill_calls = 0

        def mock_was_killed() -> bool:
            nonlocal kill_calls
            kill_calls += 1
            return kill_calls >= 2

        patches[f"{RUNNER}.was_killed"] = mock_was_killed
        patches[f"{EXEC}.was_killed"] = mock_was_killed
        patches[f"{RETRY}.was_killed"] = mock_was_killed
        patches[f"{RETRY}.time.sleep"] = MagicMock()

        run_main(patches, tmp_path)

        assert execute_mock.call_count == 1

    def test_done_json_includes_retry_metadata(self, tmp_path: Path) -> None:
        """done.json includes retry_metadata when retries occurred."""
        artifacts_dir = tmp_path / "artifacts"
        patches = base_patches(str(artifacts_dir))
        config = make_retry_config(max_retries=1, wait_times=[0])
        execute_mock = MagicMock(
            side_effect=[
                RuntimeError("rate limit exceeded"),
                WorkflowResult("success"),
            ]
        )
        patches[f"{EXEC}.get_retry_config"] = MagicMock(return_value=config)
        patches["sase.xprompt.workflow_runner.execute_workflow"] = execute_mock
        patches[f"{RETRY}.time.sleep"] = MagicMock()

        run_main(patches, tmp_path)

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
        patches = base_patches(str(artifacts_dir))
        patches[f"{EXEC}.get_retry_config"] = MagicMock(return_value=None)
        patches["sase.xprompt.workflow_runner.execute_workflow"] = MagicMock(
            return_value=WorkflowResult("success")
        )

        run_main(patches, tmp_path)

        done_path = artifacts_dir / "done.json"
        assert done_path.exists()
        done_data = json.loads(done_path.read_text())
        assert "retry_metadata" not in done_data

    def test_cross_provider_retry_uses_fallback_config(self, tmp_path: Path) -> None:
        """Retry can use a matching provider config beyond the agent provider."""
        patches = base_patches(str(tmp_path / "artifacts"))
        patches[f"{EXEC}.get_retry_config"] = MagicMock(return_value=None)

        gemini_cfg = ProviderRetryConfig(
            max_retries=1,
            error_patterns=["An unexpected critical error occurred:"],
            wait_times=[0],
        )
        patches[f"{RETRY}.find_retry_config_for_error"] = MagicMock(
            return_value=gemini_cfg
        )

        execute_mock = MagicMock(
            side_effect=[
                RuntimeError(
                    "Step 'main' failed: An unexpected critical error occurred:"
                    "[object Object]"
                ),
                WorkflowResult("success"),
            ]
        )
        patches["sase.xprompt.workflow_runner.execute_workflow"] = execute_mock
        patches[f"{RETRY}.time.sleep"] = MagicMock()

        run_main(patches, tmp_path)

        assert execute_mock.call_count == 2

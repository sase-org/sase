"""Tests for llm_provider postprocessing (logging and file saving)."""

import os
import tempfile
from typing import TYPE_CHECKING

from sase.llm_provider.postprocessing import (
    _save_to_chat_history,
    log_prompt_and_response,
    postprocess_error,
    save_prompt_to_file,
)
from sase.llm_provider.types import LoggingContext

if TYPE_CHECKING:
    from pytest import CaptureFixture


def test_log_prompt_and_response_with_iteration() -> None:
    """Test logging with iteration number."""
    with tempfile.TemporaryDirectory() as tmpdir:
        log_prompt_and_response(
            prompt="Test prompt",
            response="Test response",
            artifacts_dir=tmpdir,
            agent_type="editor",
            iteration=5,
        )

        log_file = os.path.join(tmpdir, "sase.md")
        with open(log_file) as f:
            content = f.read()
        assert "iteration 5" in content


def test_log_prompt_and_response_with_workflow_tag() -> None:
    """Test logging with workflow tag."""
    with tempfile.TemporaryDirectory() as tmpdir:
        log_prompt_and_response(
            prompt="Test prompt",
            response="Test response",
            artifacts_dir=tmpdir,
            agent_type="planner",
            workflow_tag="crs",
        )

        log_file = os.path.join(tmpdir, "sase.md")
        with open(log_file) as f:
            content = f.read()
        assert "tag crs" in content


def test_log_prompt_and_response_handles_error(
    capsys: "CaptureFixture[str]",
) -> None:
    """Test that logging errors are handled gracefully."""
    log_prompt_and_response(
        prompt="Test prompt",
        response="Test response",
        artifacts_dir="/nonexistent/path/that/cannot/exist",
    )

    captured = capsys.readouterr()
    assert "Warning" in captured.out


def test_save_prompt_to_file_basic() -> None:
    """Test saving a prompt to file."""
    with tempfile.TemporaryDirectory() as tmpdir:
        save_prompt_to_file(
            prompt="My test prompt",
            artifacts_dir=tmpdir,
            agent_type="test_agent",
        )

        prompt_file = os.path.join(tmpdir, "test_agent_prompt.md")
        assert os.path.exists(prompt_file)
        with open(prompt_file) as f:
            assert f.read() == "My test prompt"


def test_save_prompt_to_file_with_iteration() -> None:
    """Test saving a prompt with iteration number."""
    with tempfile.TemporaryDirectory() as tmpdir:
        save_prompt_to_file(
            prompt="Iteration prompt",
            artifacts_dir=tmpdir,
            agent_type="editor",
            iteration=3,
        )

        prompt_file = os.path.join(tmpdir, "editor_iter_3_prompt.md")
        assert os.path.exists(prompt_file)


def test_save_to_chat_history_passes_transcript_model_metadata() -> None:
    context = LoggingContext(
        agent_type="wf",
        workflow="wf",
        metadata_model="sonnet",
        metadata_llm_provider="claude",
    )

    from unittest.mock import patch

    with patch("sase.llm_provider.postprocessing.save_chat_history") as save_chat:
        _save_to_chat_history("prompt", "response", context, "260501_225009")

    assert save_chat.call_args.kwargs["metadata_model"] == "sonnet"
    assert save_chat.call_args.kwargs["metadata_llm_provider"] == "claude"
    assert save_chat.call_args.kwargs["metadata_agent"] is None


def test_postprocess_error_warns_when_chat_history_save_fails(
    capsys: "CaptureFixture[str]",
) -> None:
    """Chat persistence failures do not replace the primary provider error."""
    context = LoggingContext(workflow="wf", suppress_output=True)

    from unittest.mock import patch

    with patch(
        "sase.llm_provider.postprocessing._save_error_to_chat_history",
        side_effect=RuntimeError("history unavailable"),
    ):
        postprocess_error(
            prompt="prompt",
            error_content="provider failed",
            context=context,
            model_tier="large",
            start_timestamp="260501_225009",
        )

    captured = capsys.readouterr()
    assert "Warning: Failed to save chat history: history unavailable" in captured.out

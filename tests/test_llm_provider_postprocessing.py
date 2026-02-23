"""Tests for llm_provider postprocessing (logging and file saving)."""

import os
import tempfile
from typing import TYPE_CHECKING

from sase.llm_provider.postprocessing import (
    log_prompt_and_response,
    save_prompt_to_file,
)

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

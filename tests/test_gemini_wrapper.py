"""Tests for gemini_wrapper module."""

import os
import subprocess
import tempfile
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest
from sase.gemini_wrapper.file_references import process_file_references

if TYPE_CHECKING:
    from pytest import CaptureFixture


def testprocess_file_references_tilde_expansion() -> None:
    """Test that tilde paths are copied to .sase/ with home-relative structure."""
    # Create a temp file to reference
    with tempfile.NamedTemporaryFile(delete=False, suffix=".txt") as f:
        temp_path = f.name
        f.write(b"test content")

    try:
        # Create a tilde path by replacing the home directory with ~
        home_dir = os.path.expanduser("~")
        if temp_path.startswith(home_dir):
            tilde_path = "~" + temp_path[len(home_dir) :]
            rel_path = os.path.relpath(temp_path, home_dir)
        else:
            # Skip test if temp file is not under home directory
            return

        prompt = f"Check this file: @{tilde_path}"

        # Change to a temp directory to avoid issues with .sase/ in the actual dir
        original_cwd = os.getcwd()
        with tempfile.TemporaryDirectory() as tmpdir:
            os.chdir(tmpdir)
            try:
                with patch("sase.gemini_wrapper.file_references.print_status"):
                    with patch(
                        "sase.gemini_wrapper.file_references.print_file_operation"
                    ):
                        result = process_file_references(prompt)

                # The tilde path should be replaced with a relative path to .sase/
                assert f"@{tilde_path}" not in result
                assert f"@.sase/{rel_path}" in result

                # Check that the file was copied with home-relative structure
                copied_file = os.path.join(".sase", rel_path)
                assert os.path.exists(copied_file)

                # Verify content was copied correctly
                with open(copied_file) as f:
                    assert f.read() == "test content"
            finally:
                os.chdir(original_cwd)
    finally:
        os.unlink(temp_path)


def testprocess_file_references_tilde_missing_file() -> None:
    """Test that missing tilde paths are reported correctly."""
    prompt = "Check this file: @~/nonexistent/path/to/file.txt"

    with patch("sase.gemini_wrapper.file_references.print_status"):
        with patch("sase.gemini_wrapper.file_references.print_file_operation"):
            # Should exit with error for missing file
            with pytest.raises(SystemExit) as exc_info:
                process_file_references(prompt)
            assert exc_info.value.code == 1


def testprocess_file_references_at_not_in_middle_of_word() -> None:
    """Test that @ in the middle of a word is NOT treated as a file reference."""
    # These should NOT be treated as file references and should not cause errors
    # even if the "file" doesn't exist
    prompt_email = "Contact user@example.com for help"
    result = process_file_references(prompt_email)
    assert result == prompt_email  # Unchanged

    prompt_embedded = "The foo@bar value is important"
    result = process_file_references(prompt_embedded)
    assert result == prompt_embedded  # Unchanged

    prompt_no_space = "Check this:@something"
    result = process_file_references(prompt_no_space)
    assert result == prompt_no_space  # Unchanged (@ not after space)


def test_stream_process_output_basic() -> None:
    """Test basic streaming of process output."""
    from sase.gemini_wrapper.wrapper import _stream_process_output

    # Create a simple process that outputs to stdout
    process = subprocess.Popen(
        ["echo", "hello world"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    stdout, stderr, return_code = _stream_process_output(process, suppress_output=True)

    assert "hello world" in stdout
    assert stderr == ""
    assert return_code == 0


def test_gemini_command_wrapper_set_logging_context() -> None:
    """Test setting logging context on the wrapper."""
    from sase.gemini_wrapper import GeminiCommandWrapper

    wrapper = GeminiCommandWrapper()
    wrapper.set_logging_context(
        agent_type="test_agent",
        iteration=3,
        workflow_tag="test-workflow",
        artifacts_dir="/tmp/test",
        suppress_output=True,
        workflow="my-workflow",
    )

    assert wrapper.agent_type == "test_agent"
    assert wrapper.iteration == 3
    assert wrapper.workflow_tag == "test-workflow"
    assert wrapper.artifacts_dir == "/tmp/test"
    assert wrapper.suppress_output is True
    assert wrapper.workflow == "my-workflow"


def test_gemini_command_wrapper_invoke_no_query() -> None:
    """Test invoke returns error message when no HumanMessage found."""
    from sase.gemini_wrapper import GeminiCommandWrapper
    from langchain_core.messages import AIMessage

    wrapper = GeminiCommandWrapper()
    # Pass only AIMessage, no HumanMessage
    result = wrapper.invoke([AIMessage(content="Some AI response")])
    assert "No query found in messages" in result.content


def test_gemini_command_wrapper_display_decision_counts(
    capsys: "CaptureFixture[str]",
) -> None:
    """Test that decision counts are displayed when set."""
    from sase.gemini_wrapper import GeminiCommandWrapper

    wrapper = GeminiCommandWrapper()
    wrapper.suppress_output = False

    # With no counts set, should do nothing
    wrapper._display_decision_counts()
    capsys.readouterr()  # Clear any output
    # No output expected when counts is None

    # With counts set, should call print_decision_counts
    wrapper.set_decision_counts({"yes": 5, "no": 3})
    with patch("sase.gemini_wrapper.wrapper.print_decision_counts") as mock_print:
        wrapper._display_decision_counts()
        mock_print.assert_called_once_with({"yes": 5, "no": 3})

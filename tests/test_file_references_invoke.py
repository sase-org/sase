"""Tests for file-reference processing and shared process streaming."""

import os
import subprocess
import tempfile
from unittest.mock import patch

import pytest
from sase.file_references import process_file_references


def testprocess_file_references_tilde_expansion() -> None:
    """Test that tilde paths are copied with home-relative structure."""
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
                with patch("sase.file_references.print_status"):
                    with patch("sase.file_references.print_file_operation"):
                        result = process_file_references(prompt)

                # The tilde path is replaced with the new artifact-home path.
                assert f"@{tilde_path}" not in result
                assert f"@.sase/artifacts/home/{rel_path}" in result

                # Check that the file was copied with home-relative structure
                copied_file = os.path.join(".sase", "artifacts", "home", rel_path)
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

    with patch("sase.file_references.print_status"):
        with patch("sase.file_references.print_file_operation"):
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
    """Test basic streaming of process output via the shared helper."""
    from sase.llm_provider._subprocess import stream_process_output

    # Create a simple process that outputs to stdout
    process = subprocess.Popen(
        ["echo", "hello world"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    stdout, stderr, return_code = stream_process_output(process, suppress_output=True)

    assert "hello world" in stdout
    assert stderr == ""
    assert return_code == 0

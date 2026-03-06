"""Tests for command substitution and main API in the file_references module."""

import os
import tempfile

import pytest
from sase.gemini_wrapper.file_references import (
    _find_command_substitutions,
    _find_matching_paren,
    process_command_substitution,
    process_file_references,
)

# Tests for process_command_substitution


def test_process_command_substitution_no_pattern() -> None:
    """Test that prompts without $() are returned unchanged."""
    prompt = "This is a regular prompt with no command substitution"
    result = process_command_substitution(prompt)
    assert result == prompt


def test_process_command_substitution_failed_command() -> None:
    """Test that failed commands result in empty string."""
    prompt = "Before $(nonexistent_command_xyz_12345) after"
    result = process_command_substitution(prompt)
    # Failed command should be replaced with empty string
    assert result == "Before  after"


def test_process_command_substitution_unclosed_paren() -> None:
    """Test that unclosed $( is left unchanged."""
    prompt = "Unclosed $(echo hello"
    result = process_command_substitution(prompt)
    assert result == prompt


def test_process_command_substitution_multiline_output() -> None:
    """Test that multiline output is stripped properly."""
    prompt = '$(printf "line1\\nline2")'
    result = process_command_substitution(prompt)
    assert result == "line1\nline2"


# Tests for helper functions


def test_find_matching_paren_nested() -> None:
    """Test finding matching paren with nested parens."""
    text = "a(b)c)"
    result = _find_matching_paren(text, 0)
    assert result == 5


def test_find_command_substitutions_escaped() -> None:
    """Test that escaped $( is skipped."""
    text = "\\$(not a command)"
    result = _find_command_substitutions(text)
    assert len(result) == 0


# Tests for process_file_references with is_home_mode


def test_process_file_references_home_mode_expands_tilde() -> None:
    """Test that home mode expands tilde paths without copying."""
    home = os.path.expanduser("~")

    # Create a temp file in home directory
    with tempfile.NamedTemporaryFile(
        suffix=".txt", dir=home, delete=False, prefix="test_home_mode_"
    ) as f:
        temp_path = f.name
        temp_basename = os.path.basename(temp_path)

    try:
        prompt = f"Check @~/{temp_basename}"
        result = process_file_references(prompt, is_home_mode=True)

        # Should expand tilde to full path
        assert f"@{home}/{temp_basename}" in result
        # Original tilde reference should be gone
        assert f"@~/{temp_basename}" not in result
    finally:
        os.unlink(temp_path)


def test_process_file_references_home_mode_absolute_path_unchanged() -> None:
    """Test that absolute paths without tilde are left unchanged in home mode."""
    # Create a temp file with absolute path
    with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
        temp_path = f.name
        f.write(b"test content")

    try:
        prompt = f"Check @{temp_path}"
        result = process_file_references(prompt, is_home_mode=True)

        # Absolute path without tilde should remain unchanged
        assert f"@{temp_path}" in result
    finally:
        os.unlink(temp_path)


def test_process_file_references_normal_mode_copies_home_files(
    tmp_path: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test that normal mode copies home-dir files to .sase/home/."""
    monkeypatch.chdir(tmp_path)

    home_dir = os.path.expanduser("~")

    # Create a temp file in home directory
    with tempfile.NamedTemporaryFile(
        suffix=".txt", dir=home_dir, delete=False, prefix="test_normal_mode_"
    ) as f:
        temp_path = f.name
        f.write(b"test content")

    try:
        rel_path = os.path.relpath(temp_path, home_dir)
        tilde_path = "~/" + rel_path
        prompt = f"Check @{tilde_path}"
        result = process_file_references(prompt, is_home_mode=False)

        # .sase/home should be created with home-relative structure
        dest_path = os.path.join(tmp_path, ".sase", "home", rel_path)
        assert os.path.exists(dest_path)

        # Prompt should reference the copied file
        assert f"@.sase/home/{rel_path}" in result
    finally:
        os.unlink(temp_path)


def test_process_file_references_normal_mode_non_home_unchanged(
    tmp_path: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test that non-home absolute paths are left unchanged in normal mode."""
    monkeypatch.chdir(tmp_path)

    # Create a temp file outside home directory (in /tmp)
    with tempfile.NamedTemporaryFile(
        suffix=".txt", dir="/tmp", delete=False, prefix="test_non_home_"
    ) as f:
        temp_path = f.name
        f.write(b"test content")

    home_dir = os.path.expanduser("~")
    try:
        # Only run if the file is truly outside home dir
        if temp_path.startswith(home_dir):
            return

        prompt = f"Check @{temp_path}"
        result = process_file_references(prompt, is_home_mode=False)

        # Non-home absolute path should remain unchanged
        assert f"@{temp_path}" in result
        # .sase should NOT be created for non-home files
        assert not os.path.exists(os.path.join(tmp_path, ".sase"))
    finally:
        os.unlink(temp_path)

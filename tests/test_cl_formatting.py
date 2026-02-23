"""Tests for commit_workflow/cl_formatting.py - CL description formatting."""

import tempfile
from pathlib import Path

from sase.commit_workflow.cl_formatting import format_cl_description


def test_format_cl_description_empty_content() -> None:
    """Test format_cl_description handles empty file content."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write("")
        temp_path = f.name

    try:
        format_cl_description(temp_path, "proj", bug="b/0")

        content = Path(temp_path).read_text()
        # Should have [proj] followed by empty content and metadata
        assert content.startswith("[proj] \n")
        assert "BUG=b/0" in content
    finally:
        Path(temp_path).unlink()


def test_format_cl_description_fixed_bug_mutually_exclusive_with_bug() -> None:
    """Test format_cl_description uses FIXED= when fixed_bug is set, ignoring bug."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write("Description")
        temp_path = f.name

    try:
        # fixed_bug takes precedence over bug
        format_cl_description(temp_path, "proj", bug="111", fixed_bug="222")

        content = Path(temp_path).read_text()
        # Should have FIXED= tag (fixed_bug takes precedence)
        assert "FIXED=222" in content
        assert "BUG=" not in content
    finally:
        Path(temp_path).unlink()


def test_format_cl_description_no_bug_or_fixed() -> None:
    """Test format_cl_description with neither bug nor fixed_bug."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write("No bug description")
        temp_path = f.name

    try:
        format_cl_description(temp_path, "myproject")

        content = Path(temp_path).read_text()
        # Should have neither BUG= nor FIXED= tag
        assert "BUG=" not in content
        assert "FIXED=" not in content
        # Other metadata should still be present
        assert "MARKDOWN=true" in content
    finally:
        Path(temp_path).unlink()


def test_format_cl_description_git() -> None:
    """Test format_cl_description in git mode only writes project-prefixed description."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write("Add new feature")
        temp_path = f.name

    try:
        format_cl_description(temp_path, "myproject", bug="b/12345", vcs_type="git")

        content = Path(temp_path).read_text()
        # Should have project-prefixed description
        assert content == "[myproject] Add new feature\n"
        # Should NOT have any metadata tags
        assert "AUTOSUBMIT_BEHAVIOR" not in content
        assert "BUG=" not in content
        assert "MARKDOWN" not in content
        assert "R=startblock" not in content
        assert "STARTBLOCK_AUTOSUBMIT" not in content
        assert "WANT_LGTM" not in content
    finally:
        Path(temp_path).unlink()

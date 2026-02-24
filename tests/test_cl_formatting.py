"""Tests for commit_workflow/cl_formatting.py - CL description formatting."""

import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

from sase.commit_workflow.cl_formatting import format_cl_description
from sase.workspace_provider._hookspec import hookimpl


class _MockHgPlugin:
    """Minimal hg workspace plugin for testing commit description formatting."""

    @hookimpl
    def ws_format_commit_description(
        self,
        file_path: str,
        project: str,
        workflow_type: str,
        bug: str | None,
        fixed_bug: str | None,
    ) -> bool | None:
        if workflow_type != "hg":
            return None
        with open(file_path, encoding="utf-8") as f:
            content = f.read()
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(f"[{project}] {content}\n")
            f.write("\n")
            f.write("AUTOSUBMIT_BEHAVIOR=SYNC_SUBMIT\n")
            if fixed_bug:
                f.write(f"FIXED={fixed_bug}\n")
            elif bug:
                f.write(f"BUG={bug}\n")
            f.write("MARKDOWN=true\n")
            f.write("R=startblock\n")
            f.write("STARTBLOCK_AUTOSUBMIT=yes\n")
            f.write("WANT_LGTM=all\n")
        return True


@pytest.fixture(autouse=True)
def _register_mock_hg_plugin() -> Iterator[None]:
    """Register a mock hg plugin so hg formatting tests work without sase-hg."""
    from sase.workspace_provider._registry import _get_manager

    manager = _get_manager()
    plugin = _MockHgPlugin()
    manager._pm.register(plugin)
    yield  # type: ignore[func-returns-value]
    manager._pm.unregister(plugin)


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

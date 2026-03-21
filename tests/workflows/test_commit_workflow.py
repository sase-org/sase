"""Tests for commit workflow operations."""

import importlib.machinery
import importlib.util
import tempfile
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sase.workflows.commit.changespec_operations import (
    _find_changespec_end_line,
)
from sase.workflows.commit.changespec_queries import (
    changespec_exists,
    project_file_exists,
)
from sase.workflows.commit.editor_utils import get_editor


def test_project_file_exists_false() -> None:
    """Test project_file_exists returns False for non-existent project."""
    assert project_file_exists("nonexistent_project_xyz123") is False


def test_changespec_exists_no_project_file() -> None:
    """Test changespec_exists returns False when project file doesn't exist."""
    assert changespec_exists("nonexistent_project_xyz123", "some_cl") is False


def test_changespec_exists_multiple_changespecs() -> None:
    """Test changespec_exists finds NAME among multiple ChangeSpecs."""
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".gp") as f:
        f.write("")
        f.write("NAME: feature_a\n")
        f.write("DESCRIPTION:\n  Feature A\n")
        f.write("PARENT: None\n")
        f.write("CL: None\n")
        f.write("STATUS: Unstarted\n\n")
        f.write("NAME: feature_b\n")
        f.write("DESCRIPTION:\n  Feature B\n")
        f.write("PARENT: feature_a\n")
        f.write("CL: http://cl/123\n")
        f.write("STATUS: Mailed\n")
        project_file = f.name

    try:
        with patch(
            "sase.workflows.commit.changespec_queries.get_project_file_path",
            return_value=project_file,
        ):
            assert changespec_exists("testproj", "feature_a") is True
            assert changespec_exists("testproj", "feature_b") is True
            assert changespec_exists("testproj", "feature_c") is False
    finally:
        Path(project_file).unlink()


def test_get_editor_uses_env_variable() -> None:
    """Test that get_editor uses EDITOR environment variable."""
    with patch.dict("os.environ", {"EDITOR": "emacs"}):
        assert get_editor() == "emacs"


def test_get_editor_falls_back_to_nvim() -> None:
    """Test that get_editor falls back to nvim if EDITOR not set."""
    with patch.dict("os.environ", {}, clear=True):
        mock_result = MagicMock()
        mock_result.returncode = 0
        with patch("subprocess.run", return_value=mock_result):
            # Remove EDITOR from env
            with patch.dict("os.environ", {"EDITOR": ""}, clear=False):
                import os

                if "EDITOR" in os.environ:
                    del os.environ["EDITOR"]
                result = get_editor()
                # Should be nvim since which nvim succeeds
                assert result == "nvim"


def test_get_editor_falls_back_to_vim() -> None:
    """Test that get_editor falls back to vim if nvim not found."""
    with patch.dict("os.environ", {}, clear=True):
        mock_result = MagicMock()
        mock_result.returncode = 1  # nvim not found
        with patch("subprocess.run", return_value=mock_result):
            result = get_editor()
            assert result == "vim"


def test_find_changespec_end_line_multiple_changespecs() -> None:
    """Test finding end of ChangeSpec when multiple exist."""
    lines = [
        "# Project file\n",
        "\n",
        "NAME: feature_a\n",
        "DESCRIPTION:\n",
        "  A feature\n",
        "PARENT: None\n",
        "CL: None\n",
        "STATUS: Unstarted\n",
        "\n",
        "\n",
        "NAME: feature_b\n",
        "DESCRIPTION:\n",
        "  B feature\n",
        "PARENT: feature_a\n",
        "CL: http://cl/123\n",
        "STATUS: Mailed\n",
    ]
    # feature_a ends at line 7 (STATUS: Unstarted)
    assert _find_changespec_end_line(lines, "feature_a") == 7
    # feature_b ends at line 15 (STATUS: Mailed)
    assert _find_changespec_end_line(lines, "feature_b") == 15


def test_find_changespec_end_line_not_found() -> None:
    """Test when ChangeSpec is not found."""
    lines = [
        "# Project file\n",
        "\n",
        "NAME: feature_a\n",
        "STATUS: Unstarted\n",
    ]
    assert _find_changespec_end_line(lines, "nonexistent") is None


# --- Tests for _get_cl_description from sase_cl_workflow ---

_CL_WORKFLOW_SCRIPT = (
    Path(__file__).parent.parent / "src" / "sase" / "scripts" / "sase_cl_workflow"
)
_SKIP_REASON = "sase_cl_workflow script not available"


def _load_cl_workflow_module() -> types.ModuleType:
    """Load sase_cl_workflow as a Python module."""
    script_path = str(_CL_WORKFLOW_SCRIPT)
    loader = importlib.machinery.SourceFileLoader("sase_cl_workflow", script_path)
    spec = importlib.util.spec_from_loader("sase_cl_workflow", loader)
    assert spec is not None
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


@pytest.mark.skipif(not _CL_WORKFLOW_SCRIPT.exists(), reason=_SKIP_REASON)
def test_get_cl_description_valid_file() -> None:
    """Test that a valid pre-generated description file is used."""
    mod = _load_cl_workflow_module()
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".md") as f:
        f.write("Pre-generated CL description\n")
        desc_file = f.name
    try:
        result = mod._get_cl_description("some response", desc_file)
        assert result == "Pre-generated CL description"
    finally:
        Path(desc_file).unlink()


@pytest.mark.skipif(not _CL_WORKFLOW_SCRIPT.exists(), reason=_SKIP_REASON)
def test_get_cl_description_empty_path_falls_back() -> None:
    """Test that empty string path falls back to get_file_summary."""
    mod = _load_cl_workflow_module()
    with patch(
        "sase.summarize_utils.get_file_summary", return_value="Summarized description"
    ):
        result = mod._get_cl_description("some response", "")
    assert result == "Summarized description"


@pytest.mark.skipif(not _CL_WORKFLOW_SCRIPT.exists(), reason=_SKIP_REASON)
def test_get_cl_description_nonexistent_file_falls_back() -> None:
    """Test that a nonexistent file path falls back to get_file_summary."""
    mod = _load_cl_workflow_module()
    with patch(
        "sase.summarize_utils.get_file_summary", return_value="Summarized description"
    ):
        result = mod._get_cl_description("some response", "/nonexistent/path.md")
    assert result == "Summarized description"


@pytest.mark.skipif(not _CL_WORKFLOW_SCRIPT.exists(), reason=_SKIP_REASON)
def test_get_cl_description_empty_file_falls_back() -> None:
    """Test that an empty file falls back to get_file_summary."""
    mod = _load_cl_workflow_module()
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".md") as f:
        f.write("")
        desc_file = f.name
    try:
        with patch(
            "sase.summarize_utils.get_file_summary",
            return_value="Summarized description",
        ):
            result = mod._get_cl_description("some response", desc_file)
        assert result == "Summarized description"
    finally:
        Path(desc_file).unlink()

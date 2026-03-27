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
from sase.workflows.commit.changespec_queries import changespec_exists
from sase.workflows.commit.editor_utils import get_editor
from sase.workflows.commit.workflow import CommitWorkflow


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
        "sase.ace.hooks.summarize_utils.get_file_summary",
        return_value="Summarized description",
    ):
        result = mod._get_cl_description("some response", "")
    assert result == "Summarized description"


@pytest.mark.skipif(not _CL_WORKFLOW_SCRIPT.exists(), reason=_SKIP_REASON)
def test_get_cl_description_nonexistent_file_falls_back() -> None:
    """Test that a nonexistent file path falls back to get_file_summary."""
    mod = _load_cl_workflow_module()
    with patch(
        "sase.ace.hooks.summarize_utils.get_file_summary",
        return_value="Summarized description",
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
            "sase.ace.hooks.summarize_utils.get_file_summary",
            return_value="Summarized description",
        ):
            result = mod._get_cl_description("some response", desc_file)
        assert result == "Summarized description"
    finally:
        Path(desc_file).unlink()


# --- _detect_parent_changespec ---


def _make_workflow(name: str = "child_cl") -> CommitWorkflow:
    """Create a CommitWorkflow configured for create_pull_request."""
    return CommitWorkflow(payload={"name": name}, method="create_pull_request")


def test_detect_parent_returns_branch_cl_when_changespec_exists() -> None:
    """Returns branch name when it matches an existing ChangeSpec."""
    wf = _make_workflow()
    wf._base_cl_name = "child_cl"
    mock_cs = MagicMock()
    mock_cs.name = "parent_feature"
    with (
        patch(
            "sase.workflows.utils.get_cl_name_from_branch",
            return_value="parent_feature",
        ),
        patch(
            "sase.workflows.utils.get_project_from_workspace",
            return_value="proj",
        ),
        patch(
            "sase.workflows.utils.get_project_file_path",
            return_value="/fake/proj.gp",
        ),
        patch(
            "sase.workflows.utils.get_changespec_from_file",
            return_value=mock_cs,
        ),
    ):
        assert wf._detect_parent_changespec() == "parent_feature"


def test_detect_parent_returns_none_when_no_branch() -> None:
    """Returns None when get_cl_name_from_branch fails."""
    wf = _make_workflow()
    with patch(
        "sase.workflows.utils.get_cl_name_from_branch",
        return_value=None,
    ):
        assert wf._detect_parent_changespec() is None


def test_detect_parent_returns_none_when_no_changespec() -> None:
    """Returns None when branch has no ChangeSpec."""
    wf = _make_workflow()
    wf._base_cl_name = "child_cl"
    with (
        patch(
            "sase.workflows.utils.get_cl_name_from_branch",
            return_value="some_branch",
        ),
        patch(
            "sase.workflows.utils.get_project_from_workspace",
            return_value="proj",
        ),
        patch(
            "sase.workflows.utils.get_project_file_path",
            return_value="/fake/proj.gp",
        ),
        patch(
            "sase.workflows.utils.get_changespec_from_file",
            return_value=None,
        ),
    ):
        assert wf._detect_parent_changespec() is None


def test_detect_parent_returns_none_when_self_parent() -> None:
    """Returns None when branch name matches the new CL name."""
    wf = _make_workflow(name="same_name")
    wf._base_cl_name = "same_name"
    with patch(
        "sase.workflows.utils.get_cl_name_from_branch",
        return_value="same_name",
    ):
        assert wf._detect_parent_changespec() is None


# --- _append_commits_entry (human CLI path, no env vars) ---


def _make_commit_workflow(
    message: str = "Fix a bug",
    note: str | None = None,
    method: str = "create_commit",
) -> CommitWorkflow:
    """Create a CommitWorkflow for commit/proposal tests."""
    payload: dict = {"message": message}
    if note is not None:
        payload["note"] = note
    return CommitWorkflow(payload=payload, method=method)


def test_append_commits_entry_human_cli_uses_note(tmp_path: Path) -> None:
    """--note value is used as the COMMITS entry text (no env vars)."""
    project_file = tmp_path / "proj.gp"
    project_file.write_text(
        "NAME: my_branch\nDESCRIPTION:\n  desc\nCOMMITS:\nSTATUS: Pending\n"
    )

    wf = _make_commit_workflow(note="[man] Revert BUILD changes")
    wf._cl_name = "my_branch"
    wf._project_file = str(project_file)

    entry_id = wf._append_commits_entry()
    assert entry_id == "1"

    content = project_file.read_text()
    assert "[man] Revert BUILD changes" in content


def test_append_commits_entry_human_cli_falls_back_to_message(tmp_path: Path) -> None:
    """First line of commit message is used when --note is absent."""
    project_file = tmp_path / "proj.gp"
    project_file.write_text(
        "NAME: my_branch\nDESCRIPTION:\n  desc\nCOMMITS:\nSTATUS: Pending\n"
    )

    wf = _make_commit_workflow(message="First line\nSecond line")
    wf._cl_name = "my_branch"
    wf._project_file = str(project_file)

    entry_id = wf._append_commits_entry()
    assert entry_id == "1"

    content = project_file.read_text()
    assert "First line" in content
    assert "Second line" not in content


def test_append_commits_entry_returns_none_without_project_file() -> None:
    """Returns None when project file cannot be resolved."""
    wf = _make_commit_workflow()
    wf._cl_name = "my_branch"
    wf._project_file = None

    assert wf._append_commits_entry() is None


def test_append_commits_entry_returns_none_without_cl_name(tmp_path: Path) -> None:
    """Returns None when CL name cannot be resolved."""
    project_file = tmp_path / "proj.gp"
    project_file.write_text("NAME: x\nSTATUS: Pending\n")

    wf = _make_commit_workflow()
    wf._cl_name = None
    wf._project_file = str(project_file)

    assert wf._append_commits_entry() is None


def test_append_commits_entry_includes_diff_path(tmp_path: Path) -> None:
    """Diff path captured pre-commit is included in the COMMITS entry."""
    project_file = tmp_path / "proj.gp"
    project_file.write_text(
        "NAME: my_branch\nDESCRIPTION:\n  desc\nCOMMITS:\nSTATUS: Pending\n"
    )
    diff_file = tmp_path / "my.diff"
    diff_file.write_text("diff content")

    wf = _make_commit_workflow(note="with diff")
    wf._cl_name = "my_branch"
    wf._project_file = str(project_file)
    wf._diff_path = str(diff_file)

    entry_id = wf._append_commits_entry()
    assert entry_id == "1"

    content = project_file.read_text()
    assert f"DIFF: {diff_file}" in content


# --- _capture_pre_commit_diff fallback ---


def test_capture_pre_commit_diff_fallback_to_sase_diffs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Diff is saved to ~/.sase/diffs/ when SASE_ARTIFACTS_DIR is not set."""
    monkeypatch.delenv("SASE_ARTIFACTS_DIR", raising=False)
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))

    wf = _make_commit_workflow()
    wf._cl_name = "my_branch"

    mock_provider = MagicMock()
    mock_provider.diff.return_value = (True, "diff --git a/f b/f\n+hello\n")

    wf._capture_pre_commit_diff(mock_provider, str(tmp_path))

    assert wf._diff_path is not None
    assert wf._diff_path.startswith(str(fake_home / ".sase" / "diffs"))
    assert wf._diff_path.endswith(".diff")
    assert "my_branch" in wf._diff_path
    assert Path(wf._diff_path).read_text() == "diff --git a/f b/f\n+hello\n"


def test_capture_pre_commit_diff_skips_without_cl_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Diff capture is skipped when neither SASE_ARTIFACTS_DIR nor cl_name is available."""
    monkeypatch.delenv("SASE_ARTIFACTS_DIR", raising=False)

    wf = _make_commit_workflow()
    wf._cl_name = None

    mock_provider = MagicMock()
    wf._capture_pre_commit_diff(mock_provider, "/tmp")

    assert wf._diff_path is None
    mock_provider.diff.assert_not_called()

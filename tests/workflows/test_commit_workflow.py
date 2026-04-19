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
from sase.workflows.commit.commit_tracking import (
    append_commits_entry,
    capture_pre_commit_diff,
)
from sase.workflows.commit.editor_utils import get_editor
from sase.workflows.commit.pr_operations import detect_parent_changespec
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


def test_detect_parent_returns_branch_cl_when_changespec_exists() -> None:
    """Returns branch name when it matches an existing ChangeSpec."""
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
        assert (
            detect_parent_changespec("child_cl", {"name": "child_cl"})
            == "parent_feature"
        )


def test_detect_parent_returns_none_when_no_branch() -> None:
    """Returns None when get_cl_name_from_branch fails."""
    with patch(
        "sase.workflows.utils.get_cl_name_from_branch",
        return_value=None,
    ):
        assert detect_parent_changespec("child_cl", {"name": "child_cl"}) is None


def test_detect_parent_returns_none_when_no_changespec() -> None:
    """Returns None when branch has no ChangeSpec."""
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
        assert detect_parent_changespec("child_cl", {"name": "child_cl"}) is None


def test_detect_parent_returns_none_when_self_parent() -> None:
    """Returns None when branch name matches the new CL name."""
    with patch(
        "sase.workflows.utils.get_cl_name_from_branch",
        return_value="same_name",
    ):
        assert detect_parent_changespec("same_name", {"name": "same_name"}) is None


def test_explicit_parent_overrides_auto_detect() -> None:
    """Explicit parent in payload takes precedence over auto-detection."""
    wf = CommitWorkflow(
        payload={"name": "child_cl", "parent": "explicit_parent"},
        method="create_pull_request",
    )
    wf._base_cl_name = "child_cl"
    # Mock enough to reach parent resolution: precommit must succeed,
    # then we let the VCS dispatch fail to stop execution after parent
    # is set.
    mock_provider = MagicMock()
    mock_provider.create_pull_request.return_value = (False, "stopped")
    mock_provider.is_sync_in_progress.return_value = False
    mock_provider.get_conflicted_files.return_value = []
    with (
        patch("sase.workflows.commit.workflow.handle_beads"),
        patch("sase.workflows.commit.workflow.handle_sase_plan"),
        patch("sase.workflows.commit.workflow.run_precommit", return_value=True),
        patch("sase.workflows.commit.workflow.apply_project_pr_prefix"),
        patch("sase.workflows.commit.workflow.append_pr_tags"),
        patch("sase.workflows.commit.workflow.build_pr_body"),
        patch(
            "sase.workflows.commit.workflow.get_vcs_provider",
            return_value=mock_provider,
        ),
        patch(
            "sase.workflows.utils.get_project_from_workspace",
            return_value=None,
        ),
    ):
        wf.run()
    assert wf._parent_cl_name == "explicit_parent"


def test_explicit_parent_skips_auto_detect() -> None:
    """When parent is in payload, detect_parent_changespec is not called."""
    wf = CommitWorkflow(
        payload={"name": "child_cl", "parent": "given_parent"},
        method="create_pull_request",
    )
    wf._base_cl_name = "child_cl"
    mock_provider = MagicMock()
    mock_provider.create_pull_request.return_value = (False, "stopped")
    mock_provider.is_sync_in_progress.return_value = False
    mock_provider.get_conflicted_files.return_value = []
    with (
        patch("sase.workflows.commit.workflow.handle_beads"),
        patch("sase.workflows.commit.workflow.handle_sase_plan"),
        patch("sase.workflows.commit.workflow.run_precommit", return_value=True),
        patch("sase.workflows.commit.workflow.apply_project_pr_prefix"),
        patch("sase.workflows.commit.workflow.append_pr_tags"),
        patch("sase.workflows.commit.workflow.build_pr_body"),
        patch(
            "sase.workflows.commit.workflow.get_vcs_provider",
            return_value=mock_provider,
        ),
        patch(
            "sase.workflows.utils.get_project_from_workspace",
            return_value=None,
        ),
        patch("sase.workflows.commit.workflow.detect_parent_changespec") as mock_detect,
    ):
        wf.run()
    mock_detect.assert_not_called()


def test_unresolvable_explicit_parent_is_dropped() -> None:
    """Bogus ``-p`` values (e.g., a VCS ref like ``p4head``) get dropped early.

    Regression: previously the string was threaded through to the ChangeSpec
    PARENT field verbatim. Now the workflow verifies the parent resolves and
    warns + clears it when it does not.
    """
    wf = CommitWorkflow(
        payload={"name": "child_cl", "parent": "p4head"},
        method="create_pull_request",
    )
    wf._base_cl_name = "child_cl"
    mock_provider = MagicMock()
    mock_provider.create_pull_request.return_value = (False, "stopped")
    mock_provider.is_sync_in_progress.return_value = False
    mock_provider.get_conflicted_files.return_value = []
    with (
        patch("sase.workflows.commit.workflow.handle_beads"),
        patch("sase.workflows.commit.workflow.handle_sase_plan"),
        patch("sase.workflows.commit.workflow.run_precommit", return_value=True),
        patch("sase.workflows.commit.workflow.apply_project_pr_prefix"),
        patch("sase.workflows.commit.workflow.append_pr_tags"),
        patch("sase.workflows.commit.workflow.build_pr_body"),
        patch(
            "sase.workflows.commit.workflow.get_vcs_provider",
            return_value=mock_provider,
        ),
        patch(
            "sase.workflows.commit.workflow._explicit_parent_resolves",
            return_value=False,
        ),
    ):
        wf.run()
    assert wf._parent_cl_name is None
    assert "parent" not in wf._payload


def test_resolvable_explicit_parent_is_kept() -> None:
    """A real existing parent name is kept when the resolver confirms it."""
    wf = CommitWorkflow(
        payload={"name": "child_cl", "parent": "real_parent"},
        method="create_pull_request",
    )
    wf._base_cl_name = "child_cl"
    mock_provider = MagicMock()
    mock_provider.create_pull_request.return_value = (False, "stopped")
    mock_provider.is_sync_in_progress.return_value = False
    mock_provider.get_conflicted_files.return_value = []
    with (
        patch("sase.workflows.commit.workflow.handle_beads"),
        patch("sase.workflows.commit.workflow.handle_sase_plan"),
        patch("sase.workflows.commit.workflow.run_precommit", return_value=True),
        patch("sase.workflows.commit.workflow.apply_project_pr_prefix"),
        patch("sase.workflows.commit.workflow.append_pr_tags"),
        patch("sase.workflows.commit.workflow.build_pr_body"),
        patch(
            "sase.workflows.commit.workflow.get_vcs_provider",
            return_value=mock_provider,
        ),
        patch(
            "sase.workflows.commit.workflow._explicit_parent_resolves",
            return_value=True,
        ),
    ):
        wf.run()
    assert wf._parent_cl_name == "real_parent"


# --- _append_commits_entry (human CLI path, no env vars) ---


def test_append_commits_entry_uses_message_first_line(tmp_path: Path) -> None:
    """First line of commit message is used as the COMMITS entry text."""
    project_file = tmp_path / "proj.gp"
    project_file.write_text(
        "NAME: my_branch\nDESCRIPTION:\n  desc\nCOMMITS:\nSTATUS: Pending\n"
    )

    entry_id = append_commits_entry(
        str(project_file),
        "my_branch",
        {"message": "First line\nSecond line"},
        "create_commit",
        None,
    )
    assert entry_id == "1"

    content = project_file.read_text()
    assert "First line" in content
    assert "Second line" not in content


def test_append_commits_entry_returns_none_without_project_file() -> None:
    """Returns None when project file cannot be resolved."""
    assert (
        append_commits_entry(
            None, "my_branch", {"message": "Fix a bug"}, "create_commit", None
        )
        is None
    )


def test_append_commits_entry_returns_none_without_cl_name(tmp_path: Path) -> None:
    """Returns None when CL name cannot be resolved."""
    project_file = tmp_path / "proj.gp"
    project_file.write_text("NAME: x\nSTATUS: Pending\n")

    assert (
        append_commits_entry(
            str(project_file), None, {"message": "Fix a bug"}, "create_commit", None
        )
        is None
    )


def test_append_commits_entry_includes_diff_path(tmp_path: Path) -> None:
    """Diff path captured pre-commit is included in the COMMITS entry."""
    project_file = tmp_path / "proj.gp"
    project_file.write_text(
        "NAME: my_branch\nDESCRIPTION:\n  desc\nCOMMITS:\nSTATUS: Pending\n"
    )
    diff_file = tmp_path / "my.diff"
    diff_file.write_text("diff content")

    entry_id = append_commits_entry(
        str(project_file),
        "my_branch",
        {"message": "with diff"},
        "create_commit",
        str(diff_file),
    )
    assert entry_id == "1"

    content = project_file.read_text()
    assert f"DIFF: {diff_file}" in content


# --- capture_pre_commit_diff fallback ---


def test_capture_pre_commit_diff_fallback_to_sase_diffs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Diff is saved to ~/.sase/diffs/ when SASE_ARTIFACTS_DIR is not set."""
    monkeypatch.delenv("SASE_ARTIFACTS_DIR", raising=False)
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))

    mock_provider = MagicMock()
    mock_provider.diff.return_value = (True, "diff --git a/f b/f\n+hello\n")

    diff_path = capture_pre_commit_diff(mock_provider, str(tmp_path), "my_branch")

    assert diff_path is not None
    assert diff_path.startswith(str(fake_home / ".sase" / "diffs"))
    assert diff_path.endswith(".diff")
    assert "my_branch" in diff_path
    assert Path(diff_path).read_text() == "diff --git a/f b/f\n+hello\n"


def test_capture_pre_commit_diff_skips_without_cl_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Diff capture is skipped when neither SASE_ARTIFACTS_DIR nor cl_name is available."""
    monkeypatch.delenv("SASE_ARTIFACTS_DIR", raising=False)

    mock_provider = MagicMock()
    diff_path = capture_pre_commit_diff(mock_provider, "/tmp", None)

    assert diff_path is None
    mock_provider.diff.assert_not_called()


# --- Precommit runs for SDD commits ---


def test_precommit_runs_during_sdd_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression: run_precommit() must execute when sase commit is used for SDD files."""
    monkeypatch.delenv("SASE_PLAN", raising=False)
    monkeypatch.chdir(tmp_path)

    payload = {
        "message": "chore: Add SDD spec and plan for my_plan",
        "files": [
            str(tmp_path / "specs" / "my_plan.md"),
            str(tmp_path / "plans" / "my_plan.md"),
        ],
    }
    wf = CommitWorkflow(payload=payload, method="create_commit")

    # Make run_precommit fail so the workflow exits early — we only
    # need to confirm it was called, not that the full workflow succeeds.
    mock_precommit = MagicMock(return_value=False)

    with patch("sase.workflows.commit.workflow.run_precommit", mock_precommit):
        wf.run()

    mock_precommit.assert_called_once()
    assert isinstance(mock_precommit.call_args[0][0], str)  # cwd arg

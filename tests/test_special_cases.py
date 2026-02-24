"""Tests for special case handling in sase run command."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sase.main.query_handler.special_cases import (
    _resolve_vcs_project_info,
    handle_run_special_cases,
)


def test_vcs_dot_prompt_single_arg_triggers_history_picker() -> None:
    """Test that '#gh:sase .' as a single arg triggers the prompt history picker."""
    mock_picker = MagicMock(return_value="selected prompt")
    with (
        patch(
            "sase.main.query_handler.special_cases.show_prompt_history_picker",
            mock_picker,
        ),
        patch(
            "sase.main.query_handler.special_cases._resolve_vcs_project_info",
            return_value=("sase", "sase"),
        ),
        patch("sase.main.query_handler.special_cases.run_query") as mock_run,
        patch(
            "sase.workspace_provider.get_workflow_names",
            return_value={"gh", "git", "hg"},
        ),
        pytest.raises(SystemExit),
    ):
        handle_run_special_cases(["#gh:sase ."])

    mock_picker.assert_called_once_with(sort_by="sase", workspace="sase")
    mock_run.assert_called_once_with("#gh:sase selected prompt")


def test_vcs_dot_prompt_strips_cross_vcs_prefix() -> None:
    """Test that a different VCS tag is stripped when reusing via another VCS.

    E.g., selecting a prompt originally used with #git:repo while now
    using #gh:sase should strip the #git:repo prefix.
    """
    mock_picker = MagicMock(return_value="#git:repo do something cool")
    with (
        patch(
            "sase.main.query_handler.special_cases.show_prompt_history_picker",
            mock_picker,
        ),
        patch(
            "sase.main.query_handler.special_cases._resolve_vcs_project_info",
            return_value=("sase", "sase"),
        ),
        patch("sase.main.query_handler.special_cases.run_query") as mock_run,
        patch(
            "sase.workspace_provider.get_workflow_names",
            return_value={"gh", "git", "hg"},
        ),
        pytest.raises(SystemExit),
    ):
        handle_run_special_cases(["#gh:sase", "."])

    # Should strip #git:repo and prepend #gh:sase
    mock_run.assert_called_once_with("#gh:sase do something cool")


def test_resolve_vcs_project_info_repo_path_trailing_slash() -> None:
    """Test resolving a repo path with trailing slashes."""
    sort_by, workspace = _resolve_vcs_project_info("user/project/")
    assert workspace == "project"


def test_resolve_vcs_project_info_project_shorthand(tmp_path: Path) -> None:
    """Test resolving a known project shorthand."""
    projects_base = tmp_path / ".sase" / "projects"
    project_dir = projects_base / "sase"
    project_dir.mkdir(parents=True)

    with patch(
        "sase.main.query_handler.special_cases.Path.home", return_value=tmp_path
    ):
        sort_by, workspace = _resolve_vcs_project_info("sase")
    assert sort_by == "sase"
    assert workspace == "sase"


def test_resolve_vcs_project_info_changespec_name() -> None:
    """Test resolving a ChangeSpec name to its project."""

    class FakeChangeSpec:
        name = "my_cl"
        project_basename = "myproject"

    with (
        patch(
            "sase.main.query_handler.special_cases.Path.home",
            return_value=Path("/nonexistent"),
        ),
        patch(
            "sase.ace.changespec.find_all_changespecs",
            return_value=[FakeChangeSpec()],
        ),
    ):
        sort_by, workspace = _resolve_vcs_project_info("my_cl")
    assert sort_by == "my_cl"
    assert workspace == "myproject"


def test_resolve_vcs_project_info_fallback() -> None:
    """Test fallback when ref doesn't match anything known."""
    with (
        patch(
            "sase.main.query_handler.special_cases.Path.home",
            return_value=Path("/nonexistent"),
        ),
        patch(
            "sase.ace.changespec.find_all_changespecs",
            return_value=[],
        ),
    ):
        sort_by, workspace = _resolve_vcs_project_info("unknown_ref")
    assert sort_by == "unknown_ref"
    assert workspace == "unknown_ref"

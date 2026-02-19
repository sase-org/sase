"""Tests for special case handling in sase run command."""

from pathlib import Path
from unittest.mock import patch

from sase.main.query_handler.special_cases import _resolve_vcs_project_info


def test_resolve_vcs_project_info_repo_path() -> None:
    """Test resolving a user/project repo path."""
    sort_by, workspace = _resolve_vcs_project_info("bbugyi200/sase")
    assert sort_by == "bbugyi200/sase"
    assert workspace == "sase"


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

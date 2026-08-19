"""Tests for RUNNING field workspace-directory resolution."""

from pathlib import Path
from unittest.mock import patch

import pytest

from sase.running_field import get_workspace_directory_for_num
from sase.running_field import (
    get_workspace_directory as get_workspace_dir,
)


def test_running_field_get_workspace_directory_plugin_failure() -> None:
    """Test get_workspace_directory raises on plugin failure."""
    with patch(
        "sase.workspace_provider._registry.detect_workflow_type",
        side_effect=ValueError("No workspace plugin detected"),
    ):
        with pytest.raises(RuntimeError, match="No workspace plugin detected"):
            get_workspace_dir("myproject")


def test_running_field_get_workspace_directory_falls_back_to_workspace_dir(
    tmp_path: Path,
) -> None:
    """When no plugin claims the project, a configured WORKSPACE_DIR is used."""
    workspace_dir = tmp_path / "checkout"
    workspace_dir.mkdir()

    project_file = tmp_path / "myproject.sase"
    project_file.write_text(
        f"WORKSPACE_DIR: {workspace_dir}\nNAME: my\n", encoding="utf-8"
    )

    with (
        patch(
            "sase.workflows.utils.get_project_file_path",
            return_value=str(project_file),
        ),
        patch(
            "sase.workspace_provider.detect_workflow_type",
            side_effect=ValueError("No workspace plugin detected"),
        ),
    ):
        result = get_workspace_dir("myproject", 1)

    assert result == str(workspace_dir)


def test_running_field_get_workspace_directory_fallback_uses_git_clone(
    tmp_path: Path,
) -> None:
    """Numbered workspaces fall back to ``ensure_workspace_checkout`` for git checkouts."""
    workspace_dir = tmp_path / "checkout"
    workspace_dir.mkdir()
    (workspace_dir / ".git").mkdir()

    project_file = tmp_path / "myproject.sase"
    project_file.write_text(
        f"WORKSPACE_DIR: {workspace_dir}\nNAME: my\n", encoding="utf-8"
    )

    with (
        patch(
            "sase.workflows.utils.get_project_file_path",
            return_value=str(project_file),
        ),
        patch(
            "sase.workspace_provider.detect_workflow_type",
            side_effect=ValueError("No workspace plugin detected"),
        ),
        patch(
            "sase.workspace_provider.utils.ensure_workspace_checkout",
            return_value="/fake/clones/myproject_3/",
        ) as mock_ensure,
    ):
        result = get_workspace_dir("myproject", 3)

    assert result == "/fake/clones/myproject_3/"
    mock_ensure.assert_called_once_with(str(workspace_dir), 3)


def test_running_field_get_workspace_directory_fallback_skips_non_git_share(
    tmp_path: Path,
) -> None:
    """Without a git checkout, numbered workspaces still raise the plugin error."""
    workspace_dir = tmp_path / "checkout"
    workspace_dir.mkdir()  # no .git inside

    project_file = tmp_path / "myproject.sase"
    project_file.write_text(
        f"WORKSPACE_DIR: {workspace_dir}\nNAME: my\n", encoding="utf-8"
    )

    with (
        patch(
            "sase.workflows.utils.get_project_file_path",
            return_value=str(project_file),
        ),
        patch(
            "sase.workspace_provider.detect_workflow_type",
            side_effect=ValueError("No workspace plugin detected"),
        ),
    ):
        with pytest.raises(RuntimeError, match="No workspace plugin detected"):
            get_workspace_dir("myproject", 3)


def test_get_workspace_directory_for_num_main() -> None:
    """Test getting main workspace directory."""
    with patch(
        "sase.running_field._workspace.get_workspace_directory",
        return_value="/cloud/myproject/google3",
    ) as mock_get_ws:
        workspace_dir, suffix = get_workspace_directory_for_num(1, "myproject")
        assert workspace_dir == "/cloud/myproject/google3"
        assert suffix is None
        mock_get_ws.assert_called_once_with("myproject", 1)


def test_get_workspace_directory_for_num_share() -> None:
    """Test getting workspace share directory."""
    with patch(
        "sase.running_field._workspace.get_workspace_directory",
        return_value="/cloud/myproject_3/google3",
    ) as mock_get_ws:
        workspace_dir, suffix = get_workspace_directory_for_num(3, "myproject")
        assert workspace_dir == "/cloud/myproject_3/google3"
        assert suffix == "myproject_3"
        mock_get_ws.assert_called_once_with("myproject", 3)

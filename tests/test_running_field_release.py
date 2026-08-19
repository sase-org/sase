"""Tests for RUNNING field claim release."""

from pathlib import Path

from sase.running_field import (
    WorkspaceClaim,
    get_claimed_workspaces,
    release_workspace,
)
from tests._running_field_helpers import create_project_file_with_running


def test_release_workspace_single(tmp_path: Path) -> None:
    """Test releasing the only workspace claim."""
    project_file = create_project_file_with_running(
        tmp_path, running_claims=[WorkspaceClaim(1, "crs", "feature", pid=12345)]
    )
    try:
        result = release_workspace(project_file, 1)
        assert result.success is True

        with open(project_file) as f:
            content = f.read()

        # RUNNING field should be removed entirely
        assert "RUNNING:" not in content
    finally:
        Path(project_file).unlink()


def test_release_workspace_with_workflow_filter(tmp_path: Path) -> None:
    """Test releasing workspace with workflow filter."""
    project_file = create_project_file_with_running(
        tmp_path,
        running_claims=[
            WorkspaceClaim(1, "crs", "feature1", pid=11111),
            WorkspaceClaim(1, "run", "feature2", pid=22222),
        ],
    )
    try:
        # Should only release the "crs" claim
        result = release_workspace(project_file, 1, workflow="crs")
        assert result.success is True

        claims = get_claimed_workspaces(project_file)
        assert len(claims) == 1
        assert claims[0].workflow == "run"
    finally:
        Path(project_file).unlink()

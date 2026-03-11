"""Tests for RUNNING field and workspace management operations."""

import tempfile
from pathlib import Path
from unittest.mock import patch

from sase.running_field import (
    WorkspaceClaim,
    claim_workspace,
    get_claimed_workspaces,
    get_first_available_workspace,
    get_workspace_directory_for_num,
    release_workspace,
)
from sase.running_field import (
    get_workspace_directory as get_workspace_dir,
)


def _create_project_file_with_running(
    running_claims: list[WorkspaceClaim] | None = None,
) -> str:
    """Create a temporary project file with optional RUNNING field."""
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".gp") as f:
        f.write("# Test Project\n\n")
        if running_claims:
            f.write("RUNNING:\n")
            for claim in running_claims:
                f.write(claim.to_line() + "\n")
        f.write("NAME: Test Feature\n")
        f.write("DESCRIPTION:\n")
        f.write("  Test description\n")
        f.write("PARENT: None\n")
        f.write("CL: None\n")
        f.write("STATUS: Ready\n")
        return f.name


def test_workspace_claim_from_line_legacy_format_no_pid_no_cl_returns_none() -> None:
    """Test parsing legacy format without PID or cl_name returns None."""
    claim = WorkspaceClaim.from_line("  #1 | run | ")
    # Legacy format without PID is now invalid
    assert claim is None


def test_claim_workspace_new_running_field() -> None:
    """Test claiming a workspace when RUNNING field doesn't exist (PID required)."""
    project_file = _create_project_file_with_running()
    try:
        # PID is required - pass it as 4th positional arg
        success = claim_workspace(project_file, 1, "crs", 12345, "my_feature")
        assert success is True

        with open(project_file) as f:
            content = f.read()

        assert "RUNNING:" in content
        # Format: #N | PID | WORKFLOW | CL_NAME
        assert "#1 | 12345 | crs | my_feature" in content

        # Verify PID is parsed correctly
        claims = get_claimed_workspaces(project_file)
        assert len(claims) == 1
        assert claims[0].pid == 12345
    finally:
        Path(project_file).unlink()


def test_claim_workspace_existing_running_field() -> None:
    """Test claiming a workspace when RUNNING field already exists."""
    project_file = _create_project_file_with_running(
        running_claims=[WorkspaceClaim(1, "crs", "existing", pid=11111)]
    )
    try:
        success = claim_workspace(project_file, 2, "run", 22222, "new_feature")
        assert success is True

        claims = get_claimed_workspaces(project_file)
        assert len(claims) == 2
        workspace_nums = {c.workspace_num for c in claims}
        assert workspace_nums == {1, 2}
    finally:
        Path(project_file).unlink()


def test_release_workspace_single() -> None:
    """Test releasing the only workspace claim."""
    project_file = _create_project_file_with_running(
        running_claims=[WorkspaceClaim(1, "crs", "feature", pid=12345)]
    )
    try:
        success = release_workspace(project_file, 1)
        assert success is True

        with open(project_file) as f:
            content = f.read()

        # RUNNING field should be removed entirely
        assert "RUNNING:" not in content
    finally:
        Path(project_file).unlink()


def test_release_workspace_with_workflow_filter() -> None:
    """Test releasing workspace with workflow filter."""
    project_file = _create_project_file_with_running(
        running_claims=[
            WorkspaceClaim(1, "crs", "feature1", pid=11111),
            WorkspaceClaim(1, "run", "feature2", pid=22222),
        ]
    )
    try:
        # Should only release the "crs" claim
        success = release_workspace(project_file, 1, workflow="crs")
        assert success is True

        claims = get_claimed_workspaces(project_file)
        assert len(claims) == 1
        assert claims[0].workflow == "run"
    finally:
        Path(project_file).unlink()


def test_get_first_available_workspace_main_claimed() -> None:
    """Test that next workspace share is returned when main is claimed."""
    project_file = _create_project_file_with_running(
        running_claims=[WorkspaceClaim(1, "crs", "feature", pid=12345)]
    )
    try:
        workspace_num = get_first_available_workspace(project_file)
        assert workspace_num == 2
    finally:
        Path(project_file).unlink()


def test_running_field_get_workspace_directory_plugin_failure() -> None:
    """Test get_workspace_directory raises on plugin failure."""
    import pytest

    with patch(
        "sase.workspace_provider._registry.detect_workflow_type",
        side_effect=ValueError("No workspace plugin detected"),
    ):
        with pytest.raises(RuntimeError, match="No workspace plugin detected"):
            get_workspace_dir("myproject")


def test_get_workspace_directory_for_num_main() -> None:
    """Test getting main workspace directory."""
    with patch(
        "sase.running_field.get_workspace_directory",
        return_value="/cloud/myproject/google3",
    ) as mock_get_ws:
        workspace_dir, suffix = get_workspace_directory_for_num(1, "myproject")
        assert workspace_dir == "/cloud/myproject/google3"
        assert suffix is None
        mock_get_ws.assert_called_once_with("myproject", 1)


def test_get_workspace_directory_for_num_share() -> None:
    """Test getting workspace share directory."""
    with patch(
        "sase.running_field.get_workspace_directory",
        return_value="/cloud/myproject_3/google3",
    ) as mock_get_ws:
        workspace_dir, suffix = get_workspace_directory_for_num(3, "myproject")
        assert workspace_dir == "/cloud/myproject_3/google3"
        assert suffix == "myproject_3"
        mock_get_ws.assert_called_once_with("myproject", 3)

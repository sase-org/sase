"""Tests for RUNNING field claim, hold, release, and transfer operations."""

from pathlib import Path
from unittest.mock import patch

from sase.ace.patch import write_patch_atomic
from sase.running_field import (
    WorkspaceClaim,
    claim_workspace,
    get_claimed_workspaces,
    hold_workspace_claim,
    release_workspace,
    transfer_workspace_claim,
)
from tests._running_field_helpers import create_project_file_with_running


def test_workspace_claim_from_line_legacy_format_no_pid_no_cl_returns_none() -> None:
    """Test parsing legacy format without PID or cl_name returns None."""
    claim = WorkspaceClaim.from_line("  #1 | run | ")
    # Legacy format without PID is now invalid
    assert claim is None


def test_claim_workspace_new_running_field(tmp_path: Path) -> None:
    """Test claiming a workspace when RUNNING field doesn't exist (PID required)."""
    project_file = create_project_file_with_running(
        tmp_path,
    )
    try:
        # PID is required - pass it as 4th positional arg
        result = claim_workspace(project_file, 1, "crs", 12345, "my_feature")
        assert result.success is True
        assert result.error is None

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


def test_claim_workspace_existing_running_field(tmp_path: Path) -> None:
    """Test claiming a workspace when RUNNING field already exists."""
    project_file = create_project_file_with_running(
        tmp_path, running_claims=[WorkspaceClaim(1, "crs", "existing", pid=11111)]
    )
    try:
        result = claim_workspace(project_file, 2, "run", 22222, "new_feature")
        assert result.success is True

        claims = get_claimed_workspaces(project_file)
        assert len(claims) == 2
        workspace_nums = {c.workspace_num for c in claims}
        assert workspace_nums == {1, 2}
    finally:
        Path(project_file).unlink()


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


def test_hold_workspace_claim_preserves_identity_and_pins_atomically(
    tmp_path: Path,
) -> None:
    project_file = create_project_file_with_running(
        tmp_path,
        running_claims=[
            WorkspaceClaim(
                17,
                "ace(run)-260712_120000",
                "feature",
                pid=12345,
                artifacts_timestamp="20260712120000",
            )
        ],
    )
    try:
        with patch(
            "sase.running_field._hold.write_patch_atomic",
            wraps=write_patch_atomic,
        ) as write_atomic:
            result = hold_workspace_claim(
                project_file,
                17,
                "ace(run)-260712_120000",
                "feature",
                "20260712120000",
            )

        assert result.success is True
        claims = get_claimed_workspaces(project_file)
        assert claims == [
            WorkspaceClaim(
                17,
                "ace(run)-260712_120000",
                "feature",
                pid=12345,
                artifacts_timestamp="20260712120000",
                pinned=True,
            )
        ]
        write_atomic.assert_called_once()
    finally:
        Path(project_file).unlink()


def test_claim_workspace_rejects_duplicate_workspace_num(tmp_path: Path) -> None:
    """Test that claim_workspace refuses to double-claim a workspace number."""
    project_file = create_project_file_with_running(
        tmp_path, running_claims=[WorkspaceClaim(100, "spy-foo", "foo", pid=11111)]
    )
    try:
        # Second claim for workspace #100 should be rejected
        result = claim_workspace(project_file, 100, "spy-foo", 22222, "foo")
        assert result.success is False
        assert result.error is not None
        assert "100" in result.error

        # Only the original claim should remain
        claims = get_claimed_workspaces(project_file)
        assert len(claims) == 1
        assert claims[0].pid == 11111
    finally:
        Path(project_file).unlink()


def test_claim_workspace_allows_workspace_zero_duplicates(tmp_path: Path) -> None:
    """Test that workspace #0 (deferred placeholder) allows duplicates."""
    project_file = create_project_file_with_running(
        tmp_path, running_claims=[WorkspaceClaim(0, "ace(run)-1", "foo", pid=11111)]
    )
    try:
        result = claim_workspace(project_file, 0, "ace(run)-2", 22222, "bar")
        assert result.success is True

        claims = get_claimed_workspaces(project_file)
        assert len(claims) == 2
    finally:
        Path(project_file).unlink()


def test_claim_workspace_rejects_disabled_project_before_running_write(
    tmp_path: Path,
) -> None:
    """Disabled projects cannot receive even deferred workspace claims."""
    project_file = tmp_path / "foo.sase"
    project_file.write_text(
        "PROJECT_STATE: disabled\nNAME: Test Feature\nSTATUS: Ready\n",
        encoding="utf-8",
    )

    result = claim_workspace(str(project_file), 0, "ace(run)-1", 22222, "foo")

    assert result.success is False
    assert result.error is not None
    assert result.error == (
        "project 'foo' is disabled; run 'sase project enable foo' before launching work"
    )
    assert "RUNNING:" not in project_file.read_text(encoding="utf-8")


def test_transfer_workspace_claim_by_pid(tmp_path: Path) -> None:
    """Test transferring a claim to a retry child by matching workspace and PID."""
    project_file = create_project_file_with_running(
        tmp_path,
        running_claims=[
            WorkspaceClaim(
                100,
                "ace(run)-old",
                "feature",
                pid=11111,
                artifacts_timestamp="20260501115959",
            )
        ],
    )
    try:
        result = transfer_workspace_claim(
            project_file,
            100,
            from_pid=11111,
            to_pid=22222,
            new_workflow="ace(run)-new",
            new_artifacts_timestamp="20260501120000",
            cl_name="feature",
        )
        assert result.success is True

        claims = get_claimed_workspaces(project_file)
        assert len(claims) == 1
        assert claims[0].pid == 22222
        assert claims[0].workflow == "ace(run)-new"
        assert claims[0].artifacts_timestamp == "20260501120000"
    finally:
        Path(project_file).unlink()

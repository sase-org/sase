"""Tests for RUNNING field claim holds."""

from pathlib import Path
from unittest.mock import patch

from sase.ace.patch import write_patch_atomic
from sase.running_field import (
    WorkspaceClaim,
    get_claimed_workspaces,
    hold_workspace_claim,
)
from tests._running_field_helpers import create_project_file_with_running


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


def test_hold_workspace_claim_expected_pid_mismatch_is_noop(tmp_path: Path) -> None:
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

    result = hold_workspace_claim(
        project_file,
        17,
        "ace(run)-260712_120000",
        "feature",
        "20260712120000",
        expected_pid=999,
    )

    assert result.success is False
    assert result.error is not None
    assert "ownership_moved" in result.error
    claims = get_claimed_workspaces(project_file)
    assert claims == [
        WorkspaceClaim(
            17,
            "ace(run)-260712_120000",
            "feature",
            pid=12345,
            artifacts_timestamp="20260712120000",
            pinned=False,
        )
    ]


def test_hold_workspace_claim_expected_pid_match_pins(tmp_path: Path) -> None:
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

    result = hold_workspace_claim(
        project_file,
        17,
        "ace(run)-260712_120000",
        "feature",
        "20260712120000",
        expected_pid=12345,
    )

    assert result.success is True
    claims = get_claimed_workspaces(project_file)
    assert claims[0].pinned is True
    assert claims[0].pid == 12345

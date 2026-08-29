"""Tests for RUNNING field claim release."""

from pathlib import Path
from unittest.mock import patch

from sase.logs.workspace_claim_ledger import read_ledger_records
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


def test_release_workspace_refuses_foreign_expected_pid(tmp_path: Path) -> None:
    project_file = create_project_file_with_running(
        tmp_path, running_claims=[WorkspaceClaim(23, "gh-acme/widget", None, pid=111)]
    )
    ledger_file = str(tmp_path / "workspace_claims.jsonl")
    with patch("sase.logs.workspace_claim_ledger.LEDGER_FILE", ledger_file):
        result = release_workspace(
            project_file,
            23,
            "gh-acme/widget",
            caller_tag="gh-release",
            expected_pid=222,
        )
        records = read_ledger_records(ledger_file=ledger_file)

    assert result.success is False
    assert result.error is not None
    assert "pid mismatch" in result.error
    claims = get_claimed_workspaces(project_file)
    assert len(claims) == 1
    assert claims[0].pid == 111
    assert records
    assert records[-1]["success"] is False
    assert records[-1]["caller_tag"] == "gh-release"
    assert "pid mismatch" in (records[-1]["error"] or "")


def test_release_workspace_expected_pid_match_releases(tmp_path: Path) -> None:
    project_file = create_project_file_with_running(
        tmp_path, running_claims=[WorkspaceClaim(23, "gh-acme/widget", None, pid=222)]
    )
    result = release_workspace(
        project_file,
        23,
        "gh-acme/widget",
        expected_pid=222,
    )
    assert result.success is True
    assert get_claimed_workspaces(project_file) == []


def test_release_without_expected_pid_still_drops_foreign_row(tmp_path: Path) -> None:
    project_file = create_project_file_with_running(
        tmp_path, running_claims=[WorkspaceClaim(23, "gh-acme/widget", None, pid=111)]
    )
    result = release_workspace(project_file, 23, "gh-acme/widget")
    assert result.success is True
    assert get_claimed_workspaces(project_file) == []

"""Tests for RUNNING field claim transfer."""

from pathlib import Path

from sase.running_field import (
    WorkspaceClaim,
    get_claimed_workspaces,
    transfer_workspace_claim,
)
from tests._running_field_helpers import create_project_file_with_running


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


def test_transfer_workspace_claim_preserves_unknown_suffix_fields(
    tmp_path: Path,
) -> None:
    """Retry handoff must retain suffix fields it does not understand."""
    project_file = tmp_path / "project.sase"
    project_file.write_text(
        "RUNNING:\n"
        "  #100 | 11111 | ace(run)-old | feature | 20260820_121314 | legacy=bad | PINNED\n"
        "\n\n"
        "NAME: Test Feature\n"
        "STATUS: Ready\n",
        encoding="utf-8",
    )
    try:
        result = transfer_workspace_claim(
            str(project_file),
            100,
            from_pid=11111,
            to_pid=22222,
            new_workflow="ace(run)-new",
            new_artifacts_timestamp="20260820121516",
            cl_name="feature",
        )
        assert result.success is True

        content = project_file.read_text(encoding="utf-8")
        assert (
            "#100 | 22222 | ace(run)-new | feature | 20260820121516 | "
            "legacy=bad | PINNED"
        ) in content
    finally:
        project_file.unlink()

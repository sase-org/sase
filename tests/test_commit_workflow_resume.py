"""Tests for CommitWorkflow.resume() — replaying tracking after conflict resolution."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sase.workflows.commit import checkpoint
from sase.workflows.commit.workflow import CommitWorkflow, RunResult

_PROVIDER_TARGET = "sase.workflows.commit.workflow.get_vcs_provider"


@pytest.fixture
def artifacts_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Direct checkpoint persistence to a hermetic artifacts directory."""
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(tmp_path))
    return tmp_path


def _make_provider(
    *,
    head_subject: str = "fix: bug",
    is_conflict: bool = False,
    finalize_result: tuple[bool, str | None] = (True, None),
    finalize_raises: bool = False,
) -> MagicMock:
    provider = MagicMock()
    provider._provider_name = "git"
    provider.is_sync_in_progress.return_value = is_conflict
    provider.get_conflicted_files.return_value = ["a.py"] if is_conflict else []
    provider.get_description.return_value = (True, head_subject)
    if finalize_raises:
        provider.finalize_commit.side_effect = NotImplementedError
    else:
        provider.finalize_commit.return_value = finalize_result
    return provider


def _save_checkpoint(
    *,
    cwd: str,
    method: str = "create_commit",
    payload: dict | None = None,
    completed_steps: list[str] | None = None,
    cs_name: str | None = None,
    entry_id: str | None = None,
    dispatch_result: str | None = None,
) -> checkpoint.CommitCheckpoint:
    cp = checkpoint.CommitCheckpoint(
        method=method,
        payload=payload if payload is not None else {"message": "fix: bug"},
        cwd=cwd,
        completed_steps=list(completed_steps) if completed_steps else [],
        cs_name=cs_name,
        entry_id=entry_id,
        dispatch_result=dispatch_result,
    )
    checkpoint.checkpoint_save(cp)
    return cp


def test_resume_returns_failed_when_no_checkpoint(artifacts_dir: Path) -> None:
    assert CommitWorkflow.resume() == RunResult.FAILED
    assert not (artifacts_dir / "commit_state.json").exists()


@patch(_PROVIDER_TARGET)
def test_resume_returns_conflict_when_sync_still_in_progress(
    mock_get: MagicMock, artifacts_dir: Path, tmp_path: Path
) -> None:
    provider = _make_provider(is_conflict=True)
    mock_get.return_value = provider

    _save_checkpoint(cwd=str(tmp_path))

    assert CommitWorkflow.resume() == RunResult.CONFLICT
    # Checkpoint must survive so the user can retry.
    assert (artifacts_dir / "commit_state.json").exists()
    provider.finalize_commit.assert_not_called()


@patch(_PROVIDER_TARGET)
def test_resume_returns_failed_on_subject_mismatch(
    mock_get: MagicMock, artifacts_dir: Path, tmp_path: Path
) -> None:
    provider = _make_provider(head_subject="feat: something else")
    mock_get.return_value = provider

    _save_checkpoint(cwd=str(tmp_path), payload={"message": "feat: original\n\nbody"})

    assert CommitWorkflow.resume() == RunResult.FAILED
    # Checkpoint preserved so the user can inspect / clean up manually.
    assert (artifacts_dir / "commit_state.json").exists()
    provider.finalize_commit.assert_not_called()


@patch(_PROVIDER_TARGET)
def test_resume_replays_tracking_after_conflict_resolution(
    mock_get: MagicMock, artifacts_dir: Path, tmp_path: Path
) -> None:
    provider = _make_provider(head_subject="fix: bug")
    mock_get.return_value = provider

    _save_checkpoint(cwd=str(tmp_path), payload={"message": "fix: bug"})

    with (
        patch(
            "sase.workflows.commit.workflow.append_commits_entry",
            return_value="42",
        ) as mock_append,
        patch("sase.workflows.commit.workflow.write_result_marker") as mock_marker,
    ):
        assert CommitWorkflow.resume() == RunResult.OK

    provider.finalize_commit.assert_called_once()
    mock_append.assert_called_once()
    assert mock_marker.call_count == 2  # initial + final-with-entry_id
    assert not (artifacts_dir / "commit_state.json").exists()


@patch(_PROVIDER_TARGET)
def test_resume_skips_already_completed_tracking_steps(
    mock_get: MagicMock, artifacts_dir: Path, tmp_path: Path
) -> None:
    provider = _make_provider(head_subject="fix: bug")
    mock_get.return_value = provider

    _save_checkpoint(
        cwd=str(tmp_path),
        payload={"message": "fix: bug"},
        completed_steps=["dispatch", "write_result_marker"],
        entry_id=None,
    )

    with (
        patch(
            "sase.workflows.commit.workflow.append_commits_entry",
            return_value="7",
        ) as mock_append,
        patch("sase.workflows.commit.workflow.write_result_marker") as mock_marker,
    ):
        assert CommitWorkflow.resume() == RunResult.OK

    # write_result_marker already done → only the final entry-id marker runs.
    assert mock_marker.call_count == 1
    mock_append.assert_called_once()


@patch("sase.workflows.utils.get_project_from_workspace", return_value=None)
@patch(_PROVIDER_TARGET)
def test_resume_handles_pull_request_path(
    mock_get: MagicMock,
    _mock_proj: MagicMock,
    artifacts_dir: Path,
    tmp_path: Path,
) -> None:
    provider = _make_provider(head_subject="feat: x")
    mock_get.return_value = provider

    _save_checkpoint(
        cwd=str(tmp_path),
        method="create_pull_request",
        payload={"name": "feat", "message": "feat: x"},
    )

    with (
        patch(
            "sase.workflows.commit.workflow.create_changespec",
            return_value="proj_feat_1",
        ) as mock_cs,
        patch("sase.workflows.commit.workflow.append_commits_entry") as mock_append,
        patch("sase.workflows.commit.workflow.write_result_marker") as mock_marker,
    ):
        assert CommitWorkflow.resume() == RunResult.OK

    mock_cs.assert_called_once()
    mock_append.assert_not_called()
    assert mock_marker.call_count == 1


@patch(_PROVIDER_TARGET)
def test_resume_is_idempotent_across_repeated_invocations(
    mock_get: MagicMock, artifacts_dir: Path, tmp_path: Path
) -> None:
    provider = _make_provider(head_subject="fix: bug")
    mock_get.return_value = provider

    _save_checkpoint(cwd=str(tmp_path), payload={"message": "fix: bug"})

    with (
        patch(
            "sase.workflows.commit.workflow.append_commits_entry",
            return_value="1",
        ),
        patch("sase.workflows.commit.workflow.write_result_marker"),
    ):
        assert CommitWorkflow.resume() == RunResult.OK

    # Second call has no checkpoint left — nothing to resume.
    assert CommitWorkflow.resume() == RunResult.FAILED


@patch(_PROVIDER_TARGET)
def test_resume_tolerates_hg_missing_finalize_commit(
    mock_get: MagicMock, artifacts_dir: Path, tmp_path: Path
) -> None:
    provider = _make_provider(head_subject="fix: bug", finalize_raises=True)
    mock_get.return_value = provider

    _save_checkpoint(cwd=str(tmp_path), payload={"message": "fix: bug"})

    with (
        patch(
            "sase.workflows.commit.workflow.append_commits_entry",
            return_value="1",
        ),
        patch("sase.workflows.commit.workflow.write_result_marker"),
    ):
        assert CommitWorkflow.resume() == RunResult.OK

    assert not (artifacts_dir / "commit_state.json").exists()


@patch(_PROVIDER_TARGET)
def test_resume_failed_finalize_returns_failed(
    mock_get: MagicMock, artifacts_dir: Path, tmp_path: Path
) -> None:
    provider = _make_provider(
        head_subject="fix: bug", finalize_result=(False, "push rejected")
    )
    mock_get.return_value = provider

    _save_checkpoint(cwd=str(tmp_path), payload={"message": "fix: bug"})

    assert CommitWorkflow.resume() == RunResult.FAILED
    # Tracking should NOT run when finalize fails.
    assert (artifacts_dir / "commit_state.json").exists()


def test_append_commits_entry_idempotent_on_resume(
    tmp_path: Path, artifacts_dir: Path
) -> None:
    """When the COMMITS drawer already has the expected entry, resume is a no-op."""
    from sase.workflows.commit.commit_tracking import append_commits_entry

    project_file = tmp_path / "proj.gp"
    initial = (
        "NAME: test-cl\n"
        "DESCRIPTION:\n  desc\n"
        "COMMITS:\n"
        "  (99) existing note\n"
        "STATUS: Pending\n"
    )
    project_file.write_text(initial)

    result = append_commits_entry(
        str(project_file),
        "test-cl",
        {"message": "fix: bug"},
        "create_commit",
        None,
        expected_entry_id="99",
    )
    assert result == "99"
    assert project_file.read_text() == initial


@patch(_PROVIDER_TARGET)
def test_resume_detects_existing_changespec_in_project_file(
    mock_get: MagicMock, artifacts_dir: Path, tmp_path: Path
) -> None:
    """Observation-level idempotency: skip create_changespec if the name exists."""
    provider = _make_provider(head_subject="feat: x")
    mock_get.return_value = provider

    project_file = tmp_path / "proj.gp"
    project_file.write_text("NAME: proj_feat_1\nDESCRIPTION:\n  desc\nSTATUS: Draft\n")

    cp = checkpoint.CommitCheckpoint(
        method="create_pull_request",
        payload={"name": "feat", "message": "feat: x"},
        cwd=str(tmp_path),
        project_file=str(project_file),
        reserved_name="proj_feat_1",
    )
    checkpoint.checkpoint_save(cp)

    with (
        patch("sase.workflows.commit.workflow.create_changespec") as mock_cs,
        patch("sase.workflows.commit.workflow.write_result_marker"),
    ):
        assert CommitWorkflow.resume() == RunResult.OK

    mock_cs.assert_not_called()

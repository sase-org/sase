"""Tests for CommitWorkflow.resume() recovery and idempotency paths."""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sase.workflows.commit import checkpoint
from sase.workflows.commit.workflow import CommitWorkflow, RunResult
from tests._commit_workflow_fixtures import (
    commit_artifacts_dir,  # noqa: F401 (imported for fixture discovery)
    no_commit_hooks,  # noqa: F401 (imported for fixture discovery)
)
from tests._commit_workflow_resume_helpers import (
    PROVIDER_TARGET,
    make_resume_provider,
    save_resume_checkpoint,
)


@pytest.fixture(autouse=True)
def _no_commit_hooks(no_commit_hooks):  # type: ignore[no-untyped-def]  # noqa: F811
    """Keep resume tracking independent of project hooks and shell PATH."""
    yield


@patch("sase.workflows.utils.get_project_from_workspace", return_value=None)
@patch(PROVIDER_TARGET)
def test_resume_handles_pull_request_path(
    mock_get: MagicMock,
    _mock_proj: MagicMock,
    artifacts_dir: Path,
    tmp_path: Path,
) -> None:
    provider = make_resume_provider(head_subject="feat: x")
    mock_get.return_value = provider

    save_resume_checkpoint(
        cwd=str(tmp_path),
        method="create_pull_request",
        payload={"name": "feat", "message": "feat: x"},
    )

    with (
        patch(
            "sase.workflows.commit.workflow.create_patch",
            return_value="proj_feat_1",
        ) as mock_cs,
        patch("sase.workflows.commit.workflow.append_commits_entry") as mock_append,
        patch("sase.workflows.commit.workflow.write_result_marker") as mock_marker,
    ):
        assert CommitWorkflow.resume() == RunResult.OK

    mock_cs.assert_called_once()
    mock_append.assert_not_called()
    assert mock_marker.call_count == 1


@patch(PROVIDER_TARGET)
def test_resume_is_idempotent_across_repeated_invocations(
    mock_get: MagicMock,
    artifacts_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The shared fixture must prevent an ambient after-commit hook from trying
    # to resolve an installed ``sase`` command during resume.
    monkeypatch.setenv("PATH", str(tmp_path / "empty-bin"))
    provider = make_resume_provider(head_subject="fix: bug")
    mock_get.return_value = provider

    save_resume_checkpoint(cwd=str(tmp_path), payload={"message": "fix: bug"})

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


@patch(PROVIDER_TARGET)
def test_resume_tolerates_hg_missing_finalize_commit(
    mock_get: MagicMock, artifacts_dir: Path, tmp_path: Path
) -> None:
    provider = make_resume_provider(head_subject="fix: bug", finalize_raises=True)
    mock_get.return_value = provider

    save_resume_checkpoint(cwd=str(tmp_path), payload={"message": "fix: bug"})

    with (
        patch(
            "sase.workflows.commit.workflow.append_commits_entry",
            return_value="1",
        ),
        patch("sase.workflows.commit.workflow.write_result_marker"),
    ):
        assert CommitWorkflow.resume() == RunResult.OK

    assert not (artifacts_dir / "commit_state.json").exists()


@patch(PROVIDER_TARGET)
def test_resume_failed_finalize_returns_failed(
    mock_get: MagicMock, artifacts_dir: Path, tmp_path: Path
) -> None:
    provider = make_resume_provider(
        head_subject="fix: bug", finalize_result=(False, "push rejected")
    )
    mock_get.return_value = provider

    save_resume_checkpoint(cwd=str(tmp_path), payload={"message": "fix: bug"})

    assert CommitWorkflow.resume() == RunResult.FAILED
    # Tracking should NOT run when finalize fails.
    assert (artifacts_dir / "commit_state.json").exists()


def test_append_commits_entry_idempotent_on_resume(
    tmp_path: Path, artifacts_dir: Path
) -> None:
    """When the COMMITS drawer already has the expected entry, resume is a no-op."""
    from sase.workflows.commit.commit_tracking import append_commits_entry

    project_file = tmp_path / "proj.sase"
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


@patch(PROVIDER_TARGET)
def test_resume_detects_existing_patch_in_project_file(
    mock_get: MagicMock, artifacts_dir: Path, tmp_path: Path
) -> None:
    """Observation-level idempotency: skip create_patch if the name exists."""
    provider = make_resume_provider(head_subject="feat: x")
    mock_get.return_value = provider

    project_file = tmp_path / "proj.sase"
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
        patch("sase.workflows.commit.workflow.create_patch") as mock_cs,
        patch("sase.workflows.commit.workflow.write_result_marker"),
    ):
        assert CommitWorkflow.resume() == RunResult.OK

    mock_cs.assert_not_called()


@patch(PROVIDER_TARGET)
def test_resume_attributes_markers_to_checkpointed_repo_not_process_cwd(
    mock_get: MagicMock,
    artifacts_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A resume launched outside the checkpointed repo still records that repo."""
    provider = make_resume_provider(head_subject="fix: bug")
    provider.revision_id.return_value = "c" * 40
    mock_get.return_value = provider

    checkpoint_cwd = tmp_path / "plans"
    launch_dir = tmp_path / "workspace"
    checkpoint_cwd.mkdir()
    launch_dir.mkdir()
    monkeypatch.chdir(launch_dir)
    assert os.getcwd() != str(checkpoint_cwd)

    save_resume_checkpoint(cwd=str(checkpoint_cwd), payload={"message": "fix: bug"})

    with patch(
        "sase.workflows.commit.workflow.append_commits_entry",
        return_value="42",
    ):
        assert CommitWorkflow.resume() == RunResult.OK

    latest = json.loads((artifacts_dir / "commit_result.json").read_text())
    assert latest["cwd"] == str(checkpoint_cwd)
    assert latest["commit_sha"] == "c" * 40
    assert latest["commit_tree"] == "c" * 40
    assert latest["entry_id"] == "42"

    results = json.loads((artifacts_dir / "commit_results.json").read_text())
    assert len(results) == 1
    assert results[0]["cwd"] == str(checkpoint_cwd)
    assert results[0]["commit_sha"] == "c" * 40
    assert results[0]["commit_tree"] == "c" * 40
    assert results[0]["entry_id"] == "42"

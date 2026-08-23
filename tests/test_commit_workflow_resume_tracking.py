"""Tests for replaying CommitWorkflow.resume() tracking steps."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

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


@patch(PROVIDER_TARGET)
def test_resume_reaches_close_bead_step(
    mock_get: MagicMock, artifacts_dir: Path, tmp_path: Path
) -> None:
    provider = make_resume_provider(head_subject="fix: bug")
    mock_get.return_value = provider

    save_resume_checkpoint(
        cwd=str(tmp_path),
        payload={"message": "fix: bug", "bead_id": "B-123"},
    )

    snapshots: list[list[str]] = []
    with (
        patch(
            "sase.workflows.commit.workflow.append_commits_entry",
            return_value="42",
        ),
        patch("sase.workflows.commit.workflow.write_result_marker"),
        patch(
            "sase.workflows.commit.workflow.close_assigned_bead_after_commit",
            return_value=True,
        ) as close_bead,
        patch(
            "sase.workflows.commit.workflow.checkpoint_save",
            side_effect=lambda cp: snapshots.append(list(cp.completed_steps)) or None,
        ),
    ):
        assert CommitWorkflow.resume() == RunResult.OK

    close_bead.assert_called_once()
    assert close_bead.call_args.kwargs == {"method": "create_commit"}
    assert "close_bead" in snapshots[-1]
    assert not (artifacts_dir / "commit_state.json").exists()


@patch(PROVIDER_TARGET)
def test_resume_skips_completed_close_bead_step(
    mock_get: MagicMock, artifacts_dir: Path, tmp_path: Path
) -> None:
    provider = make_resume_provider(head_subject="fix: bug")
    mock_get.return_value = provider

    save_resume_checkpoint(
        cwd=str(tmp_path),
        payload={"message": "fix: bug", "bead_id": "B-123"},
        completed_steps=[
            "dispatch",
            "after_hook",
            "write_result_marker",
            "append_commits_entry",
            "final_result_marker",
            "close_bead",
        ],
        entry_id="42",
    )

    with (
        patch("sase.workflows.commit.workflow.write_result_marker"),
        patch(
            "sase.workflows.commit.workflow.close_assigned_bead_after_commit"
        ) as close_bead,
    ):
        assert CommitWorkflow.resume() == RunResult.OK

    close_bead.assert_not_called()
    assert not (artifacts_dir / "commit_state.json").exists()


@patch(PROVIDER_TARGET)
def test_resume_after_hook_failure_does_not_finalize_or_duplicate_dispatch(
    mock_get: MagicMock, artifacts_dir: Path, tmp_path: Path
) -> None:
    provider = make_resume_provider(head_subject="fix: bug")
    mock_get.return_value = provider
    save_resume_checkpoint(
        cwd=str(tmp_path),
        completed_steps=["dispatch"],
        dispatch_result="abc123",
    )

    with (
        patch(
            "sase.workflows.commit.workflow.run_after_commit_hook",
            return_value=True,
        ) as after_hook,
        patch(
            "sase.workflows.commit.workflow.append_commits_entry",
            return_value="42",
        ),
        patch("sase.workflows.commit.workflow.write_result_marker"),
    ):
        assert CommitWorkflow.resume() == RunResult.OK

    provider.finalize_commit.assert_not_called()
    after_hook.assert_called_once_with(str(tmp_path))
    assert not (artifacts_dir / "commit_state.json").exists()


@patch(PROVIDER_TARGET)
def test_resume_publishes_agent_hood_without_redispatching_primary_commit(
    mock_get: MagicMock,
    artifacts_dir: Path,
    tmp_path: Path,
) -> None:
    from sase.agents_sync.commit_publication import _CommitPublicationOutcome

    provider = make_resume_provider(head_subject="fix: bug")
    provider.revision_id.return_value = "a" * 40
    mock_get.return_value = provider
    save_resume_checkpoint(
        cwd=str(tmp_path),
        completed_steps=["dispatch", "after_hook", "write_result_marker"],
        dispatch_result="not-a-sha",
        publication_agent="foo--code",
    )

    with (
        patch(
            "sase.agents_sync.commit_publication.publish_committed_agent_hood",
            return_value=_CommitPublicationOutcome(published=True),
        ) as publish,
        patch(
            "sase.workflows.commit.workflow.append_commits_entry",
            return_value=None,
        ),
    ):
        assert CommitWorkflow.resume() == RunResult.OK

    provider.finalize_commit.assert_not_called()
    provider.revision_id.assert_called_once_with("HEAD", str(tmp_path))
    publish.assert_called_once_with(
        "foo--code",
        "a" * 40,
        commit_cwd=str(tmp_path),
    )
    assert not (artifacts_dir / "commit_state.json").exists()


@patch(PROVIDER_TARGET)
def test_resume_skips_completed_after_hook(
    mock_get: MagicMock, artifacts_dir: Path, tmp_path: Path
) -> None:
    provider = make_resume_provider(head_subject="fix: bug")
    mock_get.return_value = provider
    save_resume_checkpoint(
        cwd=str(tmp_path),
        completed_steps=["dispatch", "after_hook"],
        dispatch_result="abc123",
    )

    with (
        patch("sase.workflows.commit.workflow.run_after_commit_hook") as after_hook,
        patch(
            "sase.workflows.commit.workflow.append_commits_entry",
            return_value="42",
        ),
        patch("sase.workflows.commit.workflow.write_result_marker"),
    ):
        assert CommitWorkflow.resume() == RunResult.OK

    provider.finalize_commit.assert_not_called()
    after_hook.assert_not_called()


@patch(PROVIDER_TARGET)
def test_resume_skips_already_completed_tracking_steps(
    mock_get: MagicMock, artifacts_dir: Path, tmp_path: Path
) -> None:
    provider = make_resume_provider(head_subject="fix: bug")
    mock_get.return_value = provider

    save_resume_checkpoint(
        cwd=str(tmp_path),
        payload={"message": "fix: bug"},
        completed_steps=["dispatch", "write_result_marker"],
        cl_name="feature",
        project_file=str(tmp_path),
        entry_id=None,
    )

    with (
        patch(
            "sase.workflows.commit.workflow.append_commits_entry",
            return_value="7",
        ) as mock_append,
        patch(
            "sase.workflows.commit.workflow.refresh_deltas_after_commits_change",
            return_value=True,
        ) as mock_refresh,
        patch("sase.workflows.commit.workflow.write_result_marker") as mock_marker,
    ):
        assert CommitWorkflow.resume() == RunResult.OK

    # write_result_marker already done → only the final entry-id marker runs.
    assert mock_marker.call_count == 1
    assert mock_marker.call_args.kwargs["commit_cwd"] == str(tmp_path)
    mock_append.assert_called_once()
    mock_refresh.assert_called_once_with(str(tmp_path), "feature", str(tmp_path))

"""Tests for CommitWorkflow.resume() — replaying tracking after conflict resolution."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sase.workflows.commit.workflow import CommitWorkflow, RunResult
from tests._commit_workflow_fixtures import (
    commit_artifacts_dir,  # noqa: F401 (imported for fixture discovery)
    no_commit_hooks,  # noqa: F401 (imported for fixture discovery, re-used as fixture arg)
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


def test_resume_returns_failed_when_no_checkpoint(artifacts_dir: Path) -> None:
    assert CommitWorkflow.resume() == RunResult.FAILED
    assert not (artifacts_dir / "commit_state.json").exists()


@patch(PROVIDER_TARGET)
def test_resume_returns_conflict_when_sync_still_in_progress(
    mock_get: MagicMock, artifacts_dir: Path, tmp_path: Path
) -> None:
    provider = make_resume_provider(is_conflict=True)
    mock_get.return_value = provider

    save_resume_checkpoint(cwd=str(tmp_path))

    assert CommitWorkflow.resume() == RunResult.CONFLICT
    # Checkpoint must survive so the user can retry.
    assert (artifacts_dir / "commit_state.json").exists()
    provider.finalize_commit.assert_not_called()


@patch(PROVIDER_TARGET)
def test_resume_returns_failed_on_subject_mismatch(
    mock_get: MagicMock, artifacts_dir: Path, tmp_path: Path
) -> None:
    provider = make_resume_provider(head_subject="feat: something else")
    mock_get.return_value = provider

    save_resume_checkpoint(
        cwd=str(tmp_path), payload={"message": "feat: original\n\nbody"}
    )

    with patch(
        "sase.workflows.commit.workflow_resume.git_changed_files",
        return_value=["src/app.py"],
    ):
        assert CommitWorkflow.resume() == RunResult.FAILED
    # Checkpoint preserved so the user can inspect / clean up manually.
    assert (artifacts_dir / "commit_state.json").exists()
    provider.finalize_commit.assert_not_called()


@patch(PROVIDER_TARGET)
def test_resume_no_commit_dispatched_clean_repo_finishes_without_tracking(
    mock_get: MagicMock, artifacts_dir: Path, tmp_path: Path
) -> None:
    provider = make_resume_provider(head_subject="feat: unrelated")
    mock_get.return_value = provider

    save_resume_checkpoint(
        cwd=str(tmp_path),
        payload={"message": "fix: original"},
        no_commit_dispatched=True,
    )

    with (
        patch(
            "sase.workflows.commit.workflow_resume.git_changed_files",
            return_value=[],
        ),
        patch("sase.workflows.commit.workflow.write_result_marker") as mock_marker,
        patch("sase.workflows.commit.workflow.append_commits_entry") as mock_append,
        patch("sase.workflows.commit.workflow.run_after_commit_hook") as mock_after,
    ):
        assert CommitWorkflow.resume() == RunResult.OK

    provider.finalize_commit.assert_not_called()
    mock_after.assert_not_called()
    mock_marker.assert_not_called()
    mock_append.assert_not_called()
    assert not (artifacts_dir / "commit_state.json").exists()


@patch(PROVIDER_TARGET)
def test_resume_legacy_subject_mismatch_clean_repo_finishes_without_tracking(
    mock_get: MagicMock, artifacts_dir: Path, tmp_path: Path
) -> None:
    provider = make_resume_provider(head_subject="feat: already upstream")
    mock_get.return_value = provider

    save_resume_checkpoint(
        cwd=str(tmp_path),
        payload={"message": "fix: original"},
    )

    with (
        patch(
            "sase.workflows.commit.workflow_resume.git_changed_files",
            return_value=[],
        ),
        patch("sase.workflows.commit.workflow.write_result_marker") as mock_marker,
    ):
        assert CommitWorkflow.resume() == RunResult.OK

    provider.finalize_commit.assert_not_called()
    mock_marker.assert_not_called()
    assert not (artifacts_dir / "commit_state.json").exists()


@patch(PROVIDER_TARGET)
def test_resume_no_commit_dispatched_dirty_repo_fails_and_deletes_checkpoint(
    mock_get: MagicMock,
    artifacts_dir: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    provider = make_resume_provider(head_subject="feat: unrelated")
    mock_get.return_value = provider

    save_resume_checkpoint(
        cwd=str(tmp_path),
        payload={"message": "fix: original"},
        no_commit_dispatched=True,
    )

    with patch(
        "sase.workflows.commit.workflow_resume.git_changed_files",
        return_value=["src/app.py"],
    ):
        assert CommitWorkflow.resume() == RunResult.FAILED

    provider.finalize_commit.assert_not_called()
    assert "Re-run `sase stitch create` from scratch" in capsys.readouterr().out
    assert not (artifacts_dir / "commit_state.json").exists()


@patch(PROVIDER_TARGET)
def test_resume_legacy_subject_mismatch_dirty_repo_still_fails_closed(
    mock_get: MagicMock, artifacts_dir: Path, tmp_path: Path
) -> None:
    provider = make_resume_provider(head_subject="feat: something else")
    mock_get.return_value = provider

    save_resume_checkpoint(
        cwd=str(tmp_path),
        payload={"message": "fix: original"},
    )

    with patch(
        "sase.workflows.commit.workflow_resume.git_changed_files",
        return_value=["src/app.py"],
    ):
        assert CommitWorkflow.resume() == RunResult.FAILED

    provider.finalize_commit.assert_not_called()
    assert (artifacts_dir / "commit_state.json").exists()


@patch(PROVIDER_TARGET)
def test_resume_replays_tracking_after_conflict_resolution(
    mock_get: MagicMock, artifacts_dir: Path, tmp_path: Path
) -> None:
    provider = make_resume_provider(head_subject="fix: bug")
    mock_get.return_value = provider

    save_resume_checkpoint(cwd=str(tmp_path), payload={"message": "fix: bug"})

    events: list[str] = []
    provider.finalize_commit.side_effect = lambda *_args: (
        events.append("finalize") or (True, None)
    )

    with (
        patch(
            "sase.workflows.commit.workflow.run_after_commit_hook",
            side_effect=lambda _cwd: events.append("after") or True,
        ),
        patch(
            "sase.workflows.commit.workflow.append_commits_entry",
            return_value="42",
        ) as mock_append,
        patch("sase.workflows.commit.workflow.write_result_marker") as mock_marker,
    ):
        assert CommitWorkflow.resume() == RunResult.OK

    provider.finalize_commit.assert_called_once()
    assert events == ["finalize", "after"]
    mock_append.assert_called_once()
    assert mock_marker.call_count == 2  # initial + final-with-entry_id
    for call in mock_marker.call_args_list:
        assert call.kwargs["commit_cwd"] == str(tmp_path)
    assert not (artifacts_dir / "commit_state.json").exists()


@patch(PROVIDER_TARGET)
def test_resume_records_finalized_commit_sha_for_conflict_originated_dispatch(
    mock_get: MagicMock, artifacts_dir: Path, tmp_path: Path
) -> None:
    """Resume must record a real SHA where cp.dispatch_result stayed null.

    A dispatch that ended in CONFLICT never set cp.dispatch_result, so before
    this fix the ledger recorded "result": null for the commit this run
    actually finalized. Resume has the repo and the finalized HEAD in hand
    and must resolve and record its SHA.
    """
    provider = make_resume_provider(head_subject="fix: bug")
    provider.revision_id.return_value = "c" * 40
    mock_get.return_value = provider

    save_resume_checkpoint(cwd=str(tmp_path), payload={"message": "fix: bug"})

    with (
        patch(
            "sase.workflows.commit.workflow.append_commits_entry",
            return_value="42",
        ),
        patch("sase.workflows.commit.workflow.write_result_marker") as mock_marker,
    ):
        assert CommitWorkflow.resume() == RunResult.OK

    assert mock_marker.call_count == 2  # initial + final-with-entry_id
    for call in mock_marker.call_args_list:
        assert call.kwargs["commit_sha"] == "c" * 40
        assert call.kwargs["commit_tree"] == "c" * 40
        assert call.kwargs["commit_cwd"] == str(tmp_path)


@patch(PROVIDER_TARGET)
def test_resume_resolves_commit_sha_after_finalize_commit(
    mock_get: MagicMock, artifacts_dir: Path, tmp_path: Path
) -> None:
    """The SHA must be resolved after finalize_commit's amend/push/rebase."""
    provider = make_resume_provider(head_subject="fix: bug")
    mock_get.return_value = provider

    events: list[str] = []
    provider.finalize_commit.side_effect = lambda *_a, **_k: (
        events.append("finalize") or (True, None)
    )
    provider.revision_id.side_effect = lambda *_a, **_k: (
        events.append("revision_id") or "c" * 40
    )

    save_resume_checkpoint(cwd=str(tmp_path), payload={"message": "fix: bug"})

    with (
        patch(
            "sase.workflows.commit.workflow.append_commits_entry",
            return_value="42",
        ),
        patch("sase.workflows.commit.workflow.write_result_marker"),
    ):
        assert CommitWorkflow.resume() == RunResult.OK

    assert events == ["finalize", "revision_id", "revision_id"]


@patch(PROVIDER_TARGET)
def test_resume_resolves_commit_sha_when_finalize_commit_unsupported(
    mock_get: MagicMock, artifacts_dir: Path, tmp_path: Path
) -> None:
    """Even without finalize_commit support, HEAD's SHA is still knowable."""
    provider = make_resume_provider(head_subject="fix: bug", finalize_raises=True)
    provider.revision_id.return_value = "d" * 40
    mock_get.return_value = provider

    save_resume_checkpoint(cwd=str(tmp_path), payload={"message": "fix: bug"})

    with (
        patch(
            "sase.workflows.commit.workflow.append_commits_entry",
            return_value="1",
        ),
        patch("sase.workflows.commit.workflow.write_result_marker") as mock_marker,
    ):
        assert CommitWorkflow.resume() == RunResult.OK

    assert mock_marker.call_args.kwargs["commit_sha"] == "d" * 40
    assert mock_marker.call_args.kwargs["commit_cwd"] == str(tmp_path)


@patch(PROVIDER_TARGET)
def test_resume_reuses_checkpointed_bead_tag_without_reapplying_it(
    mock_get: MagicMock,
    artifacts_dir: Path,
    tmp_path: Path,
) -> None:
    message = "fix: bug\n\nSASE_BEAD=sase-ai.2"
    provider = make_resume_provider(head_subject="fix: bug", head_message=message)
    provider.revision_id.return_value = "a" * 40
    mock_get.return_value = provider
    save_resume_checkpoint(
        cwd=str(tmp_path),
        payload={"message": message, "bead_id": "sase-ai.2"},
    )

    with (
        patch("sase.workflows.commit.workflow.apply_bead_commit_tag") as apply_tag,
        patch(
            "sase.workflows.commit.workflow.append_commits_entry",
            return_value=None,
        ),
        patch("sase.workflows.commit.workflow.write_result_marker"),
    ):
        assert CommitWorkflow.resume() == RunResult.OK

    apply_tag.assert_not_called()
    provider.amend.assert_not_called()
    provider.finalize_commit.assert_called_once()
    assert provider.finalize_commit.call_args.args[0]["message"] == message
    assert not (artifacts_dir / "commit_state.json").exists()


@patch(PROVIDER_TARGET)
def test_resume_restamps_footer_dropped_during_conflict_resolution(
    mock_get: MagicMock, artifacts_dir: Path, tmp_path: Path
) -> None:
    """A rewritten HEAD message that lost its SASE_* footer gets it back."""
    checkpoint_message = (
        "fix: bug\n\n"
        "SASE_BEAD=sase-ai.2\n"
        "SASE_TYPE=stitch\n"
        "SASE_AGENT=bbugyi200.athena.sase-ai.2"
    )
    # Conflict resolution re-authored the body to match reality and, along
    # with the stale paragraph, dropped the whole footer — but the subject
    # line survived unchanged, so the resume subject check still passes.
    head_message_after_conflict = "fix: bug\n\nUpdated to match upstream reality."
    provider = make_resume_provider(
        head_subject="fix: bug", head_message=head_message_after_conflict
    )
    mock_get.return_value = provider

    events: list[str] = []
    provider.amend.side_effect = lambda *_a, **_k: (
        events.append("amend") or (True, None)
    )
    provider.finalize_commit.side_effect = lambda *_a, **_k: (
        events.append("finalize") or (True, None)
    )

    save_resume_checkpoint(cwd=str(tmp_path), payload={"message": checkpoint_message})

    with (
        patch(
            "sase.workflows.commit.workflow.append_commits_entry",
            return_value=None,
        ),
        patch("sase.workflows.commit.workflow.write_result_marker"),
    ):
        assert CommitWorkflow.resume() == RunResult.OK

    # The amend must happen before finalize_commit pushes, not after.
    assert events == ["amend", "finalize"]
    amended_message = provider.amend.call_args.args[0]
    assert "SASE_BEAD=sase-ai.2" in amended_message
    assert "SASE_TYPE=stitch" in amended_message
    assert "SASE_AGENT=bbugyi200.athena.sase-ai.2" in amended_message
    assert "Updated to match upstream reality." in amended_message
    assert provider.amend.call_args.kwargs.get("no_upload") is True
    assert not (artifacts_dir / "commit_state.json").exists()


@patch(PROVIDER_TARGET)
def test_resume_fails_loudly_when_footer_restamp_amend_fails(
    mock_get: MagicMock, artifacts_dir: Path, tmp_path: Path
) -> None:
    """A failed re-stamp aborts resume instead of pushing an unattributed commit."""
    checkpoint_message = "fix: bug\n\nSASE_AGENT=bbugyi200.athena.sase-ai.2"
    provider = make_resume_provider(
        head_subject="fix: bug",
        head_message="fix: bug\n\nRewritten body, no footer.",
        amend_result=(False, "no changes to amend"),
    )
    mock_get.return_value = provider

    save_resume_checkpoint(cwd=str(tmp_path), payload={"message": checkpoint_message})

    assert CommitWorkflow.resume() == RunResult.FAILED
    provider.finalize_commit.assert_not_called()
    # Checkpoint preserved so the user can inspect / retry manually.
    assert (artifacts_dir / "commit_state.json").exists()

"""Tests for CommitWorkflow.resume() — replaying tracking after conflict resolution."""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sase.workflows.commit import checkpoint
from sase.workflows.commit.workflow import CommitWorkflow, RunResult
from tests._commit_workflow_fixtures import (
    no_commit_hooks,  # noqa: F401 (imported for fixture discovery, re-used as fixture arg)
)

_PROVIDER_TARGET = "sase.workflows.commit.workflow.get_vcs_provider"


@pytest.fixture(autouse=True)
def _no_commit_hooks(no_commit_hooks):  # type: ignore[no-untyped-def]  # noqa: F811
    """Keep resume tracking independent of project hooks and shell PATH."""
    yield


@pytest.fixture
def artifacts_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Direct checkpoint persistence to a hermetic artifacts directory."""
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(tmp_path))
    return tmp_path


def _make_provider(
    *,
    head_subject: str = "fix: bug",
    head_message: str | None = None,
    is_conflict: bool = False,
    finalize_result: tuple[bool, str | None] = (True, None),
    finalize_raises: bool = False,
    amend_result: tuple[bool, str | None] = (True, None),
) -> MagicMock:
    provider = MagicMock()
    provider._provider_name = "git"
    provider.is_sync_in_progress.return_value = is_conflict
    provider.get_conflicted_files.return_value = ["a.py"] if is_conflict else []
    full_message = head_subject if head_message is None else head_message

    def _get_description(
        _revision: str, _cwd: str, *, short: bool = False
    ) -> tuple[bool, str]:
        return (True, head_subject if short else full_message)

    provider.get_description.side_effect = _get_description
    provider.amend.return_value = amend_result
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
    cl_name: str | None = None,
    project_file: str | None = None,
    cs_name: str | None = None,
    entry_id: str | None = None,
    dispatch_result: str | None = None,
    publication_agent: str | None = None,
    primary_revision: str | None = None,
) -> checkpoint.CommitCheckpoint:
    cp = checkpoint.CommitCheckpoint(
        method=method,
        payload=payload if payload is not None else {"message": "fix: bug"},
        cwd=cwd,
        completed_steps=list(completed_steps) if completed_steps else [],
        cl_name=cl_name,
        project_file=project_file,
        cs_name=cs_name,
        entry_id=entry_id,
        dispatch_result=dispatch_result,
        publication_agent=publication_agent,
        primary_revision=primary_revision,
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


@patch(_PROVIDER_TARGET)
def test_resume_records_finalized_commit_sha_for_conflict_originated_dispatch(
    mock_get: MagicMock, artifacts_dir: Path, tmp_path: Path
) -> None:
    """Resume must record a real SHA where cp.dispatch_result stayed null.

    A dispatch that ended in CONFLICT never set cp.dispatch_result, so before
    this fix the ledger recorded "result": null for the commit this run
    actually finalized. Resume has the repo and the finalized HEAD in hand
    and must resolve and record its SHA.
    """
    provider = _make_provider(head_subject="fix: bug")
    provider.revision_id.return_value = "c" * 40
    mock_get.return_value = provider

    _save_checkpoint(cwd=str(tmp_path), payload={"message": "fix: bug"})

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


@patch(_PROVIDER_TARGET)
def test_resume_resolves_commit_sha_after_finalize_commit(
    mock_get: MagicMock, artifacts_dir: Path, tmp_path: Path
) -> None:
    """The SHA must be resolved after finalize_commit's amend/push/rebase."""
    provider = _make_provider(head_subject="fix: bug")
    mock_get.return_value = provider

    events: list[str] = []
    provider.finalize_commit.side_effect = lambda *_a, **_k: (
        events.append("finalize") or (True, None)
    )
    provider.revision_id.side_effect = lambda *_a, **_k: (
        events.append("revision_id") or "c" * 40
    )

    _save_checkpoint(cwd=str(tmp_path), payload={"message": "fix: bug"})

    with (
        patch(
            "sase.workflows.commit.workflow.append_commits_entry",
            return_value="42",
        ),
        patch("sase.workflows.commit.workflow.write_result_marker"),
    ):
        assert CommitWorkflow.resume() == RunResult.OK

    assert events == ["finalize", "revision_id", "revision_id"]


@patch(_PROVIDER_TARGET)
def test_resume_resolves_commit_sha_when_finalize_commit_unsupported(
    mock_get: MagicMock, artifacts_dir: Path, tmp_path: Path
) -> None:
    """Even without finalize_commit support, HEAD's SHA is still knowable."""
    provider = _make_provider(head_subject="fix: bug", finalize_raises=True)
    provider.revision_id.return_value = "d" * 40
    mock_get.return_value = provider

    _save_checkpoint(cwd=str(tmp_path), payload={"message": "fix: bug"})

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


@patch(_PROVIDER_TARGET)
def test_resume_reaches_close_bead_step(
    mock_get: MagicMock, artifacts_dir: Path, tmp_path: Path
) -> None:
    provider = _make_provider(head_subject="fix: bug")
    mock_get.return_value = provider

    _save_checkpoint(
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
            "sase.workflows.commit.workflow.close_task_bead_after_commit",
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


@patch(_PROVIDER_TARGET)
def test_resume_skips_completed_close_bead_step(
    mock_get: MagicMock, artifacts_dir: Path, tmp_path: Path
) -> None:
    provider = _make_provider(head_subject="fix: bug")
    mock_get.return_value = provider

    _save_checkpoint(
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
            "sase.workflows.commit.workflow.close_task_bead_after_commit"
        ) as close_bead,
    ):
        assert CommitWorkflow.resume() == RunResult.OK

    close_bead.assert_not_called()
    assert not (artifacts_dir / "commit_state.json").exists()


@patch(_PROVIDER_TARGET)
def test_resume_reuses_checkpointed_bead_tag_without_reapplying_it(
    mock_get: MagicMock,
    artifacts_dir: Path,
    tmp_path: Path,
) -> None:
    message = "fix: bug\n\nSASE_BEAD=sase-ai.2"
    provider = _make_provider(head_subject="fix: bug", head_message=message)
    provider.revision_id.return_value = "a" * 40
    mock_get.return_value = provider
    _save_checkpoint(
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


@patch(_PROVIDER_TARGET)
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
    provider = _make_provider(
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

    _save_checkpoint(cwd=str(tmp_path), payload={"message": checkpoint_message})

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


@patch(_PROVIDER_TARGET)
def test_resume_fails_loudly_when_footer_restamp_amend_fails(
    mock_get: MagicMock, artifacts_dir: Path, tmp_path: Path
) -> None:
    """A failed re-stamp aborts resume instead of pushing an unattributed commit."""
    checkpoint_message = "fix: bug\n\nSASE_AGENT=bbugyi200.athena.sase-ai.2"
    provider = _make_provider(
        head_subject="fix: bug",
        head_message="fix: bug\n\nRewritten body, no footer.",
        amend_result=(False, "no changes to amend"),
    )
    mock_get.return_value = provider

    _save_checkpoint(cwd=str(tmp_path), payload={"message": checkpoint_message})

    assert CommitWorkflow.resume() == RunResult.FAILED
    provider.finalize_commit.assert_not_called()
    # Checkpoint preserved so the user can inspect / retry manually.
    assert (artifacts_dir / "commit_state.json").exists()


@patch(_PROVIDER_TARGET)
def test_resume_after_hook_failure_does_not_finalize_or_duplicate_dispatch(
    mock_get: MagicMock, artifacts_dir: Path, tmp_path: Path
) -> None:
    provider = _make_provider(head_subject="fix: bug")
    mock_get.return_value = provider
    _save_checkpoint(
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


@patch(_PROVIDER_TARGET)
def test_resume_publishes_agent_hood_without_redispatching_primary_commit(
    mock_get: MagicMock,
    artifacts_dir: Path,
    tmp_path: Path,
) -> None:
    from sase.agents_sync.commit_publication import _CommitPublicationOutcome

    provider = _make_provider(head_subject="fix: bug")
    provider.revision_id.return_value = "a" * 40
    mock_get.return_value = provider
    _save_checkpoint(
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


@patch(_PROVIDER_TARGET)
def test_resume_skips_completed_after_hook(
    mock_get: MagicMock, artifacts_dir: Path, tmp_path: Path
) -> None:
    provider = _make_provider(head_subject="fix: bug")
    mock_get.return_value = provider
    _save_checkpoint(
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


@patch(_PROVIDER_TARGET)
def test_resume_is_idempotent_across_repeated_invocations(
    mock_get: MagicMock,
    artifacts_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The shared fixture must prevent an ambient after-commit hook from trying
    # to resolve an installed ``sase`` command during resume.
    monkeypatch.setenv("PATH", str(tmp_path / "empty-bin"))
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


@patch(_PROVIDER_TARGET)
def test_resume_detects_existing_patch_in_project_file(
    mock_get: MagicMock, artifacts_dir: Path, tmp_path: Path
) -> None:
    """Observation-level idempotency: skip create_patch if the name exists."""
    provider = _make_provider(head_subject="feat: x")
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


@patch(_PROVIDER_TARGET)
def test_resume_attributes_markers_to_checkpointed_repo_not_process_cwd(
    mock_get: MagicMock,
    artifacts_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A resume launched outside the checkpointed repo still records that repo."""
    provider = _make_provider(head_subject="fix: bug")
    provider.revision_id.return_value = "c" * 40
    mock_get.return_value = provider

    checkpoint_cwd = tmp_path / "plans"
    launch_dir = tmp_path / "workspace"
    checkpoint_cwd.mkdir()
    launch_dir.mkdir()
    monkeypatch.chdir(launch_dir)
    assert os.getcwd() != str(checkpoint_cwd)

    _save_checkpoint(cwd=str(checkpoint_cwd), payload={"message": "fix: bug"})

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

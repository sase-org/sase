"""Tests for checkpoint persistence + conflict detection in CommitWorkflow.run()."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from sase.workflows.commit import checkpoint
from sase.workflows.commit.workflow import CommitWorkflow, RunResult

_PROVIDER_TARGET = "sase.workflows.commit.workflow.get_vcs_provider"
_CONFIG_TARGET = "sase.workflows.commit.precommit_hooks.load_merged_config"
_PROJECT_NAME_TARGET = "sase.workflows.utils.get_project_from_workspace"


@pytest.fixture(autouse=True)
def _no_precommit():  # type: ignore[no-untyped-def]
    """Prevent precommit commands and SASE_PLAN from running in tests."""
    with (
        patch(_CONFIG_TARGET, return_value={"precommit_command": ""}),
        patch.dict("os.environ", {"SASE_PLAN": ""}, clear=False),
    ):
        yield


@pytest.fixture
def artifacts_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Direct checkpoint persistence to a hermetic artifacts directory."""
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(tmp_path))
    return tmp_path


def _make_provider(
    *, dispatch_result: tuple[bool, str | None], is_conflict: bool = False
) -> MagicMock:
    provider = MagicMock()
    provider._provider_name = "git"
    provider.create_commit.return_value = dispatch_result
    provider.create_proposal.return_value = dispatch_result
    provider.create_pull_request.return_value = dispatch_result
    provider.is_sync_in_progress.return_value = is_conflict
    provider.get_conflicted_files.return_value = ["a.py"] if is_conflict else []
    provider.diff.return_value = (True, None)
    return provider


@patch(_PROVIDER_TARGET)
def test_run_detects_conflict_and_returns_conflict_code(
    mock_get: MagicMock, artifacts_dir: Path
) -> None:
    provider = _make_provider(
        dispatch_result=(False, "merge conflict"), is_conflict=True
    )
    mock_get.return_value = provider

    payload: dict[str, Any] = {"message": "fix: bug", "files": ["a.py"]}
    wf = CommitWorkflow(payload, "create_commit")

    assert wf.run() == RunResult.CONFLICT

    cp_path = artifacts_dir / "commit_state.json"
    assert cp_path.exists(), "checkpoint must remain on disk after a conflict"
    loaded = checkpoint.load(str(cp_path))
    assert loaded is not None
    assert loaded.completed_steps == []
    assert loaded.payload == payload
    assert loaded.method == "create_commit"


@patch(_PROVIDER_TARGET)
def test_run_failure_without_conflict_deletes_checkpoint(
    mock_get: MagicMock, artifacts_dir: Path
) -> None:
    provider = _make_provider(
        dispatch_result=(False, "git add failed"), is_conflict=False
    )
    mock_get.return_value = provider

    wf = CommitWorkflow({"message": "fix: bug"}, "create_commit")

    assert wf.run() == RunResult.FAILED
    assert not (artifacts_dir / "commit_state.json").exists()


@patch(_PROVIDER_TARGET)
def test_run_success_deletes_checkpoint(
    mock_get: MagicMock, artifacts_dir: Path
) -> None:
    provider = _make_provider(dispatch_result=(True, "abc123"))
    mock_get.return_value = provider

    wf = CommitWorkflow({"message": "fix: bug"}, "create_commit")

    assert wf.run() == RunResult.OK
    assert not (artifacts_dir / "commit_state.json").exists()


@patch(_PROVIDER_TARGET)
def test_run_records_completed_steps_in_order_for_create_commit(
    mock_get: MagicMock, artifacts_dir: Path
) -> None:
    provider = _make_provider(dispatch_result=(True, "abc123"))
    mock_get.return_value = provider

    snapshots: list[list[str]] = []
    real_save = checkpoint.save

    def spy_save(
        cp: checkpoint._CommitCheckpoint, path: str | None = None
    ) -> str | None:
        snapshots.append(list(cp.completed_steps))
        return real_save(cp, path)

    wf = CommitWorkflow({"message": "fix: bug"}, "create_commit")

    with (
        patch(
            "sase.workflows.commit.workflow.append_commits_entry",
            return_value="42",
        ),
        patch("sase.workflows.commit.workflow.checkpoint.save", side_effect=spy_save),
    ):
        assert wf.run() == RunResult.OK

    # Reduce to the unique progression we care about.
    seen: list[list[str]] = []
    for snap in snapshots:
        if not seen or snap != seen[-1]:
            seen.append(snap)

    assert seen[0] == []  # pre-dispatch
    assert seen[-1] == [
        "dispatch",
        "write_result_marker",
        "append_commits_entry",
        "final_result_marker",
    ]


@patch(_PROJECT_NAME_TARGET, return_value=None)
@patch(_PROVIDER_TARGET)
def test_run_records_completed_steps_for_pull_request(
    mock_get: MagicMock,
    mock_proj_name: MagicMock,
    artifacts_dir: Path,
) -> None:
    provider = _make_provider(dispatch_result=(True, "https://x/pr/1"))
    mock_get.return_value = provider

    snapshots: list[list[str]] = []
    real_save = checkpoint.save

    def spy_save(
        cp: checkpoint._CommitCheckpoint, path: str | None = None
    ) -> str | None:
        snapshots.append(list(cp.completed_steps))
        return real_save(cp, path)

    wf = CommitWorkflow({"name": "feat", "message": "feat: x"}, "create_pull_request")

    with (
        patch(
            "sase.workflows.commit.workflow.create_changespec",
            return_value="proj_feat_1",
        ),
        patch("sase.workflows.commit.workflow.checkpoint.save", side_effect=spy_save),
    ):
        assert wf.run() == RunResult.OK

    seen: list[list[str]] = []
    for snap in snapshots:
        if not seen or snap != seen[-1]:
            seen.append(snap)
    assert seen[0] == []
    assert seen[-1] == [
        "dispatch",
        "create_changespec",
        "write_result_marker",
    ]


@patch(_PROVIDER_TARGET)
def test_conflict_detected_via_get_conflicted_files_when_sync_probe_fails(
    mock_get: MagicMock, artifacts_dir: Path
) -> None:
    """Falls back to get_conflicted_files when is_sync_in_progress raises."""
    provider = MagicMock()
    provider._provider_name = "git"
    provider.create_commit.return_value = (False, "merge conflict")
    provider.is_sync_in_progress.side_effect = NotImplementedError
    provider.get_conflicted_files.return_value = ["a.py"]
    provider.diff.return_value = (True, None)
    mock_get.return_value = provider

    wf = CommitWorkflow({"message": "fix"}, "create_commit")

    assert wf.run() == RunResult.CONFLICT
    assert (artifacts_dir / "commit_state.json").exists()


@patch(_PROVIDER_TARGET)
def test_pre_dispatch_checkpoint_has_post_mutation_payload_for_pr(
    mock_get: MagicMock,
    artifacts_dir: Path,
) -> None:
    """Checkpoint payload reflects PR prefix / tags applied before dispatch."""
    provider = _make_provider(
        dispatch_result=(False, "merge conflict"), is_conflict=True
    )
    mock_get.return_value = provider

    payload: dict[str, Any] = {"name": "feat", "message": "feat: x"}
    wf = CommitWorkflow(payload, "create_pull_request")

    def _mark_mutation(payload: dict, parent: str | None) -> None:
        payload["_mutated"] = True

    with (
        patch(_PROJECT_NAME_TARGET, return_value=None),
        patch("sase.workflows.commit.workflow.apply_project_pr_prefix"),
        patch(
            "sase.workflows.commit.workflow.append_pr_tags",
            side_effect=_mark_mutation,
        ),
        patch("sase.workflows.commit.workflow.build_pr_body"),
    ):
        assert wf.run() == RunResult.CONFLICT

    loaded = checkpoint.load(str(artifacts_dir / "commit_state.json"))
    assert loaded is not None
    assert loaded.payload.get("_mutated") is True


@patch(_PROVIDER_TARGET)
def test_dispatch_step_recorded_after_success(
    mock_get: MagicMock, artifacts_dir: Path
) -> None:
    provider = _make_provider(dispatch_result=(True, "abc123"))
    mock_get.return_value = provider

    saved_states: list[dict] = []
    real_save = checkpoint.save

    def spy_save(
        cp: checkpoint._CommitCheckpoint, path: str | None = None
    ) -> str | None:
        saved_states.append(
            {
                "completed_steps": list(cp.completed_steps),
                "dispatch_result": cp.dispatch_result,
            }
        )
        return real_save(cp, path)

    wf = CommitWorkflow({"message": "fix"}, "create_commit")

    with (
        patch(
            "sase.workflows.commit.workflow.append_commits_entry",
            return_value="1",
        ),
        patch("sase.workflows.commit.workflow.checkpoint.save", side_effect=spy_save),
    ):
        assert wf.run() == RunResult.OK

    # Find the first save that includes "dispatch".
    dispatch_state = next(s for s in saved_states if "dispatch" in s["completed_steps"])
    assert dispatch_state["dispatch_result"] == "abc123"


@patch(_PROVIDER_TARGET)
def test_pre_dispatch_checkpoint_written_before_dispatch(
    mock_get: MagicMock, artifacts_dir: Path
) -> None:
    """The first save() is the pre-dispatch snapshot with no completed steps."""
    provider = _make_provider(
        dispatch_result=(False, "merge conflict"), is_conflict=True
    )
    mock_get.return_value = provider

    saves_before_dispatch: list[list[str]] = []
    dispatch_called = False
    real_save = checkpoint.save

    def spy_save(
        cp: checkpoint._CommitCheckpoint, path: str | None = None
    ) -> str | None:
        if not dispatch_called:
            saves_before_dispatch.append(list(cp.completed_steps))
        return real_save(cp, path)

    def _dispatch(*_args: object, **_kwargs: object) -> tuple[bool, str | None]:
        nonlocal dispatch_called
        dispatch_called = True
        return (False, "merge conflict")

    provider.create_commit.side_effect = _dispatch

    wf = CommitWorkflow({"message": "fix"}, "create_commit")

    with patch("sase.workflows.commit.workflow.checkpoint.save", side_effect=spy_save):
        assert wf.run() == RunResult.CONFLICT

    assert saves_before_dispatch == [[]]


def test_append_commits_entry_idempotent_with_expected_entry_id(
    tmp_path: Path,
) -> None:
    """When the COMMITS drawer already has the entry, no new line is appended."""
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
    mtime_before = os.path.getmtime(project_file)

    result = append_commits_entry(
        str(project_file),
        "test-cl",
        {"message": "won't be added"},
        "create_commit",
        None,
        expected_entry_id="99",
    )

    assert result == "99"
    assert project_file.read_text() == initial
    assert os.path.getmtime(project_file) == mtime_before


def test_append_commits_entry_appends_when_expected_entry_id_missing(
    tmp_path: Path,
) -> None:
    """When the expected ID is not present, the entry is appended normally."""
    from sase.workflows.commit.commit_tracking import append_commits_entry

    project_file = tmp_path / "proj.gp"
    project_file.write_text(
        "NAME: test-cl\nDESCRIPTION:\n  desc\nCOMMITS:\nSTATUS: Pending\n"
    )

    result = append_commits_entry(
        str(project_file),
        "test-cl",
        {"message": "first commit"},
        "create_commit",
        None,
        expected_entry_id="99",
    )

    assert result == "1"
    assert "first commit" in project_file.read_text()

"""Tests for commit hook sequencing in CommitWorkflow.run()."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sase.workflows.commit import checkpoint
from sase.workflows.commit.workflow import CommitWorkflow, RunResult
from tests._commit_workflow_fixtures import (
    commit_artifacts_dir,  # noqa: F401 (registers artifacts_dir fixture)
    make_provider,
    no_commit_hooks,  # noqa: F401 (imported for fixture discovery, re-used below)
)

_PROVIDER_TARGET = "sase.workflows.commit.workflow.get_vcs_provider"


@pytest.fixture(autouse=True)
def _no_commit_hooks(no_commit_hooks):  # type: ignore[no-untyped-def]  # noqa: F811
    yield


@patch(_PROVIDER_TARGET)
def test_run_logs_before_hook_failure_reason(
    mock_get: MagicMock, artifacts_dir: Path
) -> None:
    provider = make_provider(dispatch_result=(True, "abc123"))
    mock_get.return_value = provider

    wf = CommitWorkflow({"message": "fix: bug"}, "create_commit")

    with (
        patch(
            "sase.workflows.commit.workflow.run_before_commit_hook", return_value=False
        ),
        patch("sase.logs.run_log.log_event") as mock_log,
    ):
        assert wf.run() == RunResult.FAILED

    mock_log.assert_any_call(
        event="commit_failed", method="create_commit", reason="before_hook_failed"
    )
    provider.create_commit.assert_not_called()


@patch(_PROVIDER_TARGET)
def test_commit_hooks_bracket_successful_dispatch(
    mock_get: MagicMock, artifacts_dir: Path
) -> None:
    events: list[str] = []
    provider = make_provider(dispatch_result=(True, "abc123"))
    provider.create_commit.side_effect = lambda *_args: (
        events.append("dispatch") or (True, "abc123")
    )
    mock_get.return_value = provider

    with (
        patch(
            "sase.workflows.commit.workflow.run_before_commit_hook",
            side_effect=lambda _cwd: events.append("before") or True,
        ),
        patch(
            "sase.workflows.commit.workflow.run_after_commit_hook",
            side_effect=lambda _cwd: events.append("after") or True,
        ),
    ):
        assert (
            CommitWorkflow({"message": "fix: bug"}, "create_commit").run()
            == RunResult.OK
        )

    assert events == ["before", "dispatch", "after"]


@patch(_PROVIDER_TARGET)
def test_after_hook_failure_preserves_post_dispatch_checkpoint(
    mock_get: MagicMock, artifacts_dir: Path, capsys
) -> None:
    provider = make_provider(dispatch_result=(True, "abc123"))
    mock_get.return_value = provider

    with (
        patch(
            "sase.workflows.commit.workflow.run_after_commit_hook",
            return_value=False,
        ),
        patch("sase.workflows.commit.workflow.write_result_marker") as marker,
    ):
        result = CommitWorkflow({"message": "fix: bug"}, "create_commit").run()

    assert result == RunResult.FAILED
    loaded = checkpoint.checkpoint_load(str(artifacts_dir / "commit_state.json"))
    assert loaded is not None
    assert loaded.completed_steps == ["dispatch"]
    assert loaded.dispatch_result == "abc123"
    marker.assert_not_called()
    captured = capsys.readouterr()
    assert "commit may already be pushed" in captured.out.lower()
    assert "--resume" in captured.out


@pytest.mark.parametrize(
    ("method", "dispatch_result"),
    [
        ("create_proposal", (True, "proposal.diff")),
        ("create_commit", (False, "git add failed")),
    ],
)
@patch(_PROVIDER_TARGET)
def test_after_hook_skipped_for_proposals_and_failed_dispatches(
    mock_get: MagicMock,
    method: str,
    dispatch_result: tuple[bool, str],
    artifacts_dir: Path,
) -> None:
    provider = make_provider(dispatch_result=dispatch_result)
    mock_get.return_value = provider

    with patch("sase.workflows.commit.workflow.run_after_commit_hook") as after_hook:
        CommitWorkflow({"message": "fix: bug"}, method).run()

    after_hook.assert_not_called()

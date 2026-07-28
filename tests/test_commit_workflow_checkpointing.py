"""Tests for checkpoint persistence + conflict detection in CommitWorkflow.run()."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from sase.core.commit_footer_facade import LinkedCommitTagValue
from sase.workflows.commit import checkpoint
from sase.workflows.commit.workflow import CommitWorkflow, RunResult
from tests._commit_workflow_fixtures import (
    no_commit_hooks,  # noqa: F401 (imported for fixture discovery, re-used as fixture arg)
)

_PROVIDER_TARGET = "sase.workflows.commit.workflow.get_vcs_provider"
_PROJECT_NAME_TARGET = "sase.workflows.utils.get_project_from_workspace"


@pytest.fixture(autouse=True)
def _no_commit_hooks(no_commit_hooks):  # type: ignore[no-untyped-def]  # noqa: F811
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
    loaded = checkpoint.checkpoint_load(str(cp_path))
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

    with patch("sase.logs.run_log.log_event") as mock_log:
        assert wf.run() == RunResult.FAILED

    mock_log.assert_any_call(
        event="commit_failed", method="create_commit", reason="other"
    )
    assert not (artifacts_dir / "commit_state.json").exists()


@patch(_PROVIDER_TARGET)
def test_run_logs_before_hook_failure_reason(
    mock_get: MagicMock, artifacts_dir: Path
) -> None:
    provider = _make_provider(dispatch_result=(True, "abc123"))
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
def test_run_success_deletes_checkpoint(
    mock_get: MagicMock, artifacts_dir: Path
) -> None:
    provider = _make_provider(dispatch_result=(True, "abc123"))
    mock_get.return_value = provider

    wf = CommitWorkflow({"message": "fix: bug"}, "create_commit")

    assert wf.run() == RunResult.OK
    assert not (artifacts_dir / "commit_state.json").exists()


@patch(_PROVIDER_TARGET)
def test_commit_hooks_bracket_successful_dispatch(
    mock_get: MagicMock, artifacts_dir: Path
) -> None:
    events: list[str] = []
    provider = _make_provider(dispatch_result=(True, "abc123"))
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
    provider = _make_provider(dispatch_result=(True, "abc123"))
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
    provider = _make_provider(dispatch_result=dispatch_result)
    mock_get.return_value = provider

    with patch("sase.workflows.commit.workflow.run_after_commit_hook") as after_hook:
        CommitWorkflow({"message": "fix: bug"}, method).run()

    after_hook.assert_not_called()


@patch(_PROVIDER_TARGET)
def test_run_records_completed_steps_in_order_for_create_commit(
    mock_get: MagicMock, artifacts_dir: Path
) -> None:
    provider = _make_provider(dispatch_result=(True, "abc123"))
    mock_get.return_value = provider

    snapshots: list[list[str]] = []
    real_save = checkpoint.checkpoint_save

    def spy_save(
        cp: checkpoint.CommitCheckpoint, path: str | None = None
    ) -> str | None:
        snapshots.append(list(cp.completed_steps))
        return real_save(cp, path)

    wf = CommitWorkflow({"message": "fix: bug"}, "create_commit")

    with (
        patch(
            "sase.workflows.commit.workflow.append_commits_entry",
            return_value="42",
        ),
        patch("sase.workflows.commit.workflow.checkpoint_save", side_effect=spy_save),
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
        "after_hook",
        "write_result_marker",
        "append_commits_entry",
        "final_result_marker",
    ]


@patch(_PROVIDER_TARGET)
def test_publication_failure_with_durable_outbox_keeps_primary_successful(
    mock_get: MagicMock,
    artifacts_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.agents_sync.commit_publication import _CommitPublicationOutcome
    from sase.core.agent_identity_facade import AgentOwnerIdentity

    monkeypatch.setenv("SASE_AGENT_NAME", "foo--code")
    monkeypatch.setattr(
        "sase.config.require_agent_owner_identity",
        lambda: AgentOwnerIdentity("test-user", "test_host"),
    )
    provider = _make_provider(dispatch_result=(True, "not-a-sha"))
    provider.revision_id.return_value = "a" * 40
    mock_get.return_value = provider

    with (
        patch(
            "sase.agents_sync.commit_publication.publish_committed_agent_hood",
            return_value=_CommitPublicationOutcome(
                queued=True,
                error="sidecar push failed",
            ),
        ) as publish,
        patch(
            "sase.workflows.commit.workflow.append_commits_entry",
            return_value=None,
        ),
    ):
        assert CommitWorkflow({"message": "fix: bug"}, "create_commit").run() == (
            RunResult.OK
        )

    publish.assert_called_once_with(
        "foo--code",
        "a" * 40,
        commit_cwd=os.getcwd(),
    )
    assert not (artifacts_dir / "commit_state.json").exists()


@patch(_PROVIDER_TARGET)
def test_publication_without_target_warns_but_keeps_primary_successful(
    mock_get: MagicMock,
    artifacts_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from sase.agents_sync.commit_publication import _CommitPublicationOutcome
    from sase.core.agent_identity_facade import AgentOwnerIdentity

    monkeypatch.setenv("SASE_AGENT_NAME", "foo--code")
    monkeypatch.setattr(
        "sase.config.require_agent_owner_identity",
        lambda: AgentOwnerIdentity("test-user", "test_host"),
    )
    provider = _make_provider(dispatch_result=(True, "not-a-sha"))
    provider.revision_id.return_value = "a" * 40
    mock_get.return_value = provider

    with (
        patch(
            "sase.agents_sync.commit_publication.publish_committed_agent_hood",
            return_value=_CommitPublicationOutcome(
                skip_reason="repository does not map to a publishable project",
            ),
        ) as publish,
        patch(
            "sase.workflows.commit.workflow.append_commits_entry",
            return_value=None,
        ),
    ):
        assert CommitWorkflow({"message": "fix: bug"}, "create_commit").run() == (
            RunResult.OK
        )

    publish.assert_called_once_with(
        "foo--code",
        "a" * 40,
        commit_cwd=os.getcwd(),
    )
    output = " ".join(capsys.readouterr().out.split())
    assert f"skipped for repository {os.getcwd()!r}" in output
    assert "does not map to a publishable project" in output
    assert not (artifacts_dir / "commit_state.json").exists()


@patch(_PROVIDER_TARGET)
def test_publication_warning_names_quarantined_backlog(
    mock_get: MagicMock,
    artifacts_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from sase.agents_sync.commit_publication import _CommitPublicationOutcome
    from sase.core.agent_identity_facade import AgentOwnerIdentity

    monkeypatch.setenv("SASE_AGENT_NAME", "foo--code")
    monkeypatch.setattr(
        "sase.config.require_agent_owner_identity",
        lambda: AgentOwnerIdentity("test-user", "test_host"),
    )
    provider = _make_provider(dispatch_result=(True, "not-a-sha"))
    provider.revision_id.return_value = "a" * 40
    mock_get.return_value = provider

    with (
        patch(
            "sase.agents_sync.commit_publication.publish_committed_agent_hood",
            return_value=_CommitPublicationOutcome(
                queued=True,
                quarantined=2,
                error="committing agent absent from project inventory",
            ),
        ),
        patch(
            "sase.workflows.commit.workflow.append_commits_entry",
            return_value=None,
        ),
    ):
        assert CommitWorkflow({"message": "fix: bug"}, "create_commit").run() == (
            RunResult.OK
        )

    output = " ".join(capsys.readouterr().out.split())
    assert "already has 2 quarantined agent-hood publication requests" in output
    assert "link written to this commit may remain unavailable" in output
    assert "sase agent sync --retry-quarantined" in output
    assert "will retry automatically" not in output
    assert not (artifacts_dir / "commit_state.json").exists()


@patch(_PROVIDER_TARGET)
def test_publication_warning_names_drop_command_for_retired_backlog(
    mock_get: MagicMock,
    artifacts_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from sase.agents_sync.commit_publication import _CommitPublicationOutcome
    from sase.core.agent_identity_facade import AgentOwnerIdentity

    monkeypatch.setenv("SASE_AGENT_NAME", "foo--code")
    monkeypatch.setattr(
        "sase.config.require_agent_owner_identity",
        lambda: AgentOwnerIdentity("test-user", "test_host"),
    )
    provider = _make_provider(dispatch_result=(True, "not-a-sha"))
    provider.revision_id.return_value = "a" * 40
    mock_get.return_value = provider

    with (
        patch(
            "sase.agents_sync.commit_publication.publish_committed_agent_hood",
            return_value=_CommitPublicationOutcome(
                queued=True,
                retired=3,
                error="hood 'lt' has no publishable runs",
            ),
        ),
        patch(
            "sase.workflows.commit.workflow.append_commits_entry",
            return_value=None,
        ),
    ):
        assert CommitWorkflow({"message": "fix: bug"}, "create_commit").run() == (
            RunResult.OK
        )

    output = " ".join(capsys.readouterr().out.split())
    assert "already has 3 retired agent-hood publication requests" in output
    assert "sase agent sync --drop-retired" in output
    assert "sase agent sync --retry-quarantined" not in output
    assert "will retry automatically" not in output


@patch(_PROVIDER_TARGET)
def test_family_member_commit_uses_metadata_for_footer_and_publication(
    mock_get: MagicMock,
    artifacts_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.agents_sync.commit_publication import _CommitPublicationOutcome
    from sase.core.agent_identity_facade import AgentOwnerIdentity

    (artifacts_dir / "agent_meta.json").write_text(
        '{"name": "ms--code", "workflow_name": "ms"}',
        encoding="utf-8",
    )
    monkeypatch.setenv("SASE_AGENT_NAME", "ms")
    monkeypatch.setattr(
        "sase.config.require_agent_owner_identity",
        lambda: AgentOwnerIdentity("bbugyi200", "athena"),
    )
    provider = _make_provider(dispatch_result=(True, "not-a-sha"))
    provider.revision_id.return_value = "a" * 40
    mock_get.return_value = provider
    linked_tag = LinkedCommitTagValue(
        "bbugyi200.athena.ms--code",
        "https://github.com/sase-org/sase--agents/blob/main/"
        "families/bbugyi200.athena.ms.md#member-code",
    )

    with (
        patch(
            "sase.agents_sync.links.resolve_agent_commit_tag",
            return_value=linked_tag,
        ) as resolve_tag,
        patch(
            "sase.agents_sync.commit_publication.publish_committed_agent_hood",
            return_value=_CommitPublicationOutcome(published=True),
        ) as publish,
        patch(
            "sase.workflows.commit.workflow.append_commits_entry",
            return_value=None,
        ),
    ):
        assert CommitWorkflow({"message": "fix: bug"}, "create_commit").run() == (
            RunResult.OK
        )

    payload = provider.create_commit.call_args.args[0]
    assert payload["message"] == (
        "fix: bug\n\nSASE_AGENT=[bbugyi200.athena.ms--code][1]\n\n"
        "[1]: https://github.com/sase-org/sase--agents/blob/main/"
        "families/bbugyi200.athena.ms.md#member-code"
    )
    resolve_tag.assert_called_once()
    assert resolve_tag.call_args.args[0] == "ms--code"
    publish.assert_called_once_with(
        "ms--code",
        "a" * 40,
        commit_cwd=os.getcwd(),
    )
    assert not (artifacts_dir / "commit_state.json").exists()


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
    real_save = checkpoint.checkpoint_save

    def spy_save(
        cp: checkpoint.CommitCheckpoint, path: str | None = None
    ) -> str | None:
        snapshots.append(list(cp.completed_steps))
        return real_save(cp, path)

    wf = CommitWorkflow({"name": "feat", "message": "feat: x"}, "create_pull_request")

    with (
        patch(
            "sase.workflows.commit.workflow.create_changespec",
            return_value="proj_feat_1",
        ),
        patch("sase.workflows.commit.workflow.checkpoint_save", side_effect=spy_save),
    ):
        assert wf.run() == RunResult.OK

    seen: list[list[str]] = []
    for snap in snapshots:
        if not seen or snap != seen[-1]:
            seen.append(snap)
    assert seen[0] == []
    assert seen[-1] == [
        "dispatch",
        "after_hook",
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

    loaded = checkpoint.checkpoint_load(str(artifacts_dir / "commit_state.json"))
    assert loaded is not None
    assert loaded.payload.get("_mutated") is True


@patch(_PROVIDER_TARGET)
def test_dispatch_step_recorded_after_success(
    mock_get: MagicMock, artifacts_dir: Path
) -> None:
    provider = _make_provider(dispatch_result=(True, "abc123"))
    mock_get.return_value = provider

    saved_states: list[dict] = []
    real_save = checkpoint.checkpoint_save

    def spy_save(
        cp: checkpoint.CommitCheckpoint, path: str | None = None
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
        patch("sase.workflows.commit.workflow.checkpoint_save", side_effect=spy_save),
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
    real_save = checkpoint.checkpoint_save

    def spy_save(
        cp: checkpoint.CommitCheckpoint, path: str | None = None
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

    with patch("sase.workflows.commit.workflow.checkpoint_save", side_effect=spy_save):
        assert wf.run() == RunResult.CONFLICT

    assert saves_before_dispatch == [[]]


def test_append_commits_entry_idempotent_with_expected_entry_id(
    tmp_path: Path,
) -> None:
    """When the COMMITS drawer already has the entry, no new line is appended."""
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

    project_file = tmp_path / "proj.sase"
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

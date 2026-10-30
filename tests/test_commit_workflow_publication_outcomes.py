"""Workflow-level publication outcome tests for CommitWorkflow.

Split from ``tests.test_commit_workflow_publication``; the original module
re-exports these tests so its import path keeps working.
"""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from sase.agents_sync._commit_publication_types import CommitPublicationOutcome
from sase.core.agent_identity_facade import AgentOwnerIdentity
from sase.core.commit_footer_facade import LinkedCommitTagValue
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


def _configure_publication(
    mock_get: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
    *,
    agent_name: str = "foo--code",
    owner: AgentOwnerIdentity | None = None,
) -> MagicMock:
    monkeypatch.setenv("SASE_AGENT_NAME", agent_name)
    owner = owner or AgentOwnerIdentity("test-user", "test_host")
    monkeypatch.setattr("sase.config.require_agent_owner_identity", lambda: owner)
    provider = make_provider(dispatch_result=(True, "not-a-sha"))
    provider.revision_id.return_value = "a" * 40
    mock_get.return_value = provider
    return provider


@patch(_PROVIDER_TARGET)
def test_commit_publishes_post_commit_revision_not_pre_dispatch_head(
    mock_get: MagicMock,
    artifacts_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_publication(mock_get, monkeypatch)
    mock_get.return_value.revision_id.side_effect = ["0" * 40, "1" * 40, "2" * 40]
    prompt_revisions: list[str] = []
    hood_revisions: list[str] = []

    def capture_prompt(
        _agent: str, revision: str, **_kwargs: object
    ) -> SimpleNamespace:
        prompt_revisions.append(revision)
        return SimpleNamespace(
            error=None, skip_reason=None, prompt_path=None, queued=False
        )

    def capture_hood(
        _agent: str, revision: str, **_kwargs: object
    ) -> CommitPublicationOutcome:
        hood_revisions.append(revision)
        return CommitPublicationOutcome(published=True)

    with (
        patch(
            "sase.agents_sync.prompt_archive.publish_prompt_archive",
            side_effect=capture_prompt,
        ),
        patch(
            "sase.agents_sync.commit_publication.publish_committed_agent_hood",
            side_effect=capture_hood,
        ),
        patch(
            "sase.workflows.commit._workflow_tracking.append_commits_entry",
            return_value=None,
        ),
    ):
        assert CommitWorkflow({"message": "fix: bug"}, "create_commit").run() == (
            RunResult.OK
        )

    assert prompt_revisions == ["1" * 40]
    assert hood_revisions == ["1" * 40]


@patch(_PROVIDER_TARGET)
def test_publication_failure_with_durable_outbox_keeps_primary_successful(
    mock_get: MagicMock,
    artifacts_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _configure_publication(mock_get, monkeypatch)

    with (
        patch(
            "sase.agents_sync.commit_publication.publish_committed_agent_hood",
            return_value=CommitPublicationOutcome(
                queued=True,
                error="sidecar push failed",
            ),
        ) as publish,
        patch(
            "sase.workflows.commit._workflow_tracking.append_commits_entry",
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
        artifacts_dir=str(artifacts_dir),
        run_id=None,
    )
    output = " ".join(capsys.readouterr().out.split())
    assert "agent-hood publication is queued and will retry automatically" in output
    assert "Last error: sidecar push failed" in output
    assert not (artifacts_dir / "commit_state.json").exists()


@patch(_PROVIDER_TARGET)
def test_unqueueable_publication_fails_the_commit_with_a_resume_hint(
    mock_get: MagicMock,
    artifacts_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _configure_publication(mock_get, monkeypatch)

    with (
        patch(
            "sase.agents_sync.commit_publication.publish_committed_agent_hood",
            return_value=CommitPublicationOutcome(
                error="could not persist agents publication retry: disk is full",
            ),
        ),
        patch(
            "sase.workflows.commit._workflow_tracking.append_commits_entry",
            return_value=None,
        ),
    ):
        assert CommitWorkflow({"message": "fix: bug"}, "create_commit").run() == (
            RunResult.FAILED
        )

    output = " ".join(capsys.readouterr().out.split())
    assert "agent publication could not be queued" in output
    assert "disk is full" in output
    assert "sase stitch create --resume" in output
    assert (artifacts_dir / "commit_state.json").exists()


@patch(_PROVIDER_TARGET)
def test_publication_raising_fails_the_commit_with_a_resume_hint(
    mock_get: MagicMock,
    artifacts_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _configure_publication(mock_get, monkeypatch)

    with (
        patch(
            "sase.agents_sync.commit_publication.publish_committed_agent_hood",
            side_effect=RuntimeError("agents lock is wedged"),
        ),
        patch(
            "sase.workflows.commit._workflow_tracking.append_commits_entry",
            return_value=None,
        ),
    ):
        assert CommitWorkflow({"message": "fix: bug"}, "create_commit").run() == (
            RunResult.FAILED
        )

    output = " ".join(capsys.readouterr().out.split())
    assert "agent publication failed before a retry could be confirmed" in output
    assert "agents lock is wedged" in output
    assert "sase stitch create --resume" in output
    assert (artifacts_dir / "commit_state.json").exists()


@patch(_PROVIDER_TARGET)
def test_deferred_prompt_archive_rides_the_durable_agent_publication(
    mock_get: MagicMock,
    artifacts_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _configure_publication(mock_get, monkeypatch)

    with (
        patch(
            "sase.agents_sync.prompt_archive.publish_prompt_archive",
            return_value=SimpleNamespace(
                error="agents sync lock is busy",
                queued=True,
                skip_reason=None,
                prompt_path=None,
            ),
        ),
        patch(
            "sase.agents_sync.commit_publication.publish_committed_agent_hood",
            return_value=CommitPublicationOutcome(published=True),
        ),
        patch(
            "sase.workflows.commit._workflow_tracking.append_commits_entry",
            return_value=None,
        ),
    ):
        assert CommitWorkflow({"message": "fix: bug"}, "create_commit").run() == (
            RunResult.OK
        )

    output = " ".join(capsys.readouterr().out.split())
    assert "prompt archive publication was deferred and will retry with " in output
    assert "agent publication: agents sync lock is busy" in output
    assert not (artifacts_dir / "commit_state.json").exists()


@patch(_PROVIDER_TARGET)
def test_unqueueable_prompt_archive_fails_the_commit_with_a_resume_hint(
    mock_get: MagicMock,
    artifacts_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _configure_publication(mock_get, monkeypatch)

    with (
        patch(
            "sase.agents_sync.prompt_archive.publish_prompt_archive",
            return_value=SimpleNamespace(
                error="could not persist agents publication retry: disk is full",
                queued=False,
                skip_reason=None,
                prompt_path=None,
            ),
        ),
        patch(
            "sase.agents_sync.commit_publication.publish_committed_agent_hood",
            side_effect=AssertionError("agent publication must not run"),
        ),
        patch(
            "sase.workflows.commit._workflow_tracking.append_commits_entry",
            return_value=None,
        ),
    ):
        assert CommitWorkflow({"message": "fix: bug"}, "create_commit").run() == (
            RunResult.FAILED
        )

    output = " ".join(capsys.readouterr().out.split())
    assert "prompt archive publication could not be queued" in output
    assert "disk is full" in output
    assert "sase stitch create --resume" in output
    assert (artifacts_dir / "commit_state.json").exists()


@patch(_PROVIDER_TARGET)
def test_publication_without_target_warns_but_keeps_primary_successful(
    mock_get: MagicMock,
    artifacts_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _configure_publication(mock_get, monkeypatch)

    with (
        patch(
            "sase.agents_sync.commit_publication.publish_committed_agent_hood",
            return_value=CommitPublicationOutcome(
                skip_reason="repository does not map to a publishable project",
            ),
        ) as publish,
        patch(
            "sase.workflows.commit._workflow_tracking.append_commits_entry",
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
        artifacts_dir=str(artifacts_dir),
        run_id=None,
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
    _configure_publication(mock_get, monkeypatch)

    with (
        patch(
            "sase.agents_sync.commit_publication.publish_committed_agent_hood",
            return_value=CommitPublicationOutcome(
                queued=True,
                quarantined=2,
                error="committing agent absent from project inventory",
            ),
        ),
        patch(
            "sase.workflows.commit._workflow_tracking.append_commits_entry",
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
    _configure_publication(mock_get, monkeypatch)

    with (
        patch(
            "sase.agents_sync.commit_publication.publish_committed_agent_hood",
            return_value=CommitPublicationOutcome(
                queued=True,
                retired=3,
                error="hood 'lt' has no publishable runs",
            ),
        ),
        patch(
            "sase.workflows.commit._workflow_tracking.append_commits_entry",
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
def test_agent_session_member_commit_uses_metadata_for_footer_and_publication(
    mock_get: MagicMock,
    artifacts_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (artifacts_dir / "agent_meta.json").write_text(
        '{"name": "ms--code", "workflow_name": "ms"}',
        encoding="utf-8",
    )
    provider = _configure_publication(
        mock_get,
        monkeypatch,
        agent_name="ms",
        owner=AgentOwnerIdentity("bbugyi200", "athena"),
    )
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
            return_value=CommitPublicationOutcome(queued=True),
        ) as publish,
        patch(
            "sase.workflows.commit._workflow_tracking.append_commits_entry",
            return_value=None,
        ),
    ):
        assert CommitWorkflow({"message": "fix: bug"}, "create_commit").run() == (
            RunResult.OK
        )

    payload = provider.create_commit.call_args.args[0]
    assert payload["message"] == (
        "fix: bug\n\nSASE_TYPE=stitch\nSASE_AGENT=[bbugyi200.athena.ms--code][1]\n\n"
        "[1]: https://github.com/sase-org/sase--agents/blob/main/"
        "families/bbugyi200.athena.ms.md#member-code"
    )
    resolve_tag.assert_called_once()
    assert resolve_tag.call_args.args[0] == "ms--code"
    publish.assert_called_once_with(
        "ms--code",
        "a" * 40,
        commit_cwd=os.getcwd(),
        artifacts_dir=str(artifacts_dir),
        run_id=None,
    )
    assert not (artifacts_dir / "commit_state.json").exists()

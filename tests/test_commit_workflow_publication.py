"""Tests for agent-hood publication after CommitWorkflow dispatch."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sase.agents_sync.commit_publication import _CommitPublicationOutcome
from sase.agents_sync.prompt_archive import PromptArchivePublicationOutcome
from sase.core.agent_identity_facade import AgentOwnerIdentity
from sase.core.commit_footer_facade import LinkedCommitTagValue
from sase.workflows.commit.checkpoint import CommitCheckpoint
from sase.workflows.commit.workflow import CommitWorkflow, RunResult
from sase.workflows.commit.workflow_publication import run_agent_publication_step
from tests._commit_workflow_fixtures import (
    commit_artifacts_dir,  # noqa: F401 (registers artifacts_dir fixture)
    make_provider,
    no_commit_hooks,  # noqa: F401 (imported for fixture discovery, re-used below)
)

_PROVIDER_TARGET = "sase.workflows.commit.workflow.get_vcs_provider"


def test_prompt_archive_precedes_plan_refresh_and_hood_publication(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    order: list[str] = []
    cp = CommitCheckpoint(
        method="create_commit",
        payload={"message": "fix: archive"},
        cwd=str(tmp_path),
        primary_revision="a" * 40,
        publication_agent="worker",
        completed_steps=["publish_bead_pages"],
    )
    monkeypatch.setattr(
        "sase.agents_sync.prompt_archive.publish_prompt_archive",
        lambda *_args, **_kwargs: (
            order.append("archive") or PromptArchivePublicationOutcome(published=True)
        ),
    )
    monkeypatch.setattr(
        "sase.agents_sync.commit_publication.refresh_committed_plan_header",
        lambda *_args, **_kwargs: order.append("refresh"),
    )
    monkeypatch.setattr(
        "sase.agents_sync.commit_publication.publish_committed_agent_hood",
        lambda *_args, **_kwargs: (
            order.append("hood") or _CommitPublicationOutcome(published=True)
        ),
    )

    assert run_agent_publication_step(
        cp,
        "create_commit",
        checkpoint_save=lambda _cp: None,
        get_vcs_provider=lambda _cwd: pytest.fail("revision is already resolved"),
    )

    assert order == ["archive", "refresh", "hood"]
    assert "publish_prompt_archive" in cp.completed_steps
    assert "publish_agent_hood" in cp.completed_steps


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
def test_publication_failure_with_durable_outbox_keeps_primary_successful(
    mock_get: MagicMock,
    artifacts_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_publication(mock_get, monkeypatch)

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
    _configure_publication(mock_get, monkeypatch)

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
    _configure_publication(mock_get, monkeypatch)

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
    _configure_publication(mock_get, monkeypatch)

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

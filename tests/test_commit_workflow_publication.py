"""Tests for agent-hood publication after CommitWorkflow dispatch."""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from sase.agents_sync.commit_publication import _CommitPublicationOutcome
from sase.agents_sync.publication_outbox import list_agent_publications
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


def test_commit_publishes_every_sidecar_inline_in_order(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    order: list[str] = []
    cp = CommitCheckpoint(
        method="create_commit",
        payload={
            "message": (
                "fix: archive\n\nSASE_BEAD=sase-ai.5\nSASE_PLAN=plans:202608/archive.md"
            )
        },
        cwd=str(tmp_path),
        primary_revision="a" * 40,
        publication_agent="worker",
    )
    monkeypatch.setattr(
        "sase.sdd.checkout_anchor.resolve_checkout_anchor",
        lambda _cwd: SimpleNamespace(primary_root=tmp_path, project_name="Project"),
    )
    monkeypatch.setattr(
        "sase.bead_pages.publication.publish_committed_bead_pages",
        lambda *_args, **_kwargs: (
            order.append("beads") or SimpleNamespace(changed=True, error=None)
        ),
    )
    monkeypatch.setattr(
        "sase.agents_sync.prompt_archive.publish_prompt_archive",
        lambda *_args, **_kwargs: (
            order.append("prompt")
            or SimpleNamespace(error=None, skip_reason=None, prompt_path=None)
        ),
    )
    monkeypatch.setattr(
        "sase.sdd.plan_header_refresh.refresh_committed_plan_header",
        lambda *_args, **_kwargs: (
            order.append("plan") or SimpleNamespace(changed=True, error=None)
        ),
    )
    monkeypatch.setattr(
        "sase.agents_sync.commit_publication.publish_committed_agent_hood",
        lambda *_args, **_kwargs: (
            order.append("agent") or _CommitPublicationOutcome(published=True)
        ),
    )

    assert run_agent_publication_step(
        cp,
        "create_commit",
        checkpoint_save=lambda _cp: None,
        get_vcs_provider=lambda _cwd: pytest.fail("revision is already resolved"),
    )

    assert order == ["beads", "prompt", "plan", "agent"]
    assert cp.completed_steps == [
        "publish_bead_pages",
        "publish_prompt_archive",
        "publish_agent_hood",
    ]


def test_fully_tagged_commit_and_resume_publish_each_sidecar_once(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "state"))
    primary = tmp_path / "primary"
    primary.mkdir()
    calls: list[str] = []
    monkeypatch.setattr(
        "sase.sdd.checkout_anchor.resolve_checkout_anchor",
        lambda _cwd: SimpleNamespace(primary_root=primary, project_name="Project"),
    )
    monkeypatch.setattr(
        "sase.bead_pages.publication.publish_committed_bead_pages",
        lambda *_args, **_kwargs: (
            calls.append("beads") or SimpleNamespace(changed=True, error=None)
        ),
    )
    monkeypatch.setattr(
        "sase.agents_sync.prompt_archive.publish_prompt_archive",
        lambda *_args, **_kwargs: (
            calls.append("prompt")
            or SimpleNamespace(error=None, skip_reason=None, prompt_path=None)
        ),
    )
    monkeypatch.setattr(
        "sase.sdd.plan_header_refresh.refresh_committed_plan_header",
        lambda *_args, **_kwargs: (
            calls.append("plan") or SimpleNamespace(changed=True, error=None)
        ),
    )
    monkeypatch.setattr(
        "sase.agents_sync.commit_publication.publish_committed_agent_hood",
        lambda *_args, **_kwargs: (
            calls.append("agent") or _CommitPublicationOutcome(published=True)
        ),
    )
    message = (
        "feat: publish now\n\n"
        "SASE_BEAD=sase-ai.5\n"
        "SASE_PLAN=plans:202608/publish_now.md"
    )
    cp = CommitCheckpoint(
        method="create_commit",
        payload={"message": message},
        cwd=str(primary),
        primary_revision="b" * 40,
        publication_agent="worker--code",
    )

    for _ in range(2):
        assert run_agent_publication_step(
            cp,
            "create_commit",
            checkpoint_save=lambda _cp: None,
            get_vcs_provider=lambda _cwd: pytest.fail("revision already resolved"),
        )

    # A resumed commit must not publish bead pages, the prompt archive, or the
    # agent hood a second time; only the idempotent plan refresh reruns.
    assert calls.count("beads") == 1
    assert calls.count("prompt") == 1
    assert calls.count("agent") == 1
    assert list_agent_publications("proj") == ()


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
    capsys: pytest.CaptureFixture[str],
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
            return_value=_CommitPublicationOutcome(
                error="could not persist agents publication retry: disk is full",
            ),
        ),
        patch(
            "sase.workflows.commit.workflow.append_commits_entry",
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
            "sase.workflows.commit.workflow.append_commits_entry",
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
            return_value=_CommitPublicationOutcome(published=True),
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
            "sase.workflows.commit.workflow.append_commits_entry",
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
            return_value=_CommitPublicationOutcome(queued=True),
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

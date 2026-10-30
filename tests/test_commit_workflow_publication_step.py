"""Direct publication-step tests for CommitWorkflow agent-hood publication.

Split from ``tests.test_commit_workflow_publication``; the original module
re-exports these tests so its import path keeps working.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from sase.agents_sync._commit_publication_types import CommitPublicationOutcome
from sase.agents_sync.publication_outbox import list_agent_publications
from sase.sdd.artifact_link_release_evidence import (
    artifact_link_run_has_release_evidence,
)
from sase.sdd.artifact_link_store import ArtifactLinkStore
from sase.workflows.commit.checkpoint import CommitCheckpoint
from sase.workflows.commit.workflow_publication import run_agent_publication_step
from sase.finalizers.steps import STEPS_ENV_VAR
from tests._commit_workflow_fixtures import (
    no_commit_hooks,  # noqa: F401 (imported for fixture discovery, re-used below)
)
from tests._conftest_environment import redirect_sase_home


@pytest.fixture(autouse=True)
def _no_commit_hooks(no_commit_hooks):  # type: ignore[no-untyped-def]  # noqa: F811
    yield


def test_commit_publishes_every_sidecar_inline_in_order(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    steps_path = tmp_path / "publication.steps.jsonl"
    monkeypatch.setenv(STEPS_ENV_VAR, str(steps_path))
    order: list[str] = []
    # A pre-rename commit trailer: proves the publication step still reads
    # the legacy "plans:" spelling.
    cp = CommitCheckpoint(
        method="create_commit",
        payload={
            "message": (
                "fix: archive\n\nSASE_BEAD=sase-ai.5\nSASE_PLAN=plans:202608/archive.md"
            )
        },
        cwd=str(tmp_path),
        primary_revision="a" * 40,
        commit_sha="a" * 40,
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
            order.append("agent") or CommitPublicationOutcome(published=True)
        ),
    )
    store = ArtifactLinkStore(project_key="gh_sase-org__sase", sidecar_roots={})
    monkeypatch.setattr(
        "sase.sdd.artifact_link_store.resolve_artifact_link_store",
        lambda **_kwargs: store,
    )
    monkeypatch.setattr(
        "sase.sdd.artifact_link_store.resolve_machine_artifact_link_store",
        lambda _project_key, _cwd: store,
    )
    monkeypatch.setattr(
        "sase.sdd.artifact_link_outbox.drain_artifact_link_outbox",
        lambda **_kwargs: order.append("outbox"),
    )

    assert run_agent_publication_step(
        cp,
        "create_commit",
        checkpoint_save=lambda _cp: None,
        get_vcs_provider=lambda _cwd: pytest.fail("revision is already resolved"),
    )

    assert order == ["beads", "prompt", "plan", "agent", "outbox"]
    assert cp.completed_steps == [
        "publish_bead_pages",
        "publish_prompt_archive",
        "drain_artifact_link_outbox",
        "publish_agent_hood",
    ]
    timed_steps = [
        json.loads(line)
        for line in steps_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    for name in (
        "bead_pages",
        "prompt_archive",
        "plan_header",
        "agent_hood",
        "artifact_link_outbox",
    ):
        rows = [row for row in timed_steps if row["step"] == f"publication: {name}"]
        assert [row["state"] for row in rows] == ["start", "ok"]
        assert rows[-1]["detail"].startswith("duration_seconds=")


def test_publication_step_records_release_evidence_for_this_run(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A real commit's publication step earns this run's own release evidence."""
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    monkeypatch.setenv("SASE_AGENT_TIMESTAMP", "260908_120000")
    store = ArtifactLinkStore(project_key="gh_sase-org__sase", sidecar_roots={})
    cp = CommitCheckpoint(
        method="create_commit",
        payload={"message": "fix: archive"},
        cwd=str(tmp_path),
        primary_revision="a" * 40,
        commit_sha="c" * 40,
        publication_agent="worker",
    )
    monkeypatch.setattr(
        "sase.sdd.checkout_anchor.resolve_checkout_anchor",
        lambda _cwd: SimpleNamespace(primary_root=tmp_path, project_name="Project"),
    )
    monkeypatch.setattr(
        "sase.bead_pages.publication.publish_committed_bead_pages",
        lambda *_args, **_kwargs: SimpleNamespace(changed=True, error=None),
    )
    monkeypatch.setattr(
        "sase.agents_sync.prompt_archive.publish_prompt_archive",
        lambda *_args, **_kwargs: SimpleNamespace(
            error=None, skip_reason=None, prompt_path=None
        ),
    )
    monkeypatch.setattr(
        "sase.sdd.plan_header_refresh.refresh_committed_plan_header",
        lambda *_args, **_kwargs: SimpleNamespace(changed=True, error=None),
    )
    monkeypatch.setattr(
        "sase.agents_sync.commit_publication.publish_committed_agent_hood",
        lambda *_args, **_kwargs: CommitPublicationOutcome(published=True),
    )
    monkeypatch.setattr(
        "sase.sdd.artifact_link_store.resolve_artifact_link_store",
        lambda **_kwargs: store,
    )
    monkeypatch.setattr(
        "sase.sdd.artifact_link_store.resolve_machine_artifact_link_store",
        lambda _project_key, _cwd: store,
    )
    drained: list[str] = []
    monkeypatch.setattr(
        "sase.sdd.artifact_link_outbox.drain_artifact_link_outbox",
        lambda **_kwargs: drained.append("outbox"),
    )

    assert (
        artifact_link_run_has_release_evidence(
            project_key="gh_sase-org__sase",
            run_id="260908_120000",
            agent_id="worker",
        )
        is False
    )

    assert run_agent_publication_step(
        cp,
        "create_commit",
        checkpoint_save=lambda _cp: None,
        get_vcs_provider=lambda _cwd: pytest.fail("revision is already resolved"),
    )

    assert drained == ["outbox"]
    assert artifact_link_run_has_release_evidence(
        project_key="gh_sase-org__sase",
        run_id="260908_120000",
        agent_id="worker",
    )


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
            calls.append("agent") or CommitPublicationOutcome(published=True)
        ),
    )
    store = ArtifactLinkStore(project_key="gh_sase-org__sase", sidecar_roots={})
    monkeypatch.setattr(
        "sase.sdd.artifact_link_store.resolve_artifact_link_store",
        lambda **_kwargs: store,
    )
    monkeypatch.setattr(
        "sase.sdd.artifact_link_store.resolve_machine_artifact_link_store",
        lambda _project_key, _cwd: store,
    )
    monkeypatch.setattr(
        "sase.sdd.artifact_link_outbox.drain_artifact_link_outbox",
        lambda **_kwargs: calls.append("outbox"),
    )
    message = (
        "feat: publish now\n\nSASE_BEAD=sase-ai.5\nSASE_PLAN=plan:202608/publish_now.md"
    )
    cp = CommitCheckpoint(
        method="create_commit",
        payload={"message": message},
        cwd=str(primary),
        primary_revision="b" * 40,
        commit_sha="b" * 40,
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
    assert calls.count("outbox") == 1
    assert list_agent_publications("proj") == ()


def test_resumed_legacy_checkpoint_keeps_prompt_archive_revision_for_hood(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    hood_revisions: list[str] = []
    cp = CommitCheckpoint(
        method="create_commit",
        payload={"message": "fix: bug"},
        cwd=str(tmp_path),
        primary_revision="0" * 40,
        commit_sha="1" * 40,
        publication_agent="worker",
        completed_steps=["publish_bead_pages", "publish_prompt_archive"],
    )
    monkeypatch.setattr(
        "sase.sdd.checkout_anchor.resolve_checkout_anchor",
        lambda _cwd: SimpleNamespace(primary_root=tmp_path, project_name="Project"),
    )
    monkeypatch.setattr(
        "sase.bead_pages.publication.publish_committed_bead_pages",
        lambda *_args, **_kwargs: SimpleNamespace(changed=True, error=None),
    )

    def _prompt_already_completed(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("prompt archive already completed")

    monkeypatch.setattr(
        "sase.agents_sync.prompt_archive.publish_prompt_archive",
        _prompt_already_completed,
    )
    monkeypatch.setattr(
        "sase.sdd.plan_header_refresh.refresh_committed_plan_header",
        lambda *_args, **_kwargs: SimpleNamespace(changed=True, error=None),
    )
    monkeypatch.setattr(
        "sase.agents_sync.commit_publication.publish_committed_agent_hood",
        lambda _agent, revision, **_kwargs: (
            hood_revisions.append(revision) or CommitPublicationOutcome(published=True)
        ),
    )
    store = ArtifactLinkStore(project_key="gh_sase-org__sase", sidecar_roots={})
    monkeypatch.setattr(
        "sase.sdd.artifact_link_store.resolve_artifact_link_store",
        lambda **_kwargs: store,
    )
    monkeypatch.setattr(
        "sase.sdd.artifact_link_store.resolve_machine_artifact_link_store",
        lambda _project_key, _cwd: store,
    )
    monkeypatch.setattr(
        "sase.sdd.artifact_link_outbox.drain_artifact_link_outbox",
        lambda **_kwargs: None,
    )

    assert run_agent_publication_step(
        cp,
        "create_commit",
        checkpoint_save=lambda _cp: None,
        get_vcs_provider=lambda _cwd: pytest.fail("legacy revision is already set"),
    )
    assert hood_revisions == ["0" * 40]
    assert cp.primary_revision == "0" * 40


def test_legacy_checkpoint_without_prompt_archive_publishes_commit_sha(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    prompt_revisions: list[str] = []
    hood_revisions: list[str] = []
    cp = CommitCheckpoint(
        method="create_commit",
        payload={"message": "fix: bug"},
        cwd=str(tmp_path),
        primary_revision="0" * 40,
        commit_sha="1" * 40,
        publication_agent="worker",
    )
    monkeypatch.setattr(
        "sase.sdd.checkout_anchor.resolve_checkout_anchor",
        lambda _cwd: SimpleNamespace(primary_root=tmp_path, project_name="Project"),
    )
    monkeypatch.setattr(
        "sase.bead_pages.publication.publish_committed_bead_pages",
        lambda *_args, **_kwargs: SimpleNamespace(changed=True, error=None),
    )
    monkeypatch.setattr(
        "sase.agents_sync.prompt_archive.publish_prompt_archive",
        lambda _agent, revision, **_kwargs: (
            prompt_revisions.append(revision)
            or SimpleNamespace(error=None, skip_reason=None, prompt_path=None)
        ),
    )
    monkeypatch.setattr(
        "sase.sdd.plan_header_refresh.refresh_committed_plan_header",
        lambda *_args, **_kwargs: SimpleNamespace(changed=True, error=None),
    )
    monkeypatch.setattr(
        "sase.agents_sync.commit_publication.publish_committed_agent_hood",
        lambda _agent, revision, **_kwargs: (
            hood_revisions.append(revision) or CommitPublicationOutcome(published=True)
        ),
    )
    store = ArtifactLinkStore(project_key="gh_sase-org__sase", sidecar_roots={})
    monkeypatch.setattr(
        "sase.sdd.artifact_link_store.resolve_artifact_link_store",
        lambda **_kwargs: store,
    )
    monkeypatch.setattr(
        "sase.sdd.artifact_link_store.resolve_machine_artifact_link_store",
        lambda _project_key, _cwd: store,
    )
    monkeypatch.setattr(
        "sase.sdd.artifact_link_outbox.drain_artifact_link_outbox",
        lambda **_kwargs: None,
    )

    assert run_agent_publication_step(
        cp,
        "create_commit",
        checkpoint_save=lambda _cp: None,
        get_vcs_provider=lambda _cwd: pytest.fail("commit_sha is already set"),
    )
    assert prompt_revisions == ["1" * 40]
    assert hood_revisions == ["1" * 40]
    assert cp.primary_revision == "1" * 40

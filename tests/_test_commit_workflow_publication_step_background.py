"""Background publication-step tests for CommitWorkflow."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from sase.agents_sync._commit_publication_types import CommitPublicationOutcome
from sase.workflows.commit.checkpoint import CommitCheckpoint
from sase.workflows.commit import workflow_publication
from sase.workflows.commit.workflow_publication import run_agent_publication_step


def test_live_background_publisher_enqueues_without_draining_sidecars(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    order: list[str] = []
    cp = CommitCheckpoint(
        method="create_commit",
        payload={"message": "fix: queue publication"},
        cwd=str(tmp_path),
        commit_sha="a" * 40,
        publication_agent="worker",
        run_id="run-1",
    )
    item = SimpleNamespace(
        local_agent="worker",
        global_agent="alice.athena.worker",
        primary_revision="a" * 40,
        run_id="run-1",
    )
    monkeypatch.setattr(
        "sase.config.core.load_merged_config",
        lambda: {"commit": {"publication": {"mode": "background"}}},
    )
    monkeypatch.setattr("sase.axe._process_probe.is_axe_running", lambda: True)
    monkeypatch.setattr(
        "sase.agents_sync.publication_doorbell.publisher_is_live", lambda _age: True
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
        "sase.sdd.plan_header_refresh.refresh_committed_plan_header",
        lambda *_args, **_kwargs: order.append("plan"),
    )
    monkeypatch.setattr(
        workflow_publication,
        "_record_real_change_release_evidence",
        lambda _cp, _project_key: order.append("release"),
    )

    def enqueue(*_args: object, **kwargs: object):
        order.append("enqueue")
        assert kwargs["commit_cwd"] == str(tmp_path)
        assert kwargs["run_id"] == "run-1"
        return CommitPublicationOutcome(queued=True), "project-key", item

    monkeypatch.setattr(
        "sase.agents_sync.commit_publication.enqueue_committed_agent_publication",
        enqueue,
    )

    def append_hint(_project_key: str, hint: dict[str, object]) -> None:
        order.append("hint")
        assert hint == {
            "local_agent": "worker",
            "global_agent": "alice.athena.worker",
            "primary_revision": "a" * 40,
            "run_id": "run-1",
            "link_outbox_agent_name": "worker",
        }

    monkeypatch.setattr(
        "sase.agents_sync.publication_doorbell.append_publication_hint", append_hint
    )
    monkeypatch.setattr(
        "sase.agents_sync.prompt_archive.publish_prompt_archive",
        lambda *_args, **_kwargs: pytest.fail("background branch must not publish"),
    )
    monkeypatch.setattr(
        "sase.sdd.artifact_link_outbox.drain_artifact_link_outbox",
        lambda **_kwargs: pytest.fail("background branch must not drain"),
    )

    assert run_agent_publication_step(
        cp,
        "create_commit",
        checkpoint_save=lambda _cp: None,
        get_vcs_provider=lambda _cwd: pytest.fail("commit SHA is already set"),
    )

    assert order == ["beads", "plan", "release", "enqueue", "hint"]
    assert cp.completed_steps == ["publish_bead_pages", "enqueue_agent_publication"]
    assert "Commit publication selected background enqueue" in capsys.readouterr().out


def test_background_resume_enqueues_legacy_prompt_checkpoint_revision(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    enqueued_revisions: list[str] = []
    cp = CommitCheckpoint(
        method="create_commit",
        payload={"message": "fix: resume publication"},
        cwd=str(tmp_path),
        primary_revision="0" * 40,
        commit_sha="1" * 40,
        publication_agent="worker",
        run_id="run-1",
        completed_steps=["publish_bead_pages", "publish_prompt_archive"],
    )
    item = SimpleNamespace(
        local_agent="worker",
        global_agent="alice.athena.worker",
        primary_revision="0" * 40,
        run_id="run-1",
    )
    monkeypatch.setattr(
        "sase.config.core.load_merged_config",
        lambda: {"commit": {"publication": {"mode": "background"}}},
    )
    monkeypatch.setattr("sase.axe._process_probe.is_axe_running", lambda: True)
    monkeypatch.setattr(
        "sase.agents_sync.publication_doorbell.publisher_is_live", lambda _age: True
    )
    monkeypatch.setattr(
        "sase.sdd.checkout_anchor.resolve_checkout_anchor",
        lambda _cwd: SimpleNamespace(primary_root=tmp_path, project_name="Project"),
    )
    monkeypatch.setattr(
        "sase.sdd.plan_header_refresh.refresh_committed_plan_header",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        workflow_publication,
        "_record_real_change_release_evidence",
        lambda _cp, _project_key: None,
    )

    def enqueue(_agent: str, revision: str, **_kwargs: object):
        enqueued_revisions.append(revision)
        return CommitPublicationOutcome(queued=True), "project-key", item

    monkeypatch.setattr(
        "sase.agents_sync.commit_publication.enqueue_committed_agent_publication",
        enqueue,
    )
    monkeypatch.setattr(
        "sase.agents_sync.publication_doorbell.append_publication_hint",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        "sase.agents_sync.prompt_archive.publish_prompt_archive",
        lambda *_args, **_kwargs: pytest.fail("legacy archive step is checkpointed"),
    )

    assert run_agent_publication_step(
        cp,
        "create_commit",
        checkpoint_save=lambda _cp: None,
        get_vcs_provider=lambda _cwd: pytest.fail("legacy revision is already set"),
    )

    assert enqueued_revisions == ["0" * 40]
    assert cp.completed_steps[-1] == "enqueue_agent_publication"


def test_background_enqueue_failure_keeps_commit_resumable(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    cp = CommitCheckpoint(
        method="create_commit",
        payload={"message": "fix: retry queue write"},
        cwd=str(tmp_path),
        primary_revision="a" * 40,
        commit_sha="a" * 40,
        publication_agent="worker",
    )
    monkeypatch.setattr(
        "sase.sdd.plan_header_refresh.refresh_committed_plan_header",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        workflow_publication,
        "_record_real_change_release_evidence",
        lambda _cp, _project_key: None,
    )
    monkeypatch.setattr(
        "sase.agents_sync.commit_publication.enqueue_committed_agent_publication",
        lambda *_args, **_kwargs: (
            CommitPublicationOutcome(error="queue write failed"),
            "project-key",
            None,
        ),
    )
    monkeypatch.setattr(
        "sase.agents_sync.publication_doorbell.append_publication_hint",
        lambda *_args, **_kwargs: pytest.fail("failed enqueue cannot append a hint"),
    )

    assert not workflow_publication._enqueue_agent_publication_background(
        cp,
        "worker",
        "a" * 40,
        "fix: retry queue write",
        checkpoint_save=lambda _cp: None,
    )
    assert "enqueue_agent_publication" not in cp.completed_steps

"""Linked repository publication-step tests for CommitWorkflow."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from sase._repo_inventory_models import RepoInventory, RepoRecord
from sase.agents_sync._commit_publication_types import CommitPublicationOutcome
from sase.sdd.artifact_link_release_evidence import (
    load_artifact_link_release_evidence_index,
)
from sase.sdd.artifact_link_store import ArtifactLinkStore
from sase.workflows.commit.checkpoint import CommitCheckpoint
from sase.workflows.commit import workflow_publication
from sase.workflows.commit.workflow_publication import run_agent_publication_step
from tests._conftest_environment import redirect_sase_home

_HOST_PROJECT_KEY = "gh_example-org__example"


def _linked_repo_inventory(linked_root: Path) -> RepoInventory:
    """Return an inventory mapping *linked_root* to the host project."""

    return RepoInventory(
        records=(
            RepoRecord(
                name="example-plugins",
                kind="linked",
                project="Example",
                project_key=_HOST_PROJECT_KEY,
                path=str(linked_root),
                exists=True,
                auto_clone=False,
                description=None,
                source="test",
                env_name=None,
            ),
        ),
    )


def _background_linked_checkpoint(linked_root: Path) -> CommitCheckpoint:
    return CommitCheckpoint(
        method="create_commit",
        payload={"message": "fix: linked checkout"},
        cwd=str(linked_root),
        commit_sha="b" * 40,
        primary_revision="b" * 40,
        publication_agent="worker",
        run_id="run-linked-1",
    )


def _mock_live_background_publisher(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "sase.config.core.load_merged_config",
        lambda: {"commit": {"publication": {"mode": "background"}}},
    )
    monkeypatch.setattr("sase.axe._process_probe.is_axe_running", lambda: True)
    monkeypatch.setattr(
        "sase.agents_sync.publication_doorbell.publisher_is_live", lambda _age: True
    )


def test_resolver_prefers_inventory_over_marker_and_project_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "sase.agents_sync._commit_publication_queue.collect_repo_inventory",
        lambda: _linked_repo_inventory(tmp_path),
    )
    monkeypatch.setattr(
        "sase.sdd.artifact_link_store.resolve_artifact_link_project_key",
        lambda _cwd: "marker-key",
    )
    cp = CommitCheckpoint(
        method="create_commit",
        payload={"message": "fix: order"},
        cwd=str(tmp_path),
        project_file="~/.sase/projects/other/other.sase",
    )

    assert workflow_publication._resolve_commit_publication_project_key(cp) == (
        _HOST_PROJECT_KEY
    )


def test_resolver_falls_back_to_marker_then_project_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "sase.agents_sync._commit_publication_queue.collect_repo_inventory",
        lambda: RepoInventory(records=()),
    )
    monkeypatch.setattr(
        "sase.sdd.artifact_link_store.resolve_artifact_link_project_key",
        lambda _cwd: "marker-key",
    )
    cp = CommitCheckpoint(
        method="create_commit",
        payload={"message": "fix: marker"},
        cwd=str(tmp_path),
        project_file="~/.sase/projects/other/other.sase",
    )

    assert workflow_publication._resolve_commit_publication_project_key(cp) == (
        "marker-key"
    )

    monkeypatch.setattr(
        "sase.sdd.artifact_link_store.resolve_artifact_link_project_key",
        lambda _cwd: None,
    )
    cp.project_file = (
        "~/.sase/projects/gh_example-org__example/gh_example-org__example.sase"
    )

    assert workflow_publication._resolve_commit_publication_project_key(cp) == (
        _HOST_PROJECT_KEY
    )


def test_resolver_returns_none_when_nothing_maps(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "sase.agents_sync._commit_publication_queue.collect_repo_inventory",
        lambda: RepoInventory(records=()),
    )
    monkeypatch.setattr(
        "sase.sdd.artifact_link_store.resolve_artifact_link_project_key",
        lambda _cwd: None,
    )
    cp = CommitCheckpoint(
        method="create_commit",
        payload={"message": "fix: unmapped"},
        cwd=str(tmp_path),
    )

    assert workflow_publication._resolve_commit_publication_project_key(cp) is None


def test_background_linked_checkout_keys_evidence_enqueue_and_hint_alike(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    linked = tmp_path / "example-plugins"
    linked.mkdir()
    monkeypatch.setattr(
        "sase.agents_sync._commit_publication_queue.collect_repo_inventory",
        lambda: _linked_repo_inventory(linked),
    )
    _mock_live_background_publisher(monkeypatch)
    monkeypatch.setattr(
        "sase.sdd.checkout_anchor.resolve_checkout_anchor",
        lambda _cwd: SimpleNamespace(primary_root=linked, project_name="Example"),
    )
    monkeypatch.setattr(
        "sase.bead_pages.publication.publish_committed_bead_pages",
        lambda *_args, **_kwargs: SimpleNamespace(changed=True, error=None),
    )
    monkeypatch.setattr(
        "sase.sdd.plan_header_refresh.refresh_committed_plan_header",
        lambda *_args, **_kwargs: SimpleNamespace(changed=True, error=None),
    )
    enqueued_projects: list[str | None] = []

    def enqueue(_agent: str, revision: str, **kwargs: object):
        enqueued_projects.append(kwargs.get("project"))  # type: ignore[arg-type]
        item = SimpleNamespace(
            local_agent="worker",
            global_agent="alice.athena.worker",
            primary_revision=revision,
            run_id=kwargs.get("run_id"),
        )
        return (
            CommitPublicationOutcome(queued=True),
            kwargs.get("project"),
            item,
        )

    monkeypatch.setattr(
        "sase.agents_sync.commit_publication.enqueue_committed_agent_publication",
        enqueue,
    )
    hinted_projects: list[str] = []
    monkeypatch.setattr(
        "sase.agents_sync.publication_doorbell.append_publication_hint",
        lambda project_key, _hint: hinted_projects.append(project_key),
    )
    cp = _background_linked_checkpoint(linked)

    assert run_agent_publication_step(
        cp,
        "create_commit",
        checkpoint_save=lambda _cp: None,
        get_vcs_provider=lambda _cwd: pytest.fail("commit SHA is already set"),
    )

    assert ("run-linked-1", "worker") in (
        load_artifact_link_release_evidence_index(_HOST_PROJECT_KEY)
    )
    assert enqueued_projects == [_HOST_PROJECT_KEY]
    assert hinted_projects == [_HOST_PROJECT_KEY]
    assert "enqueue_agent_publication" in cp.completed_steps


def test_inline_linked_checkout_drains_outbox_against_host_project(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    linked = tmp_path / "example-plugins"
    linked.mkdir()
    monkeypatch.setattr(
        "sase.agents_sync._commit_publication_queue.collect_repo_inventory",
        lambda: _linked_repo_inventory(linked),
    )
    cp = CommitCheckpoint(
        method="create_commit",
        payload={"message": "fix: inline linked"},
        cwd=str(linked),
        commit_sha="c" * 40,
        primary_revision="c" * 40,
        publication_agent="worker",
        run_id="run-inline-1",
    )
    monkeypatch.setattr(
        "sase.sdd.checkout_anchor.resolve_checkout_anchor",
        lambda _cwd: SimpleNamespace(primary_root=linked, project_name="Example"),
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
    machine_projects: list[str] = []
    machine_store = ArtifactLinkStore(project_key=_HOST_PROJECT_KEY, sidecar_roots={})

    def machine_store_for(project_key: str, _cwd: object) -> ArtifactLinkStore:
        machine_projects.append(project_key)
        return machine_store

    monkeypatch.setattr(
        "sase.sdd.artifact_link_store.resolve_machine_artifact_link_store",
        machine_store_for,
    )
    drained_agents: list[str] = []
    monkeypatch.setattr(
        "sase.sdd.artifact_link_outbox.drain_artifact_link_outbox",
        lambda **kwargs: drained_agents.append(kwargs["agent_name"]),
    )

    assert run_agent_publication_step(
        cp,
        "create_commit",
        checkpoint_save=lambda _cp: None,
        get_vcs_provider=lambda _cwd: pytest.fail("commit SHA is already set"),
    )

    assert machine_projects == [_HOST_PROJECT_KEY]
    assert drained_agents == ["worker"]
    assert ("run-inline-1", "worker") in (
        load_artifact_link_release_evidence_index(_HOST_PROJECT_KEY)
    )


def test_background_unmappable_repository_skips_without_resumable_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        "sase.agents_sync._commit_publication_queue.collect_repo_inventory",
        lambda: RepoInventory(records=()),
    )
    monkeypatch.setattr(
        "sase.sdd.artifact_link_store.resolve_artifact_link_project_key",
        lambda _cwd: None,
    )
    cp = CommitCheckpoint(
        method="create_commit",
        payload={"message": "fix: unmapped"},
        cwd=str(tmp_path),
        commit_sha="d" * 40,
        primary_revision="d" * 40,
        publication_agent="worker",
        run_id="run-unmapped-1",
    )
    monkeypatch.setattr(
        "sase.sdd.plan_header_refresh.refresh_committed_plan_header",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        "sase.agents_sync.commit_publication.enqueue_committed_agent_publication",
        lambda *_args, **_kwargs: (
            CommitPublicationOutcome(
                skip_reason=(
                    f"repository {str(tmp_path)!r} does not map to a SASE project"
                )
            ),
            None,
            None,
        ),
    )

    assert workflow_publication._resolve_commit_publication_project_key(cp) is None
    assert workflow_publication._enqueue_agent_publication_background(
        cp,
        "worker",
        "d" * 40,
        "fix: unmapped",
        checkpoint_save=lambda _cp: None,
    )

    out = capsys.readouterr().out
    assert "skipped" in out
    assert "--resume" not in out
    assert "enqueue_agent_publication" in cp.completed_steps


def test_background_evidence_write_error_keeps_commit_resumable(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        workflow_publication,
        "_resolve_commit_publication_project_key",
        lambda _cp: _HOST_PROJECT_KEY,
    )
    monkeypatch.setattr(
        "sase.sdd.plan_header_refresh.refresh_committed_plan_header",
        lambda *_args, **_kwargs: None,
    )

    def _fail_record(**_kwargs: object) -> None:
        raise RuntimeError("store unavailable")

    monkeypatch.setattr(
        "sase.sdd.artifact_link_release_evidence.record_artifact_link_release_evidence",
        _fail_record,
    )
    cp = _background_linked_checkpoint(tmp_path)
    monkeypatch.setattr(
        "sase.agents_sync.commit_publication.enqueue_committed_agent_publication",
        lambda *_args, **_kwargs: pytest.fail("evidence failure must not enqueue"),
    )

    assert not workflow_publication._enqueue_agent_publication_background(
        cp,
        "worker",
        "b" * 40,
        "fix: linked checkout",
        checkpoint_save=lambda _cp: None,
    )

    assert "--resume" in capsys.readouterr().out
    assert "enqueue_agent_publication" not in cp.completed_steps


def test_background_resume_after_evidence_failure_finishes_without_new_commit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    linked = tmp_path / "example-plugins"
    linked.mkdir()
    monkeypatch.setattr(
        "sase.agents_sync._commit_publication_queue.collect_repo_inventory",
        lambda: _linked_repo_inventory(linked),
    )
    _mock_live_background_publisher(monkeypatch)
    monkeypatch.setattr(
        "sase.sdd.checkout_anchor.resolve_checkout_anchor",
        lambda _cwd: SimpleNamespace(primary_root=linked, project_name="Example"),
    )
    monkeypatch.setattr(
        "sase.bead_pages.publication.publish_committed_bead_pages",
        lambda *_args, **_kwargs: pytest.fail("bead pages already completed"),
    )
    monkeypatch.setattr(
        "sase.sdd.plan_header_refresh.refresh_committed_plan_header",
        lambda *_args, **_kwargs: SimpleNamespace(changed=True, error=None),
    )
    monkeypatch.setattr(
        "sase.agents_sync.commit_publication.enqueue_committed_agent_publication",
        lambda _agent, revision, **kwargs: (
            CommitPublicationOutcome(queued=True),
            kwargs.get("project"),
            SimpleNamespace(
                local_agent="worker",
                global_agent="alice.athena.worker",
                primary_revision=revision,
                run_id=kwargs.get("run_id"),
            ),
        ),
    )
    hinted_projects: list[str] = []
    monkeypatch.setattr(
        "sase.agents_sync.publication_doorbell.append_publication_hint",
        lambda project_key, _hint: hinted_projects.append(project_key),
    )
    cp = _background_linked_checkpoint(linked)
    cp.completed_steps.append("publish_bead_pages")

    assert run_agent_publication_step(
        cp,
        "create_commit",
        checkpoint_save=lambda _cp: None,
        get_vcs_provider=lambda _cwd: pytest.fail("resume must not re-dispatch"),
    )

    assert ("run-linked-1", "worker") in (
        load_artifact_link_release_evidence_index(_HOST_PROJECT_KEY)
    )
    assert hinted_projects == [_HOST_PROJECT_KEY]
    assert "enqueue_agent_publication" in cp.completed_steps

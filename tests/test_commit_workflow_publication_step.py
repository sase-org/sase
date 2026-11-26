"""Direct publication-step tests for CommitWorkflow agent-hood publication.

Split from ``tests.test_commit_workflow_publication``; the original module
re-exports these tests so its import path keeps working.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from sase._repo_inventory_models import RepoInventory, RepoRecord
from sase.agents_sync._commit_publication_types import CommitPublicationOutcome
from sase.agents_sync.publication_outbox import list_agent_publications
from sase.sdd.artifact_link_release_evidence import (
    load_artifact_link_release_evidence_index,
)
from sase.sdd.artifact_link_store import ArtifactLinkStore
from sase.workflows.commit.checkpoint import CommitCheckpoint
from sase.workflows.commit import workflow_publication
from sase.workflows.commit.workflow_publication import run_agent_publication_step
from sase.finalizers.steps import STEPS_ENV_VAR
from tests._commit_workflow_fixtures import (
    no_commit_hooks,  # noqa: F401 (imported for fixture discovery, re-used below)
)
from tests._conftest_environment import redirect_sase_home


@pytest.fixture(autouse=True)
def _no_commit_hooks(no_commit_hooks):  # type: ignore[no-untyped-def]  # noqa: F811
    yield


@pytest.fixture(autouse=True)
def _inline_publication_unless_a_test_selects_background(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("sase.axe._process_probe.is_axe_running", lambda: False)


@pytest.mark.parametrize(
    ("mode", "axe_running", "publisher_live", "expected"),
    [
        ("background", True, True, True),
        ("background", True, False, False),
        ("background", False, True, False),
        ("inline", True, True, False),
    ],
)
def test_background_publication_requires_mode_axe_and_live_publisher(
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    axe_running: bool,
    publisher_live: bool,
    expected: bool,
) -> None:
    monkeypatch.setattr(
        "sase.config.core.load_merged_config",
        lambda: {"commit": {"publication": {"mode": mode}}},
    )
    monkeypatch.setattr("sase.axe._process_probe.is_axe_running", lambda: axe_running)
    monkeypatch.setattr(
        "sase.agents_sync.publication_doorbell.publisher_is_live",
        lambda _age: publisher_live,
    )

    selected, _reason = workflow_publication._background_publication_selected()

    assert selected is expected


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
        workflow_publication,
        "_resolve_commit_publication_project_key",
        lambda _cp: store.project_key,
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
        workflow_publication,
        "_resolve_commit_publication_project_key",
        lambda _cp: store.project_key,
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

    assert ("260908_120000", "worker") not in (
        load_artifact_link_release_evidence_index("gh_sase-org__sase")
    )

    assert run_agent_publication_step(
        cp,
        "create_commit",
        checkpoint_save=lambda _cp: None,
        get_vcs_provider=lambda _cwd: pytest.fail("revision is already resolved"),
    )

    assert drained == ["outbox"]
    assert ("260908_120000", "worker") in (
        load_artifact_link_release_evidence_index("gh_sase-org__sase")
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
        workflow_publication,
        "_resolve_commit_publication_project_key",
        lambda _cp: store.project_key,
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
        workflow_publication,
        "_resolve_commit_publication_project_key",
        lambda _cp: store.project_key,
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
        workflow_publication,
        "_resolve_commit_publication_project_key",
        lambda _cp: store.project_key,
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

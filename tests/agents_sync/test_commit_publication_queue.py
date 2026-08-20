from __future__ import annotations

import hashlib
from pathlib import Path
import subprocess

import pytest

from sase.agents_sync import commit_publication
from sase.agents_sync.commit_publication import (
    _publish_queued_locked,
    publish_committed_agent_hood,
)
from sase.agents_sync.git import run_git
from sase.agents_sync.inventory import ProjectHoodInventory
from sase.agents_sync.io import AgentsSyncFormatError
from sase.agents_sync.models import (
    IntegrationCounts,
    ProjectTarget,
    TargetSelection,
)
from sase.agents_sync.publication_outbox import (
    AgentPublicationOutboxItem,
    enqueue_agent_publication,
    list_agent_publications,
)
from sase.agents_sync.v2_io import (
    apply_payload_atomic,
    owner_manifest_path,
    v2_json_bytes,
)
from sase.agents_sync.v2_models import (
    V2OwnerHoodEntry,
    V2OwnerManifest,
    V2ProjectIdentity,
    V2PublicationCounts,
)
from sase.core.agent_identity_facade import AgentOwnerIdentity
from sase.core.project_lifecycle_wire import (
    PROJECT_LIFECYCLE_WIRE_SCHEMA_VERSION,
    ProjectRecordWire,
)
from sase.doctor.checks_agent_publication import _check_agent_publication_outbox
from sase.doctor.runner import DoctorContext
from tests.agents_sync.commit_publication_fixtures import git, setup_target


def test_committed_publication_records_a_retryable_request_when_git_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "state"))
    target, _remote = setup_target(tmp_path)
    owner = AgentOwnerIdentity("alice", "athena")
    monkeypatch.setattr(
        commit_publication,
        "resolve_sync_targets",
        lambda _projects: TargetSelection((target,), ()),
    )
    monkeypatch.setattr(
        commit_publication,
        "require_agent_owner_identity",
        lambda: owner,
    )

    def fail_git(
        cwd: Path,
        args: list[str],
        *,
        network: bool = False,
        op: str = "",
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args, 1, "", "git is unavailable")

    outcome = publish_committed_agent_hood(
        "worker--code",
        "a" * 40,
        project="Project",
        git_runner=fail_git,
    )

    # The synchronous publisher enqueues before it touches git, so a failed
    # sidecar attempt still leaves a durable request for `sase agent sync`.
    assert outcome.queued
    assert not outcome.published
    [request] = list_agent_publications("proj")
    assert request.global_agent == "alice.athena.worker"
    assert request.primary_revision == "a" * 40
    assert request.attempts == 1


def test_failed_targeted_publish_cleans_uncommitted_payload(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "state"))
    target, _remote = setup_target(tmp_path)
    owner = AgentOwnerIdentity("alice", "athena")
    enqueue_agent_publication(
        AgentPublicationOutboxItem(
            project_key="proj",
            project="Project",
            local_agent="broken--code",
            global_agent="alice.athena.broken--code",
            primary_revision="a" * 40,
            local_hood="broken",
        )
    )
    monkeypatch.setattr(
        commit_publication,
        "integrate_agent_imports_with_receipts",
        lambda *_args, **_kwargs: IntegrationCounts(),
    )
    monkeypatch.setattr(
        commit_publication,
        "build_project_hood_inventory",
        lambda *_args, **_kwargs: ProjectHoodInventory(owner, "proj", ()),
    )

    def fail_after_write(
        _target: ProjectTarget,
        repo: Path,
        _agent: str,
        **_kwargs: object,
    ) -> V2PublicationCounts:
        apply_payload_atomic(
            repo,
            {
                "README.md": b"# Stranded targeted publication\n",
                "agents/stranded/README.md": b"# Stranded agent\n",
            },
        )
        raise RuntimeError("targeted publication failed")

    monkeypatch.setattr(commit_publication, "publish_agent_hood", fail_after_write)

    result = _publish_queued_locked(target, owner, run_git)

    assert result.error is None
    assert result.drained == 0
    assert result.item_errors == (
        "could not publish agent hood 'broken': targeted publication failed",
    )
    assert not (target.sidecar_path / "README.md").exists()
    assert not (target.sidecar_path / "agents" / "stranded").exists()
    assert git(target.sidecar_path, "status", "--short").stdout == ""


def test_large_backlog_builds_one_inventory_and_publishes_each_hood_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target, _remote = setup_target(tmp_path)
    owner = AgentOwnerIdentity("alice", "athena")
    hoods = ("alpha", "beta", "gamma", "delta")
    requests = tuple(
        AgentPublicationOutboxItem(
            project_key="proj",
            project="Project",
            local_agent=f"{hood}.worker{i}",
            global_agent=f"alice.athena.{hood}.worker{i}",
            primary_revision=f"{i:040x}",
            local_hood=hood,
        )
        for i in range(2_000)
        for hood in (hoods[i % len(hoods)],)
    )
    inventory = ProjectHoodInventory(
        owner,
        "proj",
        tuple(object() for _ in range(5_000)),  # type: ignore[arg-type]
    )
    build_calls = 0
    integration_calls = 0
    published: list[tuple[str, ProjectHoodInventory]] = []
    updated: list[tuple[tuple[str, str], ...]] = []
    acknowledged: list[tuple[tuple[str, str], ...]] = []
    listed = 0
    cleaned = 0
    pulled = 0
    commit_checks = 0
    ahead_checks = 0

    def list_publications(_project_key, **_kwargs):
        nonlocal listed
        listed += 1
        return requests

    monkeypatch.setattr(
        commit_publication, "list_agent_publications", list_publications
    )

    def integrate(*_args, **_kwargs):
        nonlocal integration_calls
        integration_calls += 1
        return IntegrationCounts()

    def build(*_args, **_kwargs):
        nonlocal build_calls
        build_calls += 1
        return inventory

    def publish(_target, repo, agent, *, inventory, **_kwargs):
        published.append((agent.split(".", 1)[0], inventory))
        manifest = V2OwnerManifest(
            owner,
            V2ProjectIdentity("proj", "Project"),
            tuple(
                (hood, V2OwnerHoodEntry(f"{index:x}" * 64, ("README.md",), 1, 1))
                for index, hood in enumerate(hoods, start=1)
            ),
        )
        path = repo / owner_manifest_path(owner)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(v2_json_bytes(manifest.to_json_dict()))
        return V2PublicationCounts(hoods_published=1)

    monkeypatch.setattr(
        commit_publication,
        "integrate_agent_imports_with_receipts",
        integrate,
    )
    monkeypatch.setattr(commit_publication, "build_project_hood_inventory", build)
    monkeypatch.setattr(commit_publication, "publish_agent_hood", publish)
    monkeypatch.setattr(
        commit_publication,
        "update_agent_publications",
        lambda _project_key, keys, **_kwargs: updated.append(tuple(keys)),
    )
    monkeypatch.setattr(
        commit_publication,
        "acknowledge_agent_publications",
        lambda _project_key, keys: acknowledged.append(tuple(keys)),
    )

    from sase.agents_sync import git_sync

    def clean(*_args, **_kwargs):
        nonlocal cleaned
        cleaned += 1
        return None

    def pull(*_args, **_kwargs):
        nonlocal pulled
        pulled += 1
        return subprocess.CompletedProcess([], 0, "", "")

    def commit(*_args, **_kwargs):
        nonlocal commit_checks
        commit_checks += 1
        return False

    def ahead(*_args, **_kwargs):
        nonlocal ahead_checks
        ahead_checks += 1
        return 0

    monkeypatch.setattr(git_sync, "clean_agents_payload_worktree", clean)
    monkeypatch.setattr(
        git_sync,
        "pull_agents_rebase",
        pull,
    )
    monkeypatch.setattr(git_sync, "commit_agents_payload_if_dirty", commit)
    monkeypatch.setattr(git_sync, "agents_ahead_count", ahead)

    result = _publish_queued_locked(target, owner, run_git)

    assert result.error is None
    assert result.drained == len(requests)
    assert listed == 1
    assert cleaned == 2
    assert pulled == 1
    assert commit_checks == 1
    assert ahead_checks == 1
    assert integration_calls == 1
    assert build_calls == 1
    assert [hood for hood, _inventory in published] == list(hoods)
    assert all(seen_inventory is inventory for _hood, seen_inventory in published)
    assert sorted(len(keys) for keys in updated) == [500, 500, 500, 500]
    assert acknowledged == [tuple(item.logical_key for item in requests)]


def test_mixed_queue_publishes_good_items_and_quarantines_only_bad_item(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("SASE_AGENTS_PUBLICATION_MAX_ATTEMPTS", "2")
    target, remote = setup_target(tmp_path)
    owner = AgentOwnerIdentity("alice", "athena")
    monkeypatch.setattr(
        "sase.agents_sync.commit_publication.resolve_sync_targets",
        lambda _projects: TargetSelection((target,), ()),
    )
    monkeypatch.setattr(
        "sase.agents_sync.commit_publication.require_agent_owner_identity",
        lambda: owner,
    )
    monkeypatch.setattr(
        "sase.agents_sync.commit_publication.integrate_agent_imports_with_receipts",
        lambda *_args, **_kwargs: IntegrationCounts(),
    )
    for hood, revision in (("good", "a" * 40), ("bad", "b" * 40)):
        enqueue_agent_publication(
            AgentPublicationOutboxItem(
                project_key="proj",
                project="Project",
                local_agent=f"{hood}--code",
                global_agent=f"alice.athena.{hood}--code",
                primary_revision=revision,
                local_hood=hood,
            )
        )

    published: list[str] = []

    def publish(_target, repo, agent, **_kwargs):
        hood = agent.split("--", 1)[0]
        if hood == "bad":
            raise RuntimeError("broken historical record")
        published.append(hood)
        (repo / "README.md").write_text("# Published hoods\n")
        (repo / "schema.json").write_text("{}\n")
        (repo / "families").mkdir(exist_ok=True)
        (repo / "families" / ".gitkeep").write_text("")
        agent_page = repo / "agents" / hood / "README.md"
        agent_page.parent.mkdir(parents=True, exist_ok=True)
        agent_page.write_text(f"# {hood}\n")
        entries = tuple(
            (
                published_hood,
                V2OwnerHoodEntry(
                    hashlib.sha256(published_hood.encode()).hexdigest(),
                    (f"agents/{published_hood}/README.md",),
                    1,
                    1,
                ),
            )
            for published_hood in dict.fromkeys(published)
        )
        manifest = V2OwnerManifest(
            owner,
            V2ProjectIdentity("proj", "Project"),
            entries,
        )
        path = repo / owner_manifest_path(owner)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(v2_json_bytes(manifest.to_json_dict()))
        return V2PublicationCounts(hoods_published=1)

    monkeypatch.setattr(
        "sase.agents_sync.commit_publication.publish_agent_hood",
        publish,
    )

    first = publish_committed_agent_hood(
        "other--code",
        "c" * 40,
        project="Project",
        git_runner=run_git,
    )

    assert first.published and first.queued and first.drained == 2
    assert published == ["good", "other"]
    queued = list_agent_publications("proj")
    assert len(queued) == 1
    assert queued[0].local_hood == "bad"
    assert queued[0].attempts == 1
    assert queued[0].last_error is not None
    assert "broken historical record" in queued[0].last_error

    verify = tmp_path / "verify-mixed"
    git(tmp_path, "clone", str(remote), str(verify))
    assert (verify / "agents" / "good" / "README.md").is_file()
    assert (verify / "agents" / "other" / "README.md").is_file()

    second = publish_committed_agent_hood(
        "bad--code",
        "b" * 40,
        project="Project",
        git_runner=run_git,
    )
    assert second.queued and not second.published
    quarantined = list_agent_publications("proj")[0]
    assert quarantined.quarantined
    assert quarantined.attempts == 2

    third = publish_committed_agent_hood(
        "bad--code",
        "b" * 40,
        project="Project",
        git_runner=run_git,
    )
    assert third.queued and not third.published
    assert list_agent_publications("proj")[0].attempts == 2


def test_no_publishable_runs_retries_once_then_retires(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "state"))
    target, _remote = setup_target(tmp_path)
    owner = AgentOwnerIdentity("alice", "athena")
    monkeypatch.setattr(
        commit_publication,
        "resolve_sync_targets",
        lambda _projects: TargetSelection((target,), ()),
    )
    monkeypatch.setattr(
        commit_publication,
        "require_agent_owner_identity",
        lambda: owner,
    )
    monkeypatch.setattr(
        commit_publication,
        "integrate_agent_imports_with_receipts",
        lambda *_args, **_kwargs: IntegrationCounts(),
    )
    monkeypatch.setattr(
        commit_publication,
        "build_project_hood_inventory",
        lambda *_args, **_kwargs: ProjectHoodInventory(owner, "proj", ()),
    )

    def no_publishable_runs(
        _target: ProjectTarget,
        _repo: Path,
        _agent: str,
        **_kwargs: object,
    ) -> V2PublicationCounts:
        raise AgentsSyncFormatError("hood 'missing' has no publishable runs")

    monkeypatch.setattr(
        commit_publication,
        "publish_agent_hood",
        no_publishable_runs,
    )

    first = publish_committed_agent_hood(
        "missing--code",
        "a" * 40,
        project="Project",
        git_runner=run_git,
    )
    [pending] = list_agent_publications("proj")
    assert first.queued and not first.published
    assert pending.attempts == 1
    assert not pending.terminal
    assert not pending.quarantined

    second = publish_committed_agent_hood(
        "missing--code",
        "a" * 40,
        project="Project",
        git_runner=run_git,
    )
    [retired] = list_agent_publications("proj")
    assert second.queued and not second.published
    assert retired.attempts == 2
    assert retired.terminal
    assert retired.terminal_reason == retired.last_error
    assert not retired.quarantined
    assert list_agent_publications("proj", include_quarantined=False) == ()

    publish_committed_agent_hood(
        "missing--code",
        "a" * 40,
        project="Project",
        git_runner=run_git,
    )
    [still_retired] = list_agent_publications("proj")
    assert still_retired.terminal
    assert still_retired.terminal_reason == retired.terminal_reason
    assert still_retired.attempts == retired.attempts


def test_repeated_format_publication_failure_retires_and_doctor_says_drop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_home = tmp_path / "state"
    monkeypatch.setenv("SASE_HOME", str(state_home))
    target, _remote = setup_target(tmp_path)
    owner = AgentOwnerIdentity("alice", "athena")
    old_now = 1_000.0
    doctor_now = old_now + 3 * 24 * 60 * 60
    error_detail = (
        "invalid hood relationships: duplicate or inconsistent container global name"
    )
    full_error = f"could not publish agent hood 'research': {error_detail}"
    item = AgentPublicationOutboxItem(
        project_key="proj",
        project="Project",
        local_agent="research.cdx",
        global_agent="alice.athena.research.cdx",
        primary_revision="a" * 40,
        local_hood="research",
    )
    monkeypatch.setattr(
        "sase.agents_sync.publication_outbox_operations.time.time",
        lambda: old_now,
    )
    [queued] = (enqueue_agent_publication(item),)
    assert queued.attempts == 0
    assert queued.created_at == old_now

    monkeypatch.setattr(
        commit_publication,
        "integrate_agent_imports_with_receipts",
        lambda *_args, **_kwargs: IntegrationCounts(),
    )
    monkeypatch.setattr(
        commit_publication,
        "build_project_hood_inventory",
        lambda *_args, **_kwargs: ProjectHoodInventory(owner, "proj", ()),
    )

    def invalid_relationships(*_args: object, **_kwargs: object) -> None:
        raise AgentsSyncFormatError(error_detail)

    monkeypatch.setattr(
        commit_publication,
        "publish_agent_hood",
        invalid_relationships,
    )
    monkeypatch.setattr(
        "sase.agents_sync.publication_outbox_operations.time.time",
        lambda: doctor_now,
    )

    first = _publish_queued_locked(target, owner, run_git)
    [pending] = list_agent_publications("proj")
    assert first.drained == 0
    assert first.item_errors == (full_error,)
    assert pending.attempts == 1
    assert pending.last_error == full_error
    assert not pending.terminal
    assert not pending.quarantined
    assert list_agent_publications("proj", include_quarantined=False) == (pending,)

    second = _publish_queued_locked(target, owner, run_git)
    [retired] = list_agent_publications("proj")
    assert second.drained == 0
    assert second.item_errors == (full_error,)
    assert retired.attempts == 2
    assert retired.terminal
    assert retired.terminal_reason == full_error
    assert not retired.quarantined
    assert list_agent_publications("proj", include_quarantined=False) == ()

    project_dir = state_home / "projects" / "proj"
    record = ProjectRecordWire(
        schema_version=PROJECT_LIFECYCLE_WIRE_SCHEMA_VERSION,
        project_name="proj",
        project_dir=str(project_dir),
        project_file=str(project_dir / "proj.sase"),
        archive_file=None,
        workspace_dir=str(tmp_path / "primary"),
        state="enabled",
        state_explicit=False,
        system_managed=False,
        active_claim_count=0,
        launchable=True,
    )
    monkeypatch.setattr(
        "sase.doctor.checks_agent_publication.list_project_records",
        lambda *_args, **_kwargs: [record],
    )
    monkeypatch.setattr(
        "sase.doctor.checks_agent_publication.require_agent_owner_identity",
        lambda: (_ for _ in ()).throw(RuntimeError("owner unavailable")),
    )
    check = _check_agent_publication_outbox(
        DoctorContext(cwd=tmp_path, project=None, sase_home=state_home),
        now=doctor_now,
        stalled_attempts=3,
    )

    assert check.status == "WARN"
    assert "1 retired" in check.summary
    assert "sase agent sync --drop-retired" in check.summary
    assert "sase agent sync --retry-quarantined" not in check.summary
    assert "retired as unpublishable" in check.details[0]
    assert error_detail in check.details[0]
    assert check.next_steps == (
        "Run `sase agent sync --drop-retired` to drop retired requests that can never be published.",
    )

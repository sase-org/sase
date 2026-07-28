from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import time

import pytest

from sase.agents_sync import commit_publication
from sase.agents_sync.commit_publication import (
    _publish_queued_locked,
    publish_committed_agent_hood,
    refresh_committed_plan_header,
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


def test_committed_plan_header_refresh_is_idempotent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from contextlib import contextmanager

    from sase.sdd.associations import (
        PlanAgentAssociation,
        PlanAssociations,
        PlanCommitAssociation,
    )
    from sase.sdd.plan_header_block import (
        PlanHeaderSectionKind,
        parse_plan_header_block,
    )
    from sase.sdd.store import SddStore

    plans_root = tmp_path / "plans-sidecar"
    plan = plans_root / "202607" / "child.md"
    plan.parent.mkdir(parents=True)
    plan.write_text("---\ntier: tale\n---\n# Child\n", encoding="utf-8")
    store = SddStore(
        storage="sidecar_repos",
        sdd_dir=plans_root,
        repo_root=plans_root,
    )
    associations = PlanAssociations(
        agents=(
            PlanAgentAssociation(
                label="owner.host.agent",
                target="https://example.test/agent",
                sort_key="owner.host.agent",
            ),
        ),
        commits=(
            PlanCommitAssociation(
                label="abcdef0",
                target="https://example.test/commit/abcdef012345",
                trailing_text="feat: child",
                sort_key=(1, "abcdef012345"),
                sha="abcdef012345",
            ),
        ),
    )

    class _Index:
        def for_plan(self, plan_ref: str) -> PlanAssociations:
            assert plan_ref == "plans:202607/child.md"
            return associations

    @contextmanager
    def acquired_lock(*_args: object, **_kwargs: object):
        yield True

    monkeypatch.setattr(
        "sase.sdd.plan_refs.workspace_context_for_plan_resolution",
        lambda _root: (tmp_path, 1),
    )
    monkeypatch.setattr("sase.sdd.store.resolve_sdd_store", lambda *_args: store)
    monkeypatch.setattr(
        "sase.sdd.associations.build_plan_association_index",
        lambda *_args, **_kwargs: _Index(),
    )
    monkeypatch.setattr(
        "sase.sdd._git_contention.store_git_write_lock",
        acquired_lock,
    )
    monkeypatch.setattr(
        "sase.file_references.format_with_prettier",
        lambda content: content,
    )
    commits: list[Path] = []

    def commit_plan(*_args: object, **kwargs: object) -> bool:
        paths = kwargs["paths"]
        assert isinstance(paths, list)
        commits.extend(Path(path) for path in paths)
        return True

    monkeypatch.setattr("sase.sdd.files.commit_sdd_store_files", commit_plan)
    message = "feat: child\n\nSASE_PLAN=202607/child.md"

    first = refresh_committed_plan_header(message, primary_root=tmp_path)
    second = refresh_committed_plan_header(message, primary_root=tmp_path)

    assert first.changed and first.committed
    assert not second.changed and not second.committed
    assert commits == [plan]
    parsed = parse_plan_header_block(plan.read_text(encoding="utf-8"))
    assert [section.kind for section in parsed.sections] == [
        PlanHeaderSectionKind.AGENTS,
        PlanHeaderSectionKind.COMMITS,
    ]


def test_committed_plan_header_refresh_swallows_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    def fail(_root: Path) -> tuple[Path, int]:
        raise RuntimeError("plans unavailable")

    monkeypatch.setattr(
        "sase.sdd.plan_refs.workspace_context_for_plan_resolution",
        fail,
    )

    outcome = refresh_committed_plan_header(
        "feat: child\n\nSASE_PLAN=202607/child.md",
        primary_root=tmp_path,
    )

    assert outcome.error == "plans unavailable"
    assert "Could not refresh committed plan header" in caplog.text


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )


def _setup_target(tmp_path: Path) -> tuple[ProjectTarget, Path]:
    remote = tmp_path / "remote.git"
    remote.mkdir()
    _git(remote, "init", "--bare")
    seed = tmp_path / "seed"
    seed.mkdir()
    _git(seed, "init")
    _git(seed, "config", "user.name", "Tests")
    _git(seed, "config", "user.email", "tests@example.test")
    (seed / "manifest.json").write_text(
        json.dumps({"schema_version": 1, "agents": {}}) + "\n"
    )
    (seed / "agents").mkdir()
    (seed / "agents" / ".gitkeep").write_text("")
    _git(seed, "add", ".")
    _git(seed, "commit", "-m", "seed")
    _git(seed, "remote", "add", "origin", str(remote))
    _git(seed, "push", "-u", "origin", "HEAD")
    sidecar = tmp_path / "sidecar"
    _git(tmp_path, "clone", str(remote), str(sidecar))
    primary = tmp_path / "primary"
    primary.mkdir()
    return (
        ProjectTarget(
            "proj",
            "Project",
            primary,
            (primary.resolve(),),
            sidecar,
            str(remote),
        ),
        remote,
    )


def test_push_failure_is_queued_and_next_commit_drains_idempotently(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "state"))
    target, remote = _setup_target(tmp_path)
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

    def publish(_target, repo, _agent, **_kwargs):
        (repo / "README.md").write_text("# Published hood\n")
        (repo / "schema.json").write_text("{}\n")
        (repo / "families").mkdir(exist_ok=True)
        (repo / "families" / ".gitkeep").write_text("")
        manifest = V2OwnerManifest(
            owner,
            V2ProjectIdentity("proj", "Project"),
            (
                (
                    "foo",
                    V2OwnerHoodEntry("d" * 64, ("README.md",), 1, 1),
                ),
            ),
        )
        path = repo / owner_manifest_path(owner)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(v2_json_bytes(manifest.to_json_dict()))
        return V2PublicationCounts(hoods_published=1)

    monkeypatch.setattr(
        "sase.agents_sync.commit_publication.publish_agent_hood",
        publish,
    )

    def rejecting_runner(
        cwd: Path,
        args: list[str],
        *,
        network: bool = False,
        op: str = "",
    ) -> subprocess.CompletedProcess[str]:
        if args == ["push"]:
            return subprocess.CompletedProcess(args, 1, "", "permission denied")
        return run_git(cwd, args, network=network, op=op)

    first = publish_committed_agent_hood(
        "foo--code",
        "a" * 40,
        project="Project",
        git_runner=rejecting_runner,
    )

    assert first.queued and first.error
    queued = list_agent_publications("proj")
    assert len(queued) == 1
    assert queued[0].hood_digest == "d" * 64
    assert queued[0].attempts == 1

    second = publish_committed_agent_hood(
        "foo--code",
        "a" * 40,
        project="Project",
        git_runner=run_git,
    )

    assert second.published and not second.error
    assert list_agent_publications("proj") == ()
    verify = tmp_path / "verify"
    _git(tmp_path, "clone", str(remote), str(verify))
    assert (verify / "README.md").read_text() == "# Published hood\n"


def test_failed_targeted_publish_cleans_uncommitted_payload(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "state"))
    target, _remote = _setup_target(tmp_path)
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
    assert _git(target.sidecar_path, "status", "--short").stdout == ""


def test_large_backlog_builds_one_inventory_and_publishes_each_hood_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target, _remote = _setup_target(tmp_path)
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

    monkeypatch.setattr(
        commit_publication,
        "list_agent_publications",
        lambda _project_key, **_kwargs: requests,
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

    monkeypatch.setattr(
        git_sync,
        "pull_agents_rebase",
        lambda *_args, **_kwargs: subprocess.CompletedProcess([], 0, "", ""),
    )
    monkeypatch.setattr(
        git_sync,
        "commit_agents_payload_if_dirty",
        lambda *_args, **_kwargs: False,
    )
    monkeypatch.setattr(git_sync, "agents_ahead_count", lambda *_args: 0)

    started = time.perf_counter()
    result = _publish_queued_locked(target, owner, run_git)
    elapsed = time.perf_counter() - started

    assert result.error is None
    assert result.drained == len(requests)
    assert integration_calls == 1
    assert build_calls == 1
    assert [hood for hood, _inventory in published] == list(hoods)
    assert all(seen_inventory is inventory for _hood, seen_inventory in published)
    assert sorted(len(keys) for keys in updated) == [500, 500, 500, 500]
    assert acknowledged == [tuple(item.logical_key for item in requests)]
    assert elapsed < 1.0


def test_mixed_queue_publishes_good_items_and_quarantines_only_bad_item(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("SASE_AGENTS_PUBLICATION_MAX_ATTEMPTS", "2")
    target, remote = _setup_target(tmp_path)
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
    _git(tmp_path, "clone", str(remote), str(verify))
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
    target, _remote = _setup_target(tmp_path)
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

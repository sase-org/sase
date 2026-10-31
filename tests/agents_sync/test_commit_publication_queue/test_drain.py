"""Bounded drain, stranded-payload cleanup, and large-backlog inventory reuse."""

from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from sase.agents_sync import (
    _commit_publication_locked as publication_locked,
    _commit_publication_outbox as publication_outbox,
)
from sase.agents_sync.commit_publication_transaction import DrainResult
from sase.agents_sync.git import run_git
from sase.agents_sync.inventory import ProjectHoodInventory
from sase.agents_sync.models import ProjectTarget
from sase.agents_sync.publication_outbox import (
    AgentPublicationOutboxItem,
    enqueue_agent_publication,
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
from tests.agents_sync.commit_publication_fixtures import git, setup_target


def test_bounded_drain_publishes_only_the_supplied_logical_keys(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "state"))
    target, _remote = setup_target(tmp_path)
    owner = AgentOwnerIdentity("alice", "athena")
    selected = enqueue_agent_publication(
        AgentPublicationOutboxItem(
            project_key="proj",
            project="Project",
            local_agent="selected",
            global_agent="alice.athena.selected",
            primary_revision="a" * 40,
            local_hood="selected",
        )
    )
    other = enqueue_agent_publication(
        AgentPublicationOutboxItem(
            project_key="proj",
            project="Project",
            local_agent="other",
            global_agent="alice.athena.other",
            primary_revision="b" * 40,
            local_hood="other",
        )
    )
    seen: list[tuple[tuple[str, str], ...]] = []

    def publish(_target, _owner, _runner, requests, **_kwargs):
        seen.append(tuple(item.logical_key for item in requests))
        return DrainResult(drained=1)

    monkeypatch.setattr(
        "sase.agents_sync.git_sync.clean_publication_worktree",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(publication_locked, "publish_queued_transaction", publish)

    result = publication_locked.publish_queued_locked(
        target,
        owner,
        run_git,
        selected_keys=(selected.logical_key,),
    )

    assert result.drained == 1
    assert seen == [(selected.logical_key,)]
    assert other.logical_key not in seen[0]


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
        publication_locked,
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

    monkeypatch.setattr(publication_locked, "publish_agent_hood", fail_after_write)

    result = publication_locked.publish_queued_locked(target, owner, run_git)

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
        publication_outbox, "list_agent_publications", list_publications
    )

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

    monkeypatch.setattr(publication_locked, "build_project_hood_inventory", build)
    monkeypatch.setattr(publication_locked, "publish_agent_hood", publish)
    monkeypatch.setattr(
        "sase.agents_sync.publication_completion.publication_request_fulfilled",
        lambda *_args, **_kwargs: True,
    )
    monkeypatch.setattr(
        "sase.agents_sync.prompt_archive.deferred.restore_deferred_prompt_archives",
        lambda *_args, **_kwargs: {},
    )
    monkeypatch.setattr(
        publication_locked,
        "update_agent_publications",
        lambda _project_key, keys, **_kwargs: updated.append(tuple(keys)),
    )
    monkeypatch.setattr(
        publication_locked,
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

    monkeypatch.setattr(git_sync, "clean_publication_worktree", clean)
    monkeypatch.setattr(
        git_sync,
        "pull_agents_rebase",
        pull,
    )
    monkeypatch.setattr(git_sync, "commit_agents_payload_if_dirty", commit)
    monkeypatch.setattr(git_sync, "agents_ahead_count", ahead)

    result = publication_locked.publish_queued_locked(target, owner, run_git)

    assert result.error is None
    assert result.drained == 25
    assert listed == 1
    assert cleaned == 2
    assert pulled == 1
    assert commit_checks == 1
    assert ahead_checks == 1
    assert build_calls == 1
    assert len(published) == len({hood for hood, _ in published})
    assert {hood for hood, _ in published} <= set(hoods)
    assert all(seen_inventory is inventory for _hood, seen_inventory in published)
    assert sum(len(keys) for keys in updated) == 25
    assert len(acknowledged) == 1
    assert len(acknowledged[0]) == 25

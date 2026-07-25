from __future__ import annotations

import json
from pathlib import Path
import subprocess
import time

import pytest

from sase.agents_sync import commit_publication
from sase.agents_sync.commit_publication import (
    _publish_queued_locked,
    publish_committed_agent_hood,
)
from sase.agents_sync.git import run_git
from sase.agents_sync.inventory import ProjectHoodInventory
from sase.agents_sync.models import (
    IntegrationCounts,
    ProjectTarget,
    TargetSelection,
)
from sase.agents_sync.publication_outbox import (
    AgentPublicationOutboxItem,
    list_agent_publications,
)
from sase.agents_sync.v2_io import owner_manifest_path, v2_json_bytes
from sase.agents_sync.v2_models import (
    V2OwnerHoodEntry,
    V2OwnerManifest,
    V2ProjectIdentity,
    V2PublicationCounts,
)
from sase.core.agent_identity_facade import AgentOwnerIdentity


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
        lambda _project_key: requests,
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
    error = _publish_queued_locked(target, owner, run_git)
    elapsed = time.perf_counter() - started

    assert error is None
    assert integration_calls == 1
    assert build_calls == 1
    assert [hood for hood, _inventory in published] == list(hoods)
    assert all(seen_inventory is inventory for _hood, seen_inventory in published)
    assert sorted(len(keys) for keys in updated) == [500, 500, 500, 500]
    assert acknowledged == [tuple(item.logical_key for item in requests)]
    assert elapsed < 1.0

"""Remote, target, and refresh fixtures shared by the incoming-cache tests.

The incoming-cache suite is split across several ``test_incoming_cache*.py``
modules (capture/reconcile, cached integration, legacy-v1 classification) that
all build the same seeded sidecar remote and patch the same target resolution.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import subprocess

import pytest

from sase.agents_sync import incoming_integration, status
from sase.agents_sync.git import run_git
from sase.agents_sync.git_objects import LocalGitObjectReader
from sase.agents_sync.incoming_detection import capture_fetched_agent_updates
from sase.agents_sync.inventory import InventoryRun, ProjectHoodInventory
from sase.agents_sync.io import _compute_bundle_digest, atomic_write_json
from sase.agents_sync.models import (
    AgentBundle,
    AgentsManifest,
    CapturedIncomingHood,
    CommitRecord,
    ManifestEntry,
    PortableAgentMetadata,
    ProjectTarget,
    TargetSelection,
)
from sase.agents_sync.publication import publish_agent_hood
from sase.agents_sync.v2_models import V2ProjectIdentity
from sase.core.agent_identity_facade import AgentIdentitySnapshot, AgentOwnerIdentity

from tests.agents_sync.bundle_fixtures import write_bundle

PROJECT = V2ProjectIdentity("proj", "Project")
LOCAL_OWNER = AgentOwnerIdentity("alice", "athena")
FOREIGN_OWNERS = (
    AgentOwnerIdentity("alice", "zeus"),
    AgentOwnerIdentity("bob", "athena"),
)


@dataclass(frozen=True, slots=True)
class IncomingCacheStatus:
    """Test-only projection of incoming capture details after status dropped them."""

    project_key: str
    project: str
    pending_updates: tuple[CapturedIncomingHood, ...]
    validated_foreign_count: int
    exact_owner_count: int
    quarantine_diagnostics: tuple[str, ...]
    owner_v2_hoods: tuple[str, ...]

    @property
    def pending_foreign_count(self) -> int:
        return len(self.pending_updates)


@dataclass(frozen=True, slots=True)
class IncomingCacheSnapshot:
    """Test-only snapshot returned by incoming-cache capture fixtures."""

    checked_at: float
    projects: tuple[IncomingCacheStatus, ...]


def git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Run one Git command in ``cwd`` and fail the test on a non-zero exit."""

    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )


def _run(
    owner: AgentOwnerIdentity,
    *,
    suffix: str,
    chat: bytes = b"chat\n",
    hood: str = "crew",
) -> InventoryRun:
    name = f"{hood}--code"
    return InventoryRun(
        f"run-{owner.username}-{owner.machine_name}-{suffix}",
        name,
        f"{owner.username}.{owner.machine_name}.{name}",
        "completed",
        "2026-07-24T12:00:00+00:00",
        "2026-07-24T12:01:00+00:00",
        None,
        (("model", "gpt-test"),),
        (CommitRecord((suffix * 40)[:40], name, 1),),
        b"prompt\n",
        chat,
        hood,
        None,
        (),
        f"2026072412000{suffix[0]}",
        None,
        None,
    )


def publish_owner(
    target: ProjectTarget,
    owner: AgentOwnerIdentity,
    *,
    suffix: str,
    chat: bytes = b"chat\n",
    hood: str = "crew",
) -> None:
    """Publish one v2 hood snapshot for ``owner`` into ``target``'s sidecar."""

    publish_agent_hood(
        target,
        target.sidecar_path,
        f"{hood}--code",
        identity=AgentIdentitySnapshot(owner),
        inventory=ProjectHoodInventory(
            owner,
            PROJECT.key,
            (_run(owner, suffix=suffix, chat=chat, hood=hood),),
        ),
    )


def setup_v2_remote(tmp_path: Path) -> tuple[ProjectTarget, Path]:
    """Seed a remote with one local and two foreign v2 hoods.

    Returns the target whose sidecar is a fresh clone of that remote, plus the
    seed checkout used to push further commits.
    """

    primary = tmp_path / "primary"
    primary.mkdir()
    remote = tmp_path / "remote.git"
    remote.mkdir()
    git(remote, "init", "--bare")
    seed = tmp_path / "seed"
    seed.mkdir()
    seed_target = ProjectTarget(
        PROJECT.key,
        PROJECT.name,
        primary,
        (primary.resolve(),),
        seed,
        str(remote),
    )
    for index, owner in enumerate((LOCAL_OWNER, *FOREIGN_OWNERS), start=1):
        publish_owner(seed_target, owner, suffix=str(index))
    git(seed, "init")
    git(seed, "config", "user.name", "Tests")
    git(seed, "config", "user.email", "tests@example.test")
    git(seed, "add", ".")
    git(seed, "commit", "-m", "publish hoods")
    git(seed, "remote", "add", "origin", str(remote))
    git(seed, "push", "-u", "origin", "HEAD")
    sidecar = tmp_path / "sidecar"
    git(tmp_path, "clone", str(remote), str(sidecar))
    return (
        ProjectTarget(
            PROJECT.key,
            PROJECT.name,
            primary,
            (primary.resolve(),),
            sidecar,
            str(remote),
        ),
        seed,
    )


def seed_target_for(target: ProjectTarget, seed: Path) -> ProjectTarget:
    """Return ``target`` rebound to the seed checkout as its sidecar."""

    return ProjectTarget(
        PROJECT.key,
        PROJECT.name,
        target.primary_checkout,
        target.primary_roots,
        seed,
        target.remote_url,
    )


def write_legacy_group(
    repo: Path,
    *,
    machine: str,
    hood: str,
    sha: str = "d" * 40,
    timestamp: str = "20260724130000",
) -> ManifestEntry:
    """Write one legacy-v1 bundle plus the manifest that advertises it."""

    name = f"{machine}.{hood}"
    metadata = PortableAgentMetadata(name, machine, timestamp, 2)
    commits = (CommitRecord(sha, hood, 1),)
    chat = f"{hood}\n".encode()
    digest = _compute_bundle_digest(metadata, commits, chat)
    write_bundle(repo, AgentBundle(metadata, commits, chat, digest))
    entry = ManifestEntry(
        name,
        machine,
        digest,
        timestamp,
        "2026-07-24T13:00:00+00:00",
    )
    atomic_write_json(
        repo / "manifest.json",
        AgentsManifest((entry,)).to_json_dict(),
    )
    return entry


def commit_and_push(repo: Path, message: str) -> None:
    """Commit everything in ``repo`` and push it to the seeded remote."""

    git(repo, "add", ".")
    git(repo, "commit", "-m", message)
    git(repo, "push")


def patch_target(
    monkeypatch: pytest.MonkeyPatch,
    target: ProjectTarget,
) -> None:
    """Resolve every sync entry point to ``target`` owned by ``LOCAL_OWNER``."""

    selection = TargetSelection((target,), ())
    monkeypatch.setattr(status, "resolve_sync_targets", lambda _projects: selection)
    monkeypatch.setattr(
        status,
        "require_agent_owner_identity",
        lambda: LOCAL_OWNER,
    )
    monkeypatch.setattr(
        incoming_integration,
        "resolve_sync_targets",
        lambda _projects: selection,
    )
    monkeypatch.setattr(
        incoming_integration,
        "require_agent_owner_identity",
        lambda: LOCAL_OWNER,
    )


def refresh(
    target: ProjectTarget,
    *,
    network_calls: list[str],
    now: float,
) -> IncomingCacheSnapshot:
    """Capture incoming-cache evidence, recording the network ops it performs."""

    def runner(
        cwd: Path,
        args: list[str],
        *,
        network: bool = False,
        op: str = "",
    ) -> subprocess.CompletedProcess[str]:
        if network:
            network_calls.append(op)
        return run_git(cwd, args, network=network, op=op)

    fetched = runner(
        target.sidecar_path,
        ["fetch", "--prune", "origin"],
        network=True,
        op="agents_sync.status_fetch",
    )
    fetched.check_returncode()
    with LocalGitObjectReader(target.sidecar_path, git_runner=runner) as reader:
        report = capture_fetched_agent_updates(
            target,
            LOCAL_OWNER,
            reader=reader,
            now=now,
        )
    assert report is not None
    return IncomingCacheSnapshot(
        now,
        (
            IncomingCacheStatus(
                target.project_key,
                target.project,
                report.pending_updates,
                report.validated_foreign_count,
                report.exact_owner_count,
                report.diagnostics,
                report.owner_v2_hoods,
            ),
        ),
    )

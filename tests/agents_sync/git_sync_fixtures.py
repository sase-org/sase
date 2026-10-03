"""Repository builders shared by the Git-sync tests."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest

from sase.agents_sync import git_sync
from sase.agents_sync.git import run_git
from sase.agents_sync.models import CommitRecord, ProjectTarget
from sase.agents_sync.publication_validation import snapshot_path
from sase.agents_sync.v2_io import v2_json_bytes
from sase.agents_sync.v2_models import (
    V2ContainerRecord,
    V2FileReference,
    V2HoodSnapshot,
    V2ProjectIdentity,
    V2PublicationCounts,
    V2RunRecord,
)
from sase.core.agent_identity_facade import AgentOwnerIdentity
from sase.sase_agent import agent_session_page_path


def git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Run one Git command in ``cwd`` and fail on a non-zero exit."""

    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )


def setup_repo(tmp_path: Path) -> tuple[Path, Path, Path]:
    """Create a bare remote, seed checkout, and sidecar clone."""

    remote = tmp_path / "remote.git"
    remote.mkdir()
    git(remote, "init", "--bare")
    seed = tmp_path / "seed"
    seed.mkdir()
    git(seed, "init")
    git(seed, "config", "user.name", "Tests")
    git(seed, "config", "user.email", "tests@example.test")
    (seed / "manifest.json").write_text(
        json.dumps({"schema_version": 1, "agents": {}}, indent=2) + "\n"
    )
    (seed / "agents").mkdir()
    (seed / "agents" / ".gitkeep").write_text("")
    (seed / "conflict.txt").write_text("base\n")
    git(seed, "add", ".")
    git(seed, "commit", "-m", "seed")
    git(seed, "remote", "add", "origin", str(remote))
    git(seed, "push", "-u", "origin", "HEAD")
    sidecar = tmp_path / "sidecar"
    git(tmp_path, "clone", str(remote), str(sidecar))
    git(sidecar, "config", "user.name", "Tests")
    git(sidecar, "config", "user.email", "tests@example.test")
    return remote, seed, sidecar


def target(tmp_path: Path, remote: Path, sidecar: Path) -> ProjectTarget:
    """Build a project target for the temporary repositories."""

    primary = tmp_path / "primary"
    primary.mkdir(parents=True)
    return ProjectTarget(
        "proj",
        "Project",
        primary,
        (primary.resolve(),),
        sidecar,
        str(remote),
    )


def patch_payload_pass(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """Patch the integration/export pass to write a small v2 payload."""

    calls: list[int] = []

    def reconcile(
        _target: ProjectTarget,
        repo: Path,
        **_kwargs: object,
    ) -> V2PublicationCounts:
        calls.append(1)
        (repo / "README.md").write_text("# Hoods\n")
        (repo / "schema.json").write_text("{}\n")
        manifest = repo / "users" / "local" / "machines" / "athena"
        manifest.mkdir(parents=True, exist_ok=True)
        (manifest / "manifest.json").write_text("{}\n")
        bundle = repo / "agents" / "local.athena.worker"
        bundle.mkdir(parents=True, exist_ok=True)
        (bundle / "chat.md").write_text("chat\n")
        families = repo / "families"
        families.mkdir(exist_ok=True)
        (families / ".gitkeep").write_text("")
        sessions = repo / "sessions"
        sessions.mkdir(exist_ok=True)
        (sessions / ".gitkeep").write_text("")
        return V2PublicationCounts(hoods_published=1, runs_published=1)

    monkeypatch.setattr(git_sync, "reconcile_agent_hoods", reconcile)
    return calls


def plant_fulfilled_publication(
    sidecar: Path,
    *,
    owner: AgentOwnerIdentity | None = None,
    local_agent: str = "foo",
    global_agent: str = "alice.athena.foo",
    revision: str = "a" * 40,
    extra_revisions: tuple[str, ...] = (),
    local_hood: str = "foo",
    kind: str = "run",
    has_prompt_file: bool = False,
    source_run_id: str = "run-1",
) -> None:
    """Write the canonical page and snapshot identity a request needs."""

    resolved_owner = owner or AgentOwnerIdentity("alice", "athena")
    shas = (revision, *extra_revisions)
    commits = tuple(
        CommitRecord(sha, f"publish {local_agent}", index)
        for index, sha in enumerate(shas, start=1)
    )
    files: tuple[tuple[str, V2FileReference], ...] = ()
    if has_prompt_file:
        files = (
            (
                "prompt",
                V2FileReference(
                    f"agents/{global_agent}/prompt.md",
                    "a" * 64,
                    12,
                ),
            ),
        )
    if kind == "session":
        member_local = f"{local_agent}--code"
        member_global = f"{global_agent}--code"
        run = V2RunRecord(
            source_run_id,
            member_local,
            member_global,
            "completed",
            commits=commits,
            files=files,
        )
        snapshot = V2HoodSnapshot(
            resolved_owner,
            V2ProjectIdentity("proj", "Project"),
            local_hood,
            f"{resolved_owner.username}.{resolved_owner.machine_name}.{local_hood}",
            runs=(run,),
            containers=(
                V2ContainerRecord(
                    "session",
                    global_agent,
                    (source_run_id,),
                    commits,
                ),
            ),
        )
        page = sidecar / agent_session_page_path(global_agent)
    else:
        run = V2RunRecord(
            source_run_id,
            local_agent,
            global_agent,
            "completed",
            commits=commits,
            files=files,
        )
        snapshot = V2HoodSnapshot(
            resolved_owner,
            V2ProjectIdentity("proj", "Project"),
            local_hood,
            f"{resolved_owner.username}.{resolved_owner.machine_name}.{local_hood}",
            (f"{resolved_owner.username}.{resolved_owner.machine_name}.{local_hood}",),
            (run,),
        )
        page = sidecar / "agents" / global_agent / "README.md"
    page.parent.mkdir(parents=True, exist_ok=True)
    page.write_text(f"# {local_agent}\n", encoding="utf-8")
    snapshot_file = sidecar / snapshot_path(resolved_owner, local_hood)
    snapshot_file.parent.mkdir(parents=True, exist_ok=True)
    snapshot_file.write_bytes(v2_json_bytes(snapshot.to_json_dict()))

"""Repository builders shared by the Git-sync tests."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest

from sase.agents_sync import git_sync
from sase.agents_sync.git import run_git
from sase.agents_sync.models import IntegrationCounts, ProjectTarget
from sase.agents_sync.v2_models import V2PublicationCounts


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
    monkeypatch.setattr(
        git_sync,
        "integrate_agent_imports_with_receipts",
        lambda *_args, **_kwargs: IntegrationCounts(),
    )

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
        return V2PublicationCounts(hoods_published=1, runs_published=1)

    monkeypatch.setattr(git_sync, "reconcile_agent_hoods", reconcile)
    return calls

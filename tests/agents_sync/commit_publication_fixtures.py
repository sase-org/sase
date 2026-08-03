from __future__ import annotations

import json
from pathlib import Path
import subprocess

from sase.agents_sync.commit_publication import (
    _CommitPublicationOutcome,
    drain_agent_publications,
    enqueue_committed_agent_publication,
    resolve_sidecar_publication_target,
)
from sase.agents_sync.git import GitRunner, run_git
from sase.agents_sync.models import ProjectTarget


def publish_committed_agent_hood(
    local_agent: str,
    primary_revision: str,
    *,
    project: str | None = None,
    commit_cwd: Path | str | None = None,
    git_runner: GitRunner = run_git,
    lock_timeout_seconds: float | None = None,
) -> _CommitPublicationOutcome:
    """Exercise the explicit enqueue and manual-drain APIs as one test action."""

    outcome = enqueue_committed_agent_publication(
        local_agent,
        primary_revision,
        project=project,
        commit_cwd=commit_cwd,
        git_runner=git_runner,
    )
    if outcome.error is not None or outcome.skip_reason is not None:
        return outcome
    target, _error = resolve_sidecar_publication_target(
        project=project,
        commit_cwd=commit_cwd,
    )
    if target is None:
        return outcome
    return drain_agent_publications(
        target.project_key,
        git_runner=git_runner,
        lock_timeout_seconds=lock_timeout_seconds,
    )


def git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )


def setup_target(tmp_path: Path) -> tuple[ProjectTarget, Path]:
    remote = tmp_path / "remote.git"
    remote.mkdir()
    git(remote, "init", "--bare")
    seed = tmp_path / "seed"
    seed.mkdir()
    git(seed, "init")
    git(seed, "config", "user.name", "Tests")
    git(seed, "config", "user.email", "tests@example.test")
    (seed / "manifest.json").write_text(
        json.dumps({"schema_version": 1, "agents": {}}) + "\n"
    )
    (seed / "agents").mkdir()
    (seed / "agents" / ".gitkeep").write_text("")
    git(seed, "add", ".")
    git(seed, "commit", "-m", "seed")
    git(seed, "remote", "add", "origin", str(remote))
    git(seed, "push", "-u", "origin", "HEAD")
    sidecar = tmp_path / "sidecar"
    git(tmp_path, "clone", str(remote), str(sidecar))
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

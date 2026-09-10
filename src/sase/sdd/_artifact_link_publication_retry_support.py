"""Git probes and deadline helpers for artifact-link publication retry."""

from __future__ import annotations

from pathlib import Path
from typing import Any
import os
import subprocess
import time

from sase.core.artifact_link_publication_retry import (
    artifact_link_publication_record_key,
    artifact_link_publication_state_wire_schema_version,
)
from sase.sdd._artifact_link_machine_store import MachineArtifactLinkRoot

_LOCAL_GIT_TIMEOUT_SECONDS = 10.0


def deadline_expired(deadline: float | None) -> bool:
    return deadline is not None and time.monotonic() >= deadline


def deadline_remaining(deadline: float | None) -> float | None:
    if deadline is None:
        return None
    return max(0.0, deadline - time.monotonic())


def bounded_timeout(default: float, deadline: float | None) -> float:
    if deadline is None:
        return max(0.0, default)
    remaining = deadline_remaining(deadline)
    assert remaining is not None
    return min(max(0.0, default), remaining)


def wall_now(value: float | None) -> float:
    return float(time.time() if value is None else value)


def publication_observation(
    root: MachineArtifactLinkRoot, now: float, *, deadline: float | None = None
) -> tuple[dict[str, Any] | None, str | None]:
    repo_root = root.repo_root.expanduser().resolve(strict=False)
    if not (repo_root / ".git").is_dir():
        return None, f"{repo_root} is not a git worktree"
    upstream = _tracking_upstream(repo_root, deadline=deadline)
    if upstream is None:
        return None, "sidecar repository has no tracking upstream"
    head_revision = _git_text(repo_root, ["rev-parse", "HEAD"], deadline=deadline)
    if head_revision is None:
        return None, "could not read sidecar HEAD"
    return (
        {
            "version": artifact_link_publication_state_wire_schema_version(),
            "project_key": root.project_key,
            "role": root.role,
            "repo_root": str(repo_root),
            "remote_url": root.remote_url,
            "upstream": upstream,
            "head_revision": head_revision,
            "oldest_unpublished_at": _oldest_unpublished_commit_time(
                repo_root, upstream, deadline=deadline
            )
            or now,
            "key": artifact_link_publication_record_key(
                project_key=root.project_key,
                role=root.role,
                repo_root=str(repo_root),
                remote_url=root.remote_url,
                upstream=upstream,
            ),
        },
        None,
    )


def head_is_published(repo_root: Path, *, deadline: float | None = None) -> bool:
    result = _git_result(
        repo_root,
        ["merge-base", "--is-ancestor", "HEAD", "@{upstream}"],
        deadline=deadline,
    )
    return result is not None and result.returncode == 0


def retry_mutation_blocker(
    repo_root: Path, *, deadline: float | None = None
) -> str | None:
    status = _git_result(
        repo_root,
        ["status", "--porcelain=v1", "-z", "--untracked-files=all"],
        deadline=deadline,
    )
    if status is None or status.returncode != 0:
        return "could not inspect sidecar worktree status"
    if status.stdout:
        return "sidecar repository has uncommitted or untracked changes"
    return None


def _git_text(
    repo_root: Path, args: list[str], *, deadline: float | None = None
) -> str | None:
    result = _git_result(repo_root, args, deadline=deadline)
    if result is None or result.returncode != 0:
        return None
    return result.stdout.strip() or None


def _tracking_upstream(repo_root: Path, *, deadline: float | None = None) -> str | None:
    return _git_text(
        repo_root,
        ["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"],
        deadline=deadline,
    )


def _oldest_unpublished_commit_time(
    repo_root: Path, upstream: str, *, deadline: float | None = None
) -> float | None:
    output = _git_text(
        repo_root,
        ["log", "--format=%ct", "--reverse", f"{upstream}..HEAD"],
        deadline=deadline,
    )
    if not output:
        return None
    first = output.splitlines()[0].strip()
    try:
        return float(int(first))
    except ValueError:
        return None


def _git_result(
    repo_root: Path, args: list[str], *, deadline: float | None = None
) -> subprocess.CompletedProcess[str] | None:
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    timeout = bounded_timeout(_LOCAL_GIT_TIMEOUT_SECONDS, deadline)
    if timeout <= 0.0:
        return None
    try:
        return subprocess.run(
            ["git", *args],
            cwd=repo_root,
            env=env,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None

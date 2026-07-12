"""Managed one-shot integration worker for companion bead stores."""

from __future__ import annotations

import fcntl
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class _ManagedSyncOutcome:
    """Terminal result from one managed fetch/rebase/push attempt."""

    pushed: bool
    integrated: bool
    skipped_locked: bool = False
    error: str | None = None


def run_managed_sync_worker(
    repo_root: Path,
    beads_dir: Path,
    *,
    log_path: Path,
) -> _ManagedSyncOutcome:
    """Fetch, rebase with bead conflict repair, and push without prompting."""
    repo_root = repo_root.expanduser().resolve()
    beads_dir = beads_dir.expanduser().resolve()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = _git_dir(repo_root) / "sase-bead-sync.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "a+", encoding="utf-8") as lock_file:
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            outcome = _ManagedSyncOutcome(
                pushed=False,
                integrated=False,
                skipped_locked=True,
            )
            _log(log_path, "skipped", reason="worker_already_running")
            return outcome

        try:
            return _run_locked_sync(repo_root, beads_dir, log_path)
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _run_locked_sync(
    repo_root: Path, beads_dir: Path, log_path: Path
) -> _ManagedSyncOutcome:
    os.environ["GIT_TERMINAL_PROMPT"] = "0"
    _log(log_path, "started", repo_root=str(repo_root), beads_dir=str(beads_dir))

    fetched = _git(
        repo_root,
        ["fetch", "--prune", "origin"],
        op="bead.sync.fetch",
        network=True,
    )
    if fetched.returncode != 0:
        return _failure(log_path, "git fetch failed", fetched)

    upstream = _git(
        repo_root,
        ["rev-parse", "--verify", "@{upstream}"],
        op="bead.sync.upstream",
    )
    integrated = False
    if upstream.returncode == 0:
        already_integrated = _git(
            repo_root,
            ["merge-base", "--is-ancestor", "@{upstream}", "HEAD"],
            op="bead.sync.ancestor",
        )
        if already_integrated.returncode != 0:
            dirty = _git(
                repo_root,
                ["status", "--porcelain"],
                op="bead.sync.status",
            )
            if dirty.returncode != 0:
                return _failure(log_path, "git status failed", dirty)
            if dirty.stdout.strip():
                return _failure(
                    log_path,
                    "bead store needs integration but has uncommitted changes",
                )
            rebased = _git(
                repo_root,
                ["rebase", "@{upstream}"],
                op="bead.sync.rebase",
            )
            if rebased.returncode != 0:
                repaired = _repair_rebase(repo_root, beads_dir, log_path)
                if repaired is not None:
                    return repaired
        integrated = True
        from sase.bead.sync import mark_bead_integration

        mark_bead_integration(repo_root)

    pushed = _git(
        repo_root,
        ["push"],
        op="bead.sync.push",
        network=True,
    )
    if pushed.returncode != 0:
        return _failure(log_path, "git push failed", pushed, integrated=integrated)

    _log(log_path, "completed", pushed=True, integrated=integrated)
    return _ManagedSyncOutcome(pushed=True, integrated=integrated)


def _repair_rebase(
    repo_root: Path, beads_dir: Path, log_path: Path
) -> _ManagedSyncOutcome | None:
    from sase.bead.conflict_resolver import resolve_bead_conflicts

    for _ in range(100):
        resolution = resolve_bead_conflicts(repo_root, beads_dir=beads_dir)
        _log(
            log_path,
            "conflict_resolution",
            ok=resolution.ok,
            message=resolution.message,
            resolved_files=list(resolution.resolved_files),
        )
        if not resolution.ok:
            return _abort_rebase(repo_root, log_path, resolution.message)

        continued = _git(
            repo_root,
            ["-c", "core.editor=true", "rebase", "--continue"],
            op="bead.sync.rebase_continue",
        )
        if continued.returncode == 0:
            return None
        conflicts = _git(
            repo_root,
            ["diff", "--name-only", "--diff-filter=U"],
            op="bead.sync.conflicts",
        )
        if conflicts.returncode != 0 or not conflicts.stdout.strip():
            return _abort_rebase(
                repo_root,
                log_path,
                _git_error("git rebase --continue failed", continued),
            )
    return _abort_rebase(repo_root, log_path, "too many rebase conflict rounds")


def _abort_rebase(repo_root: Path, log_path: Path, reason: str) -> _ManagedSyncOutcome:
    aborted = _git(
        repo_root,
        ["rebase", "--abort"],
        op="bead.sync.rebase_abort",
    )
    suffix = ""
    if aborted.returncode != 0:
        suffix = "; git rebase --abort also failed"
    return _failure(log_path, f"{reason}{suffix}")


def _failure(
    log_path: Path,
    message: str,
    result: subprocess.CompletedProcess[str] | None = None,
    *,
    integrated: bool = False,
) -> _ManagedSyncOutcome:
    error = _git_error(message, result) if result is not None else message
    _log(log_path, "failed", error=error, integrated=integrated)
    return _ManagedSyncOutcome(
        pushed=False,
        integrated=integrated,
        error=error,
    )


def _git_error(message: str, result: subprocess.CompletedProcess[str]) -> str:
    detail = (result.stderr or result.stdout or "").strip()
    if detail:
        return f"{message}: {detail}"
    return f"{message} with exit code {result.returncode}"


def _git(
    repo_root: Path,
    args: list[str],
    *,
    op: str,
    network: bool = False,
) -> subprocess.CompletedProcess[str]:
    from sase.sdd._git import (
        SddGitCommandTimeout,
        network_git_timeout,
        run_sdd_git,
    )

    try:
        return run_sdd_git(
            args,
            cwd=repo_root,
            op=op,
            timeout=network_git_timeout() if network else None,
            check=False,
            capture_output=True,
            text=True,
        )
    except (OSError, SddGitCommandTimeout) as exc:
        return subprocess.CompletedProcess(
            ["git", *args],
            returncode=124,
            stdout="",
            stderr=str(exc),
        )


def _git_dir(repo_root: Path) -> Path:
    result = subprocess.run(
        ["git", "rev-parse", "--git-dir"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    path = Path(result.stdout.strip()) if result.returncode == 0 else Path(".git")
    return path if path.is_absolute() else repo_root / path


def _log(log_path: Path, event: str, **fields: Any) -> None:
    record = {"ts": time.time(), "event": event, **fields}
    with open(log_path, "a", encoding="utf-8") as log_file:
        log_file.write(json.dumps(record, sort_keys=True) + "\n")


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 3:
        return 2
    outcome = run_managed_sync_worker(
        Path(args[0]),
        Path(args[1]),
        log_path=Path(args[2]),
    )
    return 0 if outcome.pushed or outcome.skipped_locked else 1


if __name__ == "__main__":
    raise SystemExit(main())

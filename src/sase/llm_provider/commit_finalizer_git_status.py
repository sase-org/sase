"""Git subprocess primitives and working-tree status queries.

Every read-only query here runs ``subprocess.run`` directly. Mutating
operations (add, commit, reset) funnel through :func:`run_git`, which retries
around a contended ``index.lock``.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from sase.git_lock_retry import run_with_git_lock_retry

from .commit_finalizer_git_paths import (
    is_sase_reserved_status_path,
    normalize_path,
    normalize_status_path,
)

_GIT_TIMEOUT_SECONDS = 5

UNKNOWN_HEAD_SENTINEL = "<unknown-head>"


@dataclass(frozen=True)
class GitStatusRecord:
    """One ``git status --porcelain=v1`` entry: its ``XY`` code and path."""

    xy: str
    path: str


def run_git(
    repo_dir: str,
    args: list[str],
    *,
    timeout: int = _GIT_TIMEOUT_SECONDS,
) -> subprocess.CompletedProcess[str] | None:
    """Run a mutating git command, retrying around a contended index lock."""

    try:
        result, _outcome = run_with_git_lock_retry(
            lambda: subprocess.run(
                ["git", "-C", repo_dir, *args],
                capture_output=True,
                text=True,
                check=False,
                timeout=timeout,
            ),
            cwd=repo_dir,
        )
        return result
    except Exception:
        return None


def git_changed_files(repo_dir: str) -> list[str]:
    repo_dir = normalize_path(repo_dir)
    if not Path(repo_dir).is_dir():
        return []
    try:
        result = subprocess.run(
            [
                "git",
                "-C",
                repo_dir,
                "status",
                "--porcelain=v1",
                "--untracked-files=all",
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=20,
        )
    except Exception:
        return []
    if result.returncode != 0:
        return []
    return changed_files_from_git_status(result.stdout)


def changed_files_from_git_status(status_text: str) -> list[str]:
    """Parse porcelain status output, dropping SASE-reserved metadata paths."""

    changed: list[str] = []
    for raw_line in status_text.splitlines():
        line = raw_line.rstrip()
        if not line:
            continue
        path = line[3:] if len(line) > 3 else line
        is_rename = len(line) >= 2 and bool({"R", "C"} & set(line[:2]))
        if is_sase_reserved_status_path(path, is_rename=is_rename):
            continue
        changed.append(path)
    return changed


def git_status_records(repo_dir: str) -> list[GitStatusRecord]:
    """Return every porcelain status entry, or ``[]`` when git is unusable."""

    try:
        result = subprocess.run(
            [
                "git",
                "-C",
                repo_dir,
                "status",
                "--porcelain=v1",
                "--untracked-files=all",
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=_GIT_TIMEOUT_SECONDS,
        )
    except Exception:
        return []
    if result.returncode != 0:
        return []

    records: list[GitStatusRecord] = []
    for raw_line in result.stdout.splitlines():
        line = raw_line.rstrip()
        if len(line) < 4:
            return []
        records.append(GitStatusRecord(xy=line[:2], path=line[3:]))
    return records


def dirty_path_fingerprints(repo_dir: str) -> dict[str, tuple[str, str | None]]:
    """Map each currently dirty path in *repo_dir* to an ``(xy, content_hash)`` pair.

    Used to compare a run-start baseline against the live worktree: a path is
    provably unchanged since the baseline only when both its git status code
    and its content hash still match.
    """
    repo_dir = normalize_path(repo_dir)
    fingerprints: dict[str, tuple[str, str | None]] = {}
    for record in git_status_records(repo_dir):
        key = normalize_status_path(record.path)
        fingerprints[key] = (record.xy, _git_hash_object(repo_dir, key))
    return fingerprints


def split_pre_existing_changed_files(
    repo_dir: str,
    changed_files: list[str],
    baseline_fingerprints: dict[str, tuple[str, str | None]] | None,
) -> tuple[list[str], list[str]]:
    """Split *changed_files* into (still relevant, unchanged-since-baseline).

    A path that was dirty at baseline and has since been edited again keeps
    its current status/hash and so stays on the "still relevant" side.
    """
    if not baseline_fingerprints:
        return list(changed_files), []

    current_fingerprints: dict[str, tuple[str, str | None]] | None = None
    still: list[str] = []
    pre_existing: list[str] = []
    for entry in changed_files:
        key = normalize_status_path(entry)
        baseline_fp = baseline_fingerprints.get(key)
        if baseline_fp is None:
            still.append(entry)
            continue
        if current_fingerprints is None:
            current_fingerprints = dirty_path_fingerprints(repo_dir)
        if current_fingerprints.get(key) == tuple(baseline_fp):
            pre_existing.append(entry)
        else:
            still.append(entry)
    return still, pre_existing


def git_head_commit_id(repo_dir: str) -> str:
    """Return *repo_dir*'s HEAD commit id, or the unknown-head sentinel."""

    try:
        result = subprocess.run(
            ["git", "-C", repo_dir, "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
            timeout=_GIT_TIMEOUT_SECONDS,
        )
    except Exception:
        return UNKNOWN_HEAD_SENTINEL
    if result.returncode != 0:
        return UNKNOWN_HEAD_SENTINEL
    return result.stdout.strip() or UNKNOWN_HEAD_SENTINEL


def git_upstream_ahead_count(repo_dir: str) -> int | None:
    """Return how many commits ``HEAD`` is ahead of its upstream.

    ``None`` means the repo has no configured upstream (or the lookup
    failed), distinguishing "no upstream to compare against" from "zero
    commits ahead."
    """
    try:
        result = subprocess.run(
            ["git", "-C", repo_dir, "rev-list", "--count", "@{upstream}..HEAD"],
            capture_output=True,
            text=True,
            check=False,
            timeout=_GIT_TIMEOUT_SECONDS,
        )
    except Exception:
        return None
    if result.returncode != 0:
        return None
    text = result.stdout.strip()
    if not text.isdigit():
        return None
    return int(text)


def git_log_commit_messages(repo_dir: str, revision: str) -> tuple[str, ...]:
    """Return the full messages of *revision*, oldest first."""

    try:
        result = subprocess.run(
            ["git", "-C", repo_dir, "log", "--reverse", "-z", "--format=%B", revision],
            capture_output=True,
            text=True,
            check=False,
            timeout=_GIT_TIMEOUT_SECONDS,
        )
    except Exception:
        return ()
    if result.returncode != 0:
        return ()
    return tuple(message for message in result.stdout.split("\0") if message.strip())


def git_show_head_file(repo_dir: str, path: str) -> str | None:
    """Return *path*'s content at HEAD, or ``None`` when it cannot be read."""

    try:
        result = subprocess.run(
            ["git", "-C", repo_dir, "show", f"HEAD:{path}"],
            capture_output=True,
            text=True,
            check=False,
            timeout=_GIT_TIMEOUT_SECONDS,
        )
    except Exception:
        return None
    if result.returncode != 0:
        return None
    return result.stdout


def _git_hash_object(repo_dir: str, rel_path: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", repo_dir, "hash-object", "--", rel_path],
            capture_output=True,
            text=True,
            check=False,
            timeout=_GIT_TIMEOUT_SECONDS,
        )
    except Exception:
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None

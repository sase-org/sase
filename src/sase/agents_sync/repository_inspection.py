"""Repository and marker inspection helpers for agents-sidecar publication."""

from __future__ import annotations

from collections.abc import Mapping
import json
from pathlib import Path
from typing import Any

from sase._interruptions import PublicationDrainTimedOut
from sase.agents_sync.git import GitRunner
from sase.agents_sync.models import CommitRecord, ProjectTarget

CommitRecordCache = dict[tuple[str, str], CommitRecord | None]


def commit_markers(artifact_dir: Path) -> list[dict[str, Any]]:
    """Return commit marker dictionaries stored in an agent artifact dir."""
    results = _read_json(artifact_dir / "commit_results.json")
    if isinstance(results, list):
        return [item for item in results if isinstance(item, dict)]
    result = _read_json_object(artifact_dir / "commit_result.json")
    return [result] if result is not None else []


def repository_root(
    cwd: Path,
    git_runner: GitRunner,
    cache: dict[str, Path | None],
) -> Path | None:
    """Resolve and cache the Git worktree root for *cwd*."""
    key = str(cwd.expanduser().resolve(strict=False))
    if key in cache:
        return cache[key]
    if not cwd.is_dir():
        cache[key] = None
        return None
    result = git_runner(
        cwd,
        ["rev-parse", "--show-toplevel"],
        op="agents_sync.primary_root",
    )
    root = (
        Path(result.stdout.strip()).resolve(strict=False)
        if result.returncode == 0 and result.stdout.strip()
        else None
    )
    cache[key] = root
    return root


def is_primary_root(root: Path, target: ProjectTarget) -> bool:
    """Return whether *root* is one of the target's configured primary roots."""
    normalized = root.resolve(strict=False)
    return any(normalized == candidate for candidate in target.primary_roots)


def commit_record(
    repo_root: Path,
    sha: str,
    git_runner: GitRunner,
    *,
    cache: CommitRecordCache | None = None,
    known: Mapping[str, CommitRecord] | None = None,
) -> CommitRecord | None:
    """Load the normalized SHA, subject, and commit time for *sha*.

    *known* reuses batched primary-history records. *cache* stores per
    ``(repository, sha)`` lookups for the rest of one drain so repeated
    marker SHAs and aliased worktree roots do not spawn extra Git calls.
    """
    root_key = str(repo_root.resolve(strict=False))
    needle = sha.strip().lower()
    cache_key = (root_key, needle)
    if cache is not None and cache_key in cache:
        return cache[cache_key]
    known_record = _known_commit(needle, known)
    if known_record is not None:
        _remember_commit(cache, root_key, needle, known_record)
        return known_record
    record = _load_commit_record(repo_root, sha, git_runner)
    _remember_commit(cache, root_key, needle, record)
    return record


def _known_commit(
    sha: str, known: Mapping[str, CommitRecord] | None
) -> CommitRecord | None:
    if not known:
        return None
    exact = known.get(sha)
    if exact is not None:
        return exact
    if 7 <= len(sha) < 40:
        matches = [item for full, item in known.items() if full.startswith(sha)]
        if len(matches) == 1:
            return matches[0]
    return None


def _remember_commit(
    cache: CommitRecordCache | None,
    root_key: str,
    sha: str,
    record: CommitRecord | None,
) -> None:
    if cache is None:
        return
    cache[(root_key, sha)] = record
    if record is not None:
        cache[(root_key, record.sha)] = record


def _load_commit_record(
    repo_root: Path, sha: str, git_runner: GitRunner
) -> CommitRecord | None:
    result = git_runner(
        repo_root,
        ["show", "-s", "--format=%ct%x00%s", sha],
        op="agents_sync.commit_record",
    )
    if result.returncode != 0:
        return None
    pieces = result.stdout.rstrip("\n").split("\x00", 1)
    if len(pieces) != 2:
        return None
    try:
        committed_at = int(pieces[0])
    except ValueError:
        return None
    normalized_sha = _resolve_sha(repo_root, sha, git_runner)
    if normalized_sha is None:
        return None
    return CommitRecord(normalized_sha, pieces[1], committed_at)


def _resolve_sha(repo_root: Path, sha: str, git_runner: GitRunner) -> str | None:
    result = git_runner(
        repo_root,
        ["rev-parse", "--verify", f"{sha}^{{commit}}"],
        op="agents_sync.resolve_sha",
    )
    value = result.stdout.strip().lower()
    return value if result.returncode == 0 and value else None


def _read_json(path: Path) -> object | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except PublicationDrainTimedOut:
        raise
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None


def _read_json_object(path: Path) -> dict[str, Any] | None:
    value = _read_json(path)
    return value if isinstance(value, dict) else None


__all__ = [
    "CommitRecordCache",
    "commit_markers",
    "commit_record",
    "is_primary_root",
    "repository_root",
]

"""Bounded reaper for the managed SASE temp root.

:func:`sase.core.paths.get_sase_managed_tmpdir` documents its root as reapable,
but nothing reaped it, so relocating handoff scratch out of the system temp dir
only moved the pile.  This module bounds it.

Two rules keep the reaper safe next to live commands:

* Only the *children* of a known managed subdirectory are pruned; the
  subdirectory itself is a stable, concurrently-created mount point.
* Staleness is decided from ``st_mtime`` alone, without following symlinks, and
  every :class:`OSError` is swallowed — losing a race with a running command is
  a no-op, not a failure.

Horizons are per subdirectory rather than global, because the lifetimes differ
by two orders of magnitude: an editor's scratch file dies with the editor, while
``workflow-artifacts/`` holds the artifact directory the ACE Agents tab reads
back for as long as the run is worth looking at.
"""

from __future__ import annotations

import shutil
import stat
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from sase.core.paths import managed_tmpdir_root


_HOUR = 3600.0
_DAY = 24 * _HOUR

COMMAND_SCRATCH_HORIZON_SECONDS = 12 * _HOUR
"""Scratch that dies with the command that created it (editors, wrappers)."""

HANDOFF_HORIZON_SECONDS = 3 * _DAY
"""Files handed to a child process that may re-read them mid-run."""

RUN_ARTIFACT_HORIZON_SECONDS = 14 * _DAY
"""Artifacts the ACE Agents tab reads back long after the run finished."""

DEFAULT_HORIZON_SECONDS = HANDOFF_HORIZON_SECONDS
"""Horizon for unrecognized subdirectories and stray top-level entries.

Nothing writes directly into the bare root any more, so anything found there is
either pre-``sase-96`` residue or a subdirectory added after this table.  Both
are safe to bound at the handoff horizon.
"""

MANAGED_TMPDIR_HORIZONS: Mapping[str, float] = {
    # Scratch whose reader is the command that wrote it.
    "ace-profiles": COMMAND_SCRATCH_HORIZON_SECONDS,
    "agent-clis": COMMAND_SCRATCH_HORIZON_SECONDS,
    "artifact-pages": COMMAND_SCRATCH_HORIZON_SECONDS,
    "commit-messages": COMMAND_SCRATCH_HORIZON_SECONDS,
    "editors": COMMAND_SCRATCH_HORIZON_SECONDS,
    "embedded-artifacts": COMMAND_SCRATCH_HORIZON_SECONDS,
    "viewers": COMMAND_SCRATCH_HORIZON_SECONDS,
    "workflow-loader": COMMAND_SCRATCH_HORIZON_SECONDS,
    "wrappers": COMMAND_SCRATCH_HORIZON_SECONDS,
    "xprompts_catalog": COMMAND_SCRATCH_HORIZON_SECONDS,
    # Handoff files a launched process owns for the length of its run.
    "gh-diffs": HANDOFF_HORIZON_SECONDS,
    "handoff": HANDOFF_HORIZON_SECONDS,
    # Read back by the ACE Agents tab well after the run itself ended.
    "launch-prompts": RUN_ARTIFACT_HORIZON_SECONDS,
    "workflow-artifacts": RUN_ARTIFACT_HORIZON_SECONDS,
}
"""Per-subdirectory horizons, keyed by the ``get_sase_managed_tmpdir`` part."""

DEFAULT_MAX_REMOVALS = 2000
"""Removal budget for one invocation.

The measured root held 94k entries, enough that a single unbounded first pass
would run for minutes.  Capping removals rather than the scan keeps each
invocation's worst case bounded while still converging over a few runs.
"""


@dataclass(frozen=True)
class _ManagedTmpReapResult:
    """What one reaper invocation looked at and reclaimed."""

    root: Path
    scanned: int
    removed: int
    removed_by_subdir: Mapping[str, int]
    deindexed: int
    capped: bool

    def describe(self) -> str:
        """Return a one-line human summary of the largest buckets pruned."""
        if not self.removed:
            return f"nothing stale under {self.root}"
        busiest = sorted(
            self.removed_by_subdir.items(), key=lambda item: (-item[1], item[0])
        )
        detail = ", ".join(f"{name}={count}" for name, count in busiest)
        if self.deindexed:
            detail += f"; {self.deindexed} artifact-index rows dropped"
        suffix = " (removal budget reached)" if self.capped else ""
        return f"reclaimed {self.removed} entries under {self.root}: {detail}{suffix}"


_TOP_LEVEL_BUCKET = "<root>"
"""Bucket name for stray entries sitting directly in the managed root."""

_UNSAFE_REAP_ROOTS = frozenset(
    Path(path).resolve() for path in ("/", "/tmp", "/var/tmp")
)
"""Resolved broad roots whose children can never all be assumed disposable."""


def reap_managed_tmpdir(
    root: Path | None = None,
    *,
    now: float | None = None,
    horizons: Mapping[str, float] = MANAGED_TMPDIR_HORIZONS,
    default_horizon_seconds: float = DEFAULT_HORIZON_SECONDS,
    max_removals: int = DEFAULT_MAX_REMOVALS,
) -> _ManagedTmpReapResult:
    """Prune stale entries under the managed SASE temp *root*.

    Known subdirectories are descended into and pruned against their own
    horizon; the subdirectory itself always survives.  Anything else at the top
    level is pruned against *default_horizon_seconds*.  Stops once
    *max_removals* entries have been removed, so a long-neglected root
    converges across invocations instead of stalling one of them.
    """
    reap_root = _validated_reap_root(managed_tmpdir_root() if root is None else root)
    clock = time.time() if now is None else now

    scanned = 0
    removed_by_subdir: dict[str, int] = {}
    removed_directories: list[Path] = []
    budget = max_removals
    capped = False

    for entry in _iter_children(reap_root):
        if budget <= 0:
            capped = True
            break
        horizon = horizons.get(entry.name)
        if horizon is not None and entry.is_dir() and not entry.is_symlink():
            candidates = [
                (child, clock - horizon, entry.name) for child in _iter_children(entry)
            ]
        else:
            candidates = [(entry, clock - default_horizon_seconds, _TOP_LEVEL_BUCKET)]

        for candidate, cutoff, bucket in candidates:
            if budget <= 0:
                capped = True
                break
            scanned += 1
            kind = _remove_if_stale(candidate, cutoff)
            if kind is None:
                continue
            if kind == "directory":
                removed_directories.append(candidate)
            removed_by_subdir[bucket] = removed_by_subdir.get(bucket, 0) + 1
            budget -= 1

    deindexed = 0
    if removed_directories:
        # A reaped directory may have been an agent's artifacts_dir — workflows
        # launched without an explicit one land in ``workflow-artifacts/`` — so
        # drop its index rows rather than leave the Agents tab pointing at a
        # directory that no longer exists.
        from sase.core.agent_artifact_index_lifecycle_mutations import (
            delete_agent_artifact_index_artifacts,
        )

        deindexed = delete_agent_artifact_index_artifacts(removed_directories)

    return _ManagedTmpReapResult(
        root=reap_root,
        scanned=scanned,
        removed=sum(removed_by_subdir.values()),
        removed_by_subdir=removed_by_subdir,
        deindexed=deindexed,
        capped=capped,
    )


def _validated_reap_root(root: Path) -> Path:
    """Reject broad roots whose children cannot all be assumed disposable."""
    resolved = root.expanduser().resolve()
    cwd = Path.cwd().resolve()
    if resolved in _UNSAFE_REAP_ROOTS or (resolved == cwd or resolved in cwd.parents):
        raise ValueError(
            f"managed SASE temp root must be a dedicated directory, not {resolved}"
        )
    return resolved


def _iter_children(directory: Path) -> list[Path]:
    """Return *directory*'s entries, or an empty list if it cannot be listed."""
    try:
        return list(directory.iterdir())
    except OSError:
        return []


def _remove_if_stale(path: Path, cutoff: float) -> str | None:
    """Remove *path* when it is a plain file or directory older than *cutoff*.

    Returns ``"directory"``, ``"file"``, or ``None`` when nothing was removed,
    so the caller can de-index the directories it reaped.  Symlinks are never
    followed and never removed: the reaper owns the scratch it can identify,
    not whatever a link happens to point at.
    """
    try:
        entry_stat = path.stat(follow_symlinks=False)
    except OSError:
        return None
    if stat.S_ISLNK(entry_stat.st_mode):
        return None
    if entry_stat.st_mtime >= cutoff:
        return None

    try:
        if stat.S_ISDIR(entry_stat.st_mode):
            shutil.rmtree(path)
            return "directory"
        if stat.S_ISREG(entry_stat.st_mode):
            path.unlink()
            return "file"
    except OSError:
        return None
    return None


__all__ = [
    "COMMAND_SCRATCH_HORIZON_SECONDS",
    "DEFAULT_HORIZON_SECONDS",
    "DEFAULT_MAX_REMOVALS",
    "HANDOFF_HORIZON_SECONDS",
    "MANAGED_TMPDIR_HORIZONS",
    "RUN_ARTIFACT_HORIZON_SECONDS",
    "reap_managed_tmpdir",
]

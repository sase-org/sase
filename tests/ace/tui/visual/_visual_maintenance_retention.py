"""Retention for visual screenshot maintenance run directories."""

from __future__ import annotations

from collections.abc import Mapping
import json
import os
from pathlib import Path
import shutil
import time

from tests.ace.tui.visual._visual_maintenance_lock import cache_root
from tests.ace.tui.visual._visual_maintenance_manifest import LATEST_REPORT_FILENAME
from tests.ace.tui.visual._visual_maintenance_types import (
    JOURNAL_APPLYING,
    JOURNAL_FILENAME,
    JOURNAL_PLANNED,
    RUNS_DIRNAME,
)


UNFINISHED_STATUSES = frozenset({JOURNAL_PLANNED, JOURNAL_APPLYING})


KEEP_RECENT_COUNT = 10
RECENT_MODIFIED_SECONDS = 24 * 60 * 60


def _is_unfinished_journal(payload: object) -> bool:
    return isinstance(payload, Mapping) and payload.get("status") in UNFINISHED_STATUSES


def _run_is_unfinished_or_unreadable(run_dir: Path) -> bool:
    """Return True when the run's apply journal is unfinished or unreadable."""
    journal = run_dir / JOURNAL_FILENAME
    if journal.is_symlink() or not journal.is_file():
        return False
    try:
        payload = json.loads(journal.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return True
    return _is_unfinished_journal(payload)


def _latest_run_id(repo_root: Path) -> str | None:
    """Return the run id ``latest-report.json`` points at, if parseable."""
    pointer = cache_root(repo_root) / LATEST_REPORT_FILENAME
    if pointer.is_symlink():
        return None
    try:
        payload = json.loads(pointer.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(payload, Mapping):
        return None
    run_id = payload.get("run_id")
    if isinstance(run_id, str) and run_id:
        return run_id
    manifest = payload.get("manifest")
    if isinstance(manifest, str):
        parts = Path(manifest).parts
        if RUNS_DIRNAME in parts:
            index = parts.index(RUNS_DIRNAME)
            if index + 1 < len(parts):
                return parts[index + 1]
    return None


def _run_mtime(run_dir: Path) -> float:
    try:
        return run_dir.lstat().st_mtime
    except OSError:
        return 0.0


def _has_recent_descendant(run_dir: Path, *, now: float) -> bool:
    """Return True when any descendant was modified in the last 24 hours."""
    cutoff = now - RECENT_MODIFIED_SECONDS
    try:
        with os.scandir(run_dir) as handle:
            stack = list(handle)
    except OSError:
        return False
    while stack:
        entry = stack.pop()
        try:
            if entry.is_symlink():
                continue
            is_dir = entry.is_dir(follow_symlinks=False)
        except OSError:
            continue
        if is_dir:
            try:
                with os.scandir(entry.path) as handle:
                    stack.extend(handle)
            except OSError:
                continue
        else:
            try:
                mtime = entry.stat(follow_symlinks=False).st_mtime
            except OSError:
                continue
            if mtime >= cutoff:
                return True
    try:
        return run_dir.lstat().st_mtime >= cutoff
    except OSError:
        return False


def select_runs_to_prune(
    repo_root: Path,
    *,
    current_run_id: str | None = None,
    now: float | None = None,
) -> list[Path]:
    """Return run directories that retention may delete."""
    runs_dir = cache_root(repo_root) / RUNS_DIRNAME
    try:
        entries = sorted(runs_dir.iterdir())
    except OSError:
        return []
    run_dirs = [entry for entry in entries if entry.is_dir() and not entry.is_symlink()]
    if not run_dirs:
        return []
    keep: set[str] = set()
    if current_run_id:
        keep.add(current_run_id)
    latest = _latest_run_id(repo_root)
    if latest:
        keep.add(latest)
    timestamp = time.time() if now is None else now
    for run_dir in run_dirs:
        if _run_is_unfinished_or_unreadable(run_dir):
            keep.add(run_dir.name)
        elif _has_recent_descendant(run_dir, now=timestamp):
            keep.add(run_dir.name)
    by_recent = sorted(run_dirs, key=_run_mtime, reverse=True)
    for run_dir in by_recent[:KEEP_RECENT_COUNT]:
        keep.add(run_dir.name)
    return [run_dir for run_dir in run_dirs if run_dir.name not in keep]


def prune_old_runs(
    repo_root: Path,
    *,
    current_run_id: str | None = None,
    now: float | None = None,
) -> tuple[str, ...]:
    """Delete prunable run directories. Return the removed run ids."""
    removed: list[str] = []
    for run_dir in select_runs_to_prune(
        repo_root, current_run_id=current_run_id, now=now
    ):
        try:
            shutil.rmtree(run_dir, ignore_errors=False)
        except OSError:
            continue
        removed.append(run_dir.name)
    return tuple(removed)


def prune_old_runs_best_effort(
    repo_root: Path,
    *,
    current_run_id: str | None = None,
) -> tuple[str, ...]:
    """Prune old runs without ever raising into the maintenance run."""
    try:
        return prune_old_runs(repo_root, current_run_id=current_run_id)
    except Exception:
        return ()

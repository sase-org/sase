"""Shared ACE-run artifact shard window helpers."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import datetime
from pathlib import Path

from sase.core.time import local_now

MAX_STARTUP_ACE_RUN_MONTH_WATCHES = 2
MAX_STARTUP_ACE_RUN_DAY_WATCHES = 14


def live_ace_run_shard_names(now: datetime | None = None) -> tuple[str, str]:
    """Return the live ``YYYYMM`` month and ``DD`` day shard names."""
    current = local_now() if now is None else now
    return current.strftime("%Y%m"), current.strftime("%d")


def _is_ace_run_month_shard_name(name: str) -> bool:
    """Return whether *name* is an ACE-run month shard."""
    return len(name) == 6 and name.isdigit()


def is_ace_run_day_shard_name(name: str) -> bool:
    """Return whether *name* is an ACE-run day shard."""
    if len(name) != 2 or not name.isdigit():
        return False
    return 1 <= int(name) <= 31


def is_agent_artifact_dir_name(name: str) -> bool:
    """Return whether *name* is a canonical per-run artifact directory."""
    return len(name) == 14 and name.isdigit()


def iter_ace_run_month_dirs(workflow_dir: Path) -> tuple[Path, ...]:
    """Return existing ACE-run month shard directories under *workflow_dir*."""
    try:
        children = tuple(workflow_dir.iterdir())
    except OSError:
        return ()
    return tuple(
        child
        for child in children
        if _path_is_dir(child) and _is_ace_run_month_shard_name(child.name)
    )


def iter_future_ace_run_month_dirs(
    workflow_dir: Path,
    *,
    now: datetime | None = None,
) -> Iterator[Path]:
    """Yield existing ace-run month dirs dated after the live month."""
    current_month, _ = live_ace_run_shard_names(now)
    for month_dir in iter_ace_run_month_dirs(workflow_dir):
        if month_dir.name > current_month:
            yield month_dir


def iter_startup_ace_run_shard_watch_paths(
    workflow_dir: Path,
    *,
    now: datetime | None = None,
    max_months: int = MAX_STARTUP_ACE_RUN_MONTH_WATCHES,
    max_days: int = MAX_STARTUP_ACE_RUN_DAY_WATCHES,
) -> Iterator[Path]:
    """Yield the month/day shards ACE should watch at startup.

    Future-dated shards are dropped so lexicographic junk cannot consume the
    budget. The live month and today's day shard are always included when they
    exist. Remaining day slots are spent newest-first across the selected
    months rather than letting one month exhaust the budget.
    """
    current_month, current_day = live_ace_run_shard_names(now)
    live_month_dir = workflow_dir / current_month
    live_day_dir = live_month_dir / current_day

    month_dirs = [
        month_dir
        for month_dir in iter_ace_run_month_dirs(workflow_dir)
        if month_dir.name <= current_month
    ]
    month_dirs.sort(key=lambda path: path.name, reverse=True)
    selected_months = _force_include_path(
        month_dirs[: max(max_months, 0)],
        live_month_dir,
        key=lambda path: path.name,
        budget=max(max_months, 0),
    )

    day_candidates: list[Path] = []
    for month_dir in selected_months:
        try:
            children = tuple(month_dir.iterdir())
        except OSError:
            continue
        for child in children:
            if not _path_is_dir(child) or not is_ace_run_day_shard_name(child.name):
                continue
            if month_dir.name == current_month and child.name > current_day:
                continue
            day_candidates.append(child)
    day_candidates.sort(key=lambda path: (path.parent.name, path.name), reverse=True)
    selected_days = _force_include_path(
        day_candidates[: max(max_days, 0)],
        live_day_dir,
        key=lambda path: (path.parent.name, path.name),
        budget=max(max_days, 0),
    )

    for month_dir in selected_months:
        yield month_dir
        for day_dir in selected_days:
            if day_dir.parent == month_dir:
                yield day_dir


def _force_include_path(
    selected: list[Path],
    required: Path,
    *,
    key: Callable[[Path], str | tuple[str, str]],
    budget: int,
) -> list[Path]:
    """Ensure *required* is selected when it exists on disk."""
    if not _path_is_dir(required):
        return selected
    if any(path == required for path in selected):
        return selected
    if budget <= 0:
        chosen = [required]
    elif len(selected) < budget:
        chosen = [*selected, required]
    else:
        chosen = [*selected[:-1], required]
    chosen.sort(key=key, reverse=True)
    return chosen


def _path_is_dir(path: Path) -> bool:
    try:
        return path.is_dir()
    except OSError:
        return False


__all__ = [
    "MAX_STARTUP_ACE_RUN_DAY_WATCHES",
    "MAX_STARTUP_ACE_RUN_MONTH_WATCHES",
    "is_ace_run_day_shard_name",
    "is_agent_artifact_dir_name",
    "iter_ace_run_month_dirs",
    "iter_future_ace_run_month_dirs",
    "iter_startup_ace_run_shard_watch_paths",
    "live_ace_run_shard_names",
]

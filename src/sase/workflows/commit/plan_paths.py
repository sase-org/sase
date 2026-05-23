"""Helpers for stable SASE_PLAN references in commit metadata."""

from __future__ import annotations

import os
from pathlib import Path


def format_sase_plan_reference(
    raw_plan: str,
    *,
    repo_root: str | os.PathLike[str] | None = None,
    home_dir: str | os.PathLike[str] | None = None,
) -> str | None:
    """Return the portable display path for a ``SASE_PLAN`` value.

    In-repo paths are written relative to the repository root. Local SDD paths
    stored under ``.sase/sdd`` keep that stable prefix. Other paths under the
    user's home directory are shortened with ``~``.
    """
    if not raw_plan:
        return None

    raw_path = Path(raw_plan).expanduser()
    compare_path = _comparison_path(raw_path, repo_root)

    if repo_root:
        repo = Path(repo_root).expanduser().resolve(strict=False)
        if compare_path.is_relative_to(repo):
            return compare_path.relative_to(repo).as_posix()

    local_sdd = _local_sdd_reference(compare_path)
    if local_sdd is not None:
        return local_sdd

    home = Path(home_dir).expanduser() if home_dir is not None else Path.home()
    home = home.resolve(strict=False)
    if compare_path == home:
        return "~"
    if compare_path.is_relative_to(home):
        return f"~/{compare_path.relative_to(home).as_posix()}"

    return Path(raw_plan).expanduser().as_posix()


def is_sase_plan_in_repo(
    raw_plan: str,
    repo_root: str | os.PathLike[str] | None,
) -> bool:
    """Return True when *raw_plan* resolves under *repo_root*."""
    if not raw_plan or not repo_root:
        return False
    plan = _comparison_path(Path(raw_plan).expanduser(), repo_root)
    repo = Path(repo_root).expanduser().resolve(strict=False)
    return plan.is_relative_to(repo)


def _comparison_path(
    path: Path,
    repo_root: str | os.PathLike[str] | None,
) -> Path:
    if not path.is_absolute() and repo_root:
        path = Path(repo_root).expanduser() / path
    return path.resolve(strict=False)


def _local_sdd_reference(path: Path) -> str | None:
    parts = path.parts
    for idx in range(len(parts) - 1):
        if parts[idx] == ".sase" and parts[idx + 1] == "sdd":
            return Path(*parts[idx:]).as_posix()
    return None

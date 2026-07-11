"""Helpers for stable SASE_PLAN references in commit metadata."""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sase.sdd.store import SddStore


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


def format_sase_plan_tag_value(
    raw_plan: str,
    *,
    repo_root: str | os.PathLike[str] | None,
    store: SddStore,
    home_dir: str | os.PathLike[str] | None = None,
) -> str | None:
    """Return the path value for a ``SASE_PLAN=`` commit tag.

    Plans in an SDD store are relative to that store's repository root.  The
    ``.sase/sdd`` fallback preserves that form when *raw_plan* points at a
    different workspace's clone of the same store.  Other paths retain the
    portable display formatting used by ChangeSpec metadata.
    """
    if not raw_plan:
        return None

    compare_path = _comparison_path(Path(raw_plan).expanduser(), repo_root)
    store_root = Path(store.sdd_dir).expanduser().resolve(strict=False)
    if not store.is_in_tree and compare_path.is_relative_to(store_root):
        return compare_path.relative_to(store_root).as_posix()

    local_sdd = _local_sdd_reference(compare_path)
    if local_sdd is not None:
        local_sdd_path = Path(local_sdd)
        return Path(*local_sdd_path.parts[2:]).as_posix()

    return format_sase_plan_reference(
        raw_plan,
        repo_root=repo_root,
        home_dir=home_dir,
    )


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

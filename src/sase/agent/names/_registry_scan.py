"""Source scanning for the durable agent-name registry."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
import re

from sase.agent.names._registry_scan_collectors import (
    collect_artifact_entries as collect_artifact_entries,
    collect_dismissed_bundle_entries as collect_dismissed_bundle_entries,
    collect_owner_namespace_entries as collect_owner_namespace_entries,
    collect_planned_reservation_entries as collect_planned_reservation_entries,
)
from sase.core.agent_artifact_paths import iter_agent_artifact_dirs
from sase.core.paths import sase_home, sase_projects_dir, sase_subdir

_MONTH_SHARD_RE = re.compile(r"^\d{6}$")
_DAY_SHARD_RE = re.compile(r"^\d{2}$")


def _directory_entries(path: Path) -> tuple[Path, ...]:
    """List a directory only after its entry set changes.

    Directory mtimes change when children are added, removed, or renamed. The
    cache therefore bounds repeated archive enumeration by the number of shard
    directories whose membership changed, while callers still stat every
    returned source path so in-place file rewrites remain visible.
    """

    try:
        stat = path.stat()
    except OSError:
        return ()
    return _directory_entries_for_signature(
        path,
        stat.st_mtime_ns,
        stat.st_ctime_ns,
        stat.st_size,
    )


@lru_cache(maxsize=4_096)
def _directory_entries_for_signature(
    path: Path,
    mtime_ns: int,
    ctime_ns: int,
    size: int,
) -> tuple[Path, ...]:
    del mtime_ns, ctime_ns, size
    try:
        return tuple(path.iterdir())
    except OSError:
        return ()


def source_signature_paths() -> list[Path]:
    """Return registry-relevant source entries, excluding live run contents.

    Artifact directory names are durable registry inputs. Files created inside a
    running artifact directory are not, so including that directory's mtime in
    the signature makes the registry permanently stale.
    """

    paths = [
        sase_home() / "dismissed_agents.json",
    ]
    dismissed_bundles = sase_subdir("dismissed_bundles")
    bundle_root_entries = _directory_entries(dismissed_bundles)
    paths.extend(
        path
        for path in bundle_root_entries
        if path.suffix == ".json" and path.is_file()
    )
    for shard_dir in bundle_root_entries:
        if not shard_dir.is_dir():
            continue
        paths.extend(
            path
            for path in _directory_entries(shard_dir)
            if path.suffix == ".json" and path.is_file()
        )
    projects_dir = sase_projects_dir()
    project_dirs = [p for p in _directory_entries(projects_dir) if p.is_dir()]
    for project_dir in project_dirs:
        artifacts_dir = project_dir / "artifacts"
        workflow_dirs = [p for p in _directory_entries(artifacts_dir) if p.is_dir()]
        for workflow_dir in workflow_dirs:
            paths.extend(
                _artifact_dirs_for_workflow(
                    project_dir.name,
                    workflow_dir.name,
                    projects_dir,
                    workflow_dir,
                )
            )
    return paths


def reset_registry_scan_caches() -> None:
    """Clear derived source enumeration caches after test home isolation changes."""
    _directory_entries_for_signature.cache_clear()
    _artifact_dirs_for_signature.cache_clear()


def _artifact_dirs_for_workflow(
    project_name: str,
    workflow_name: str,
    projects_dir: Path,
    workflow_dir: Path,
) -> tuple[Path, ...]:
    """Cache the core artifact walk until a containing directory changes."""

    return _artifact_dirs_for_signature(
        project_name,
        workflow_name,
        projects_dir,
        _artifact_tree_signature(workflow_dir),
    )


def _artifact_tree_signature(
    workflow_dir: Path,
) -> tuple[tuple[str, int, int, int], ...]:
    """Fingerprint only artifact containers, never each artifact directory."""

    directories = [workflow_dir]
    for month_dir in _directory_entries(workflow_dir):
        if not month_dir.is_dir() or not _MONTH_SHARD_RE.fullmatch(month_dir.name):
            continue
        directories.append(month_dir)
        directories.extend(
            day_dir
            for day_dir in _directory_entries(month_dir)
            if day_dir.is_dir() and _DAY_SHARD_RE.fullmatch(day_dir.name)
        )
    signature: list[tuple[str, int, int, int]] = []
    for directory in directories:
        try:
            stat = directory.stat()
        except OSError:
            continue
        signature.append(
            (
                str(directory),
                stat.st_mtime_ns,
                stat.st_ctime_ns,
                stat.st_size,
            )
        )
    return tuple(signature)


@lru_cache(maxsize=1_024)
def _artifact_dirs_for_signature(
    project_name: str,
    workflow_name: str,
    projects_dir: Path,
    tree_signature: tuple[tuple[str, int, int, int], ...],
) -> tuple[Path, ...]:
    """Delegate actual layout interpretation to the shared core helper."""

    del tree_signature
    try:
        return tuple(
            iter_agent_artifact_dirs(
                project_name,
                workflow_name,
                projects_root=projects_dir,
            )
        )
    except OSError:
        return ()

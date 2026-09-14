"""Inventory collection for SASE-owned and SASE-shaped disk usage."""

from __future__ import annotations

import os
import stat
import time
from collections.abc import Callable, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from sase.config import get_artifact_retention_keep_recent_run_months
from sase.core.disk_footprint_models import DiskFootprintReport, DiskFootprintRow
from sase.core.disk_footprint_utils import (
    format_horizon_seconds,
    is_relative_to,
    iter_children,
    resolve_soft,
    tree_size,
)
from sase.core.managed_tmp_reaper import (
    DEFAULT_HORIZON_SECONDS,
    MANAGED_TMPDIR_HORIZONS,
)
from sase.core.paths import managed_tmpdir_root, sase_home, sase_projects_dir
from sase.core.time import local_now
from sase.procs.paths import procs_dir
from sase.workspace_provider.inventory import collect_workspace_inventory


_GIB = 1024**3
_DEFAULT_STRAY_MAX_DEPTH = 6
_DEFAULT_STRAY_MAX_VISITED = 50_000
_DEFAULT_STRAY_SCAN_SECONDS = 5.0


def collect_disk_footprint(
    *,
    include_strays: bool = True,
    home: Path | None = None,
    tree_size_fn: Callable[[Path], int] = lambda path: tree_size(path),
    workspace_inventory_fn: Callable[..., Any] = collect_workspace_inventory,
    now: datetime | None = None,
) -> DiskFootprintReport:
    """Collect SASE-owned and SASE-shaped disk usage rows."""

    rows: list[DiskFootprintRow] = []
    generated = (now or local_now()).isoformat()
    rows.extend(_managed_tmp_rows(tree_size_fn=tree_size_fn))
    rows.extend(_sase_state_rows(tree_size_fn=tree_size_fn))
    rows.extend(
        _workspace_rows(
            tree_size_fn=tree_size_fn,
            workspace_inventory_fn=workspace_inventory_fn,
        )
    )
    core_targets = _rust_target_rows(tree_size_fn=tree_size_fn)
    rows.extend(core_targets)

    stray_truncated = False
    stray_visited = 0
    if include_strays:
        excludes = [
            Path(row.path)
            for row in rows
            if row.status == "owned" and row.path and Path(row.path).is_absolute()
        ]
        strays, stray_visited, stray_truncated = _cargo_stray_rows(
            home or Path.home(),
            excludes=excludes,
            tree_size_fn=tree_size_fn,
        )
        rows.extend(strays)

    rows.sort(key=lambda row: (-row.size_bytes, row.section, row.name, row.path))
    return DiskFootprintReport(
        rows=tuple(rows),
        generated_at=generated,
        stray_scan_truncated=stray_truncated,
        stray_scan_visited=stray_visited,
    )


def largest_unowned_rows(
    *,
    min_bytes: int,
    limit: int = 3,
    report: DiskFootprintReport | None = None,
) -> tuple[DiskFootprintRow, ...]:
    """Return the largest unowned rows above *min_bytes*."""

    current = report or collect_disk_footprint(include_strays=True)
    rows = [
        row
        for row in current.rows
        if row.status == "unowned" and row.size_bytes >= min_bytes
    ]
    rows.sort(key=lambda row: (-row.size_bytes, row.path))
    return tuple(rows[: max(0, limit)])


def _managed_tmp_rows(
    *, tree_size_fn: Callable[[Path], int]
) -> tuple[DiskFootprintRow, ...]:
    root = managed_tmpdir_root()
    rows: list[DiskFootprintRow] = []
    if not root.exists():
        return (
            DiskFootprintRow(
                section="managed_tmp",
                name="<root>",
                path=str(root),
                size_bytes=0,
                owner="managed_tmp_reaper",
                horizon="missing root",
                reclaim="sase disk reap --apply",
            ),
        )

    for entry in iter_children(root):
        horizon_seconds = (
            MANAGED_TMPDIR_HORIZONS.get(entry.name, DEFAULT_HORIZON_SECONDS)
            if entry.is_dir() and not entry.is_symlink()
            else DEFAULT_HORIZON_SECONDS
        )
        rows.append(
            DiskFootprintRow(
                section="managed_tmp",
                name=entry.name,
                path=str(entry),
                size_bytes=tree_size_fn(entry),
                owner="managed_tmp_reaper",
                horizon=format_horizon_seconds(horizon_seconds),
                reclaim="sase disk reap --apply",
            )
        )
    return tuple(rows)


def _sase_state_rows(
    *, tree_size_fn: Callable[[Path], int]
) -> tuple[DiskFootprintRow, ...]:
    rows = [
        DiskFootprintRow(
            section="sase_home",
            name="procs/runtime",
            path=str(procs_dir() / "runtime"),
            size_bytes=tree_size_fn(procs_dir() / "runtime"),
            owner="proc_runtime_sweep",
            horizon="proc row retention",
            reclaim="sase disk reap --apply",
        ),
        DiskFootprintRow(
            section="sase_home",
            name="cache/rust-prebuild",
            path=str(sase_home() / "cache" / "rust-prebuild"),
            size_bytes=tree_size_fn(sase_home() / "cache" / "rust-prebuild"),
            owner="rust_prebuild_cache",
            horizon="keeps newest 2 completed sets",
            reclaim=None,
        ),
    ]
    months = get_artifact_retention_keep_recent_run_months()
    projects = sase_projects_dir()
    for project_dir in iter_children(projects):
        if not project_dir.is_dir() or project_dir.is_symlink():
            continue
        ace_run = project_dir / "artifacts" / "ace-run"
        if not ace_run.exists():
            continue
        rows.append(
            DiskFootprintRow(
                section="sase_home",
                name=f"projects/{project_dir.name}/artifacts/ace-run",
                path=str(ace_run),
                size_bytes=tree_size_fn(ace_run),
                owner="artifact_run_retention",
                horizon=f"keeps newest {months} month(s) and referenced runs",
                reclaim="sase artifact prune-runs --apply",
            )
        )
    return tuple(rows)


def _workspace_rows(
    *,
    tree_size_fn: Callable[[Path], int],
    workspace_inventory_fn: Callable[..., Any],
) -> tuple[DiskFootprintRow, ...]:
    try:
        inventory = workspace_inventory_fn(include_disabled=True)
    except Exception:
        return ()
    rows: list[DiskFootprintRow] = []
    seen: set[str] = set()
    for project in getattr(inventory, "projects", ()):
        root_dir = Path(project.root_dir)
        key = str(root_dir)
        if key in seen:
            continue
        seen.add(key)
        rows.append(
            DiskFootprintRow(
                section="workspaces",
                name=str(project.project),
                path=str(root_dir),
                size_bytes=tree_size_fn(root_dir),
                owner="workspace_cleanup_and_compact",
                horizon=f"cleanup TTL {project.cleanup_ttl_days} day(s)",
                reclaim="sase workspace cleanup --stale; sase workspace compact",
            )
        )
    return tuple(rows)


def _rust_target_rows(
    *, tree_size_fn: Callable[[Path], int]
) -> tuple[DiskFootprintRow, ...]:
    core_dir = _resolve_sase_core_dir()
    if core_dir is None:
        return ()
    rows: list[DiskFootprintRow] = []
    for name in ("uv-tool-lsp", "uv-tool-py"):
        target = core_dir / "target" / name
        incremental = target / "dev-update" / "incremental"
        incremental_size = tree_size_fn(incremental)
        target_size = max(0, tree_size_fn(target) - incremental_size)
        rows.append(
            DiskFootprintRow(
                section="rust_targets",
                name=f"sase-core/target/{name}",
                path=str(target),
                size_bytes=target_size,
                owner="just rust-dev-install",
                horizon="repo-owned persistent target root",
                reclaim=None,
            )
        )
        rows.append(
            DiskFootprintRow(
                section="rust_targets",
                name=f"sase-core/target/{name}/dev-update/incremental",
                path=str(incremental),
                size_bytes=incremental_size,
                owner="just rust-dev-install",
                horizon="safe to delete; CARGO_INCREMENTAL=0 prevents return",
                reclaim="rm -rf <incremental>",
            )
        )
    return tuple(rows)


def _cargo_stray_rows(
    home: Path,
    *,
    excludes: Sequence[Path],
    tree_size_fn: Callable[[Path], int],
    max_depth: int = _DEFAULT_STRAY_MAX_DEPTH,
    max_visited: int = _DEFAULT_STRAY_MAX_VISITED,
    max_seconds: float = _DEFAULT_STRAY_SCAN_SECONDS,
) -> tuple[tuple[DiskFootprintRow, ...], int, bool]:
    root = home.expanduser()
    if not root.is_dir():
        return (), 0, False
    rows: list[DiskFootprintRow] = []
    visited = 0
    truncated = False
    stack: list[tuple[Path, int]] = [(root, 0)]
    resolved_excludes = tuple(resolve_soft(path) for path in excludes)
    deadline = time.monotonic() + max_seconds

    while stack:
        if time.monotonic() >= deadline:
            truncated = True
            break
        path, depth = stack.pop()
        visited += 1
        if visited > max_visited:
            truncated = True
            break
        if path.name in {".git", ".cargo", ".rustup"}:
            continue
        resolved = resolve_soft(path)
        if any(is_relative_to(resolved, excluded) for excluded in resolved_excludes):
            continue
        if path != root and _is_repo_checkout(path):
            continue
        if path != root and _is_cargo_target_root(path):
            rows.append(
                DiskFootprintRow(
                    section="strays",
                    name=path.name,
                    path=str(path),
                    size_bytes=tree_size_fn(path),
                    owner="unowned",
                    horizon="unowned",
                    status="unowned",
                    reclaim=None,
                )
            )
            continue
        if depth >= max_depth:
            continue
        for child in reversed(iter_children(path)):
            try:
                child_stat = child.stat(follow_symlinks=False)
            except OSError:
                continue
            if stat.S_ISDIR(child_stat.st_mode) and not stat.S_ISLNK(
                child_stat.st_mode
            ):
                stack.append((child, depth + 1))
    return tuple(rows), visited, truncated


def _resolve_sase_core_dir() -> Path | None:
    candidates: list[Path] = []
    for name in (
        "SASE_CORE_DIR",
        "SASE_LINKED_REPO_SASE_CORE_DIR",
        "SASE_SIBLING_REPO_SASE_CORE_DIR",
        "SASE_LINKED_REPO_SASE_CORE_PRIMARY_DIR",
        "SASE_SIBLING_REPO_SASE_CORE_PRIMARY_DIR",
    ):
        value = os.environ.get(name)
        if value:
            candidates.append(Path(value).expanduser())
    cwd = Path.cwd()
    candidates.extend(
        [
            cwd / "sase" / "repos" / "linked" / "sase-core",
            cwd.parent / "sase-core",
        ]
    )
    for candidate in candidates:
        if (candidate / "Cargo.toml").is_file():
            return candidate.resolve()
    return None


def _is_cargo_target_root(path: Path) -> bool:
    return (path / ".rustc_info.json").is_file() or (path / "CACHEDIR.TAG").is_file()


def _is_repo_checkout(path: Path) -> bool:
    return (path / ".git").exists()


__all__ = [
    "collect_disk_footprint",
    "largest_unowned_rows",
    "_GIB",
    "_cargo_stray_rows",
    "_is_cargo_target_root",
    "_is_repo_checkout",
    "_managed_tmp_rows",
    "_resolve_sase_core_dir",
    "_rust_target_rows",
    "_sase_state_rows",
    "_workspace_rows",
]

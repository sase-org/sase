"""Inventory collection for SASE-owned and SASE-shaped disk usage.

Public facade over the ``disk_footprint_inventory_*`` split. The row
builders live in :mod:`sase.core.disk_footprint_inventory_rows` (owned
rows) and :mod:`sase.core.disk_footprint_inventory_strays` (rust targets
and stray cargo targets), collection and classification live in
:mod:`sase.core.disk_footprint_inventory_collect`, and shared constants
live in :mod:`sase.core._disk_footprint_inventory_shared`.

This module keeps every historic monkeypatch seam as a settable
attribute and copies the live values into the implementation modules
before each delegated call, so patching
``sase.core.disk_footprint_inventory.<name>`` behaves exactly as it did
when this file held the implementation.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from sase.config import get_artifact_retention_keep_recent_run_months
from sase.config import get_managed_tmp_handoff_horizon_seconds
from sase.core import disk_footprint_inventory_collect as inventory_collect
from sase.core import disk_footprint_inventory_rows as inventory_rows
from sase.core import disk_footprint_inventory_strays as inventory_strays
from sase.core._disk_footprint_inventory_shared import STRAY_MAX_DEPTH
from sase.core._disk_footprint_inventory_shared import STRAY_MAX_VISITED
from sase.core._disk_footprint_inventory_shared import STRAY_SCAN_SECONDS
from sase.core.disk_footprint_inventory_strays import is_cargo_target_root
from sase.core.disk_footprint_inventory_strays import is_repo_checkout
from sase.core.disk_footprint_inventory_strays import resolve_sase_core_dir
from sase.core.disk_footprint_inventory_strays import resolve_sase_core_dirs
from sase.core.disk_footprint_models import DiskFootprintReport
from sase.core.disk_footprint_models import DiskFootprintRow
from sase.core.disk_footprint_utils import InventoryScanBudget
from sase.core.disk_footprint_utils import format_horizon_seconds
from sase.core.disk_footprint_utils import is_relative_to
from sase.core.disk_footprint_utils import iter_children
from sase.core.disk_footprint_utils import resolve_soft
from sase.core.disk_footprint_utils import tree_size
from sase.core.disk_inventory import classify_disk_inventory
from sase.core.managed_tmp_reaper import current_managed_tmp_horizons
from sase.core.managed_tmp_roots import effective_managed_tmp_roots
from sase.core.paths import managed_tmpdir_root
from sase.core.paths import sase_home
from sase.core.paths import sase_projects_dir
from sase.core.time import local_now
from sase.procs.paths import procs_dir
from sase.workspace_provider.inventory import collect_workspace_inventory


def collect_disk_footprint(
    *,
    include_strays: bool = True,
    home: Path | None = None,
    tree_size_fn: Callable[[Path], int] | None = None,
    workspace_inventory_fn: Callable[..., Any] = collect_workspace_inventory,
    now: datetime | None = None,
    disk_usage_fn: Callable[[str], Any] | None = None,
) -> DiskFootprintReport:
    _sync_collect_patchables()
    _sync_rows_patchables()
    _sync_strays_patchables()
    return inventory_collect.collect_disk_footprint(
        include_strays=include_strays,
        home=home,
        tree_size_fn=tree_size_fn,
        workspace_inventory_fn=workspace_inventory_fn,
        now=now,
        disk_usage_fn=disk_usage_fn,
    )


def largest_unowned_rows(
    *,
    min_bytes: int,
    limit: int = 3,
    report: DiskFootprintReport | None = None,
) -> tuple[DiskFootprintRow, ...]:
    _sync_collect_patchables()
    _sync_rows_patchables()
    _sync_strays_patchables()
    return inventory_collect.largest_unowned_rows(
        min_bytes=min_bytes,
        limit=limit,
        report=report,
    )


def managed_tmp_rows(
    *,
    tree_size_fn: Callable[[Path], int],
    budget: InventoryScanBudget | None = None,
    diagnostics: list[str] | None = None,
    roots: Sequence[Path] | None = None,
) -> tuple[DiskFootprintRow, ...]:
    _sync_rows_patchables()
    return inventory_rows.managed_tmp_rows(
        tree_size_fn=tree_size_fn,
        budget=budget,
        diagnostics=diagnostics,
        roots=roots,
    )


def sase_state_rows(
    *,
    tree_size_fn: Callable[[Path], int],
    budget: InventoryScanBudget | None = None,
    diagnostics: list[str] | None = None,
) -> tuple[DiskFootprintRow, ...]:
    _sync_rows_patchables()
    return inventory_rows.sase_state_rows(
        tree_size_fn=tree_size_fn,
        budget=budget,
        diagnostics=diagnostics,
    )


def workspace_rows(
    *,
    tree_size_fn: Callable[[Path], int],
    workspace_inventory_fn: Callable[..., Any],
    diagnostics: list[str] | None = None,
) -> tuple[DiskFootprintRow, ...]:
    _sync_rows_patchables()
    return inventory_rows.workspace_rows(
        tree_size_fn=tree_size_fn,
        workspace_inventory_fn=workspace_inventory_fn,
        diagnostics=diagnostics,
    )


def rust_target_rows(
    *, tree_size_fn: Callable[[Path], int]
) -> tuple[DiskFootprintRow, ...]:
    _sync_strays_patchables()
    return inventory_strays.rust_target_rows(tree_size_fn=tree_size_fn)


def cargo_stray_rows(
    home: Path,
    *,
    excludes: Sequence[Path],
    tree_size_fn: Callable[[Path], int],
    budget: InventoryScanBudget | None = None,
    max_depth: int = STRAY_MAX_DEPTH,
    max_visited: int = STRAY_MAX_VISITED,
    max_seconds: float = STRAY_SCAN_SECONDS,
) -> tuple[tuple[DiskFootprintRow, ...], int, bool]:
    _sync_strays_patchables()
    return inventory_strays.cargo_stray_rows(
        home,
        excludes=excludes,
        tree_size_fn=tree_size_fn,
        budget=budget,
        max_depth=max_depth,
        max_visited=max_visited,
        max_seconds=max_seconds,
    )


def _sync_collect_patchables() -> None:
    inventory_collect.classify_disk_inventory = classify_disk_inventory
    inventory_collect.collect_workspace_inventory = collect_workspace_inventory
    inventory_collect.local_now = local_now
    inventory_collect.sase_home = sase_home
    inventory_collect.managed_tmp_rows = managed_tmp_rows
    inventory_collect.sase_state_rows = sase_state_rows
    inventory_collect.workspace_rows = workspace_rows
    inventory_collect.rust_target_rows = rust_target_rows
    inventory_collect.cargo_stray_rows = cargo_stray_rows


def _sync_rows_patchables() -> None:
    inventory_rows.current_managed_tmp_horizons = current_managed_tmp_horizons
    inventory_rows.effective_managed_tmp_roots = effective_managed_tmp_roots
    inventory_rows.format_horizon_seconds = format_horizon_seconds
    inventory_rows.get_artifact_retention_keep_recent_run_months = (
        get_artifact_retention_keep_recent_run_months
    )
    inventory_rows.get_managed_tmp_handoff_horizon_seconds = (
        get_managed_tmp_handoff_horizon_seconds
    )
    inventory_rows.iter_children = iter_children
    inventory_rows.managed_tmpdir_root = managed_tmpdir_root
    inventory_rows.procs_dir = procs_dir
    inventory_rows.sase_home = sase_home
    inventory_rows.sase_projects_dir = sase_projects_dir


def _sync_strays_patchables() -> None:
    inventory_strays.is_relative_to = is_relative_to
    inventory_strays.resolve_sase_core_dir = resolve_sase_core_dir
    inventory_strays.resolve_sase_core_dirs = resolve_sase_core_dirs


__all__ = [
    "cargo_stray_rows",
    "collect_disk_footprint",
    "is_cargo_target_root",
    "is_repo_checkout",
    "largest_unowned_rows",
    "managed_tmp_rows",
    "resolve_sase_core_dir",
    "resolve_sase_core_dirs",
    "resolve_soft",
    "rust_target_rows",
    "sase_state_rows",
    "workspace_rows",
]

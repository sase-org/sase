"""SASE disk-footprint inventory and owned-reaper delegation."""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from sase.config import get_artifact_retention_keep_recent_run_months
from sase.core import disk_footprint_inventory as _inventory
from sase.core import disk_footprint_reap as _reap
from sase.core import disk_footprint_utils as _utils
from sase.core.agent_artifact_run_retention import (
    AceRunRetentionPolicy,
    apply_ace_run_retention,
    collect_ace_run_retention_protections,
    plan_ace_run_retention,
)
from sase.core.disk_footprint_models import (
    DiskFootprintReport,
    DiskFootprintRow,
    DiskReapResult,
    DiskReapStep,
)
from sase.core.disk_footprint_utils import (
    format_horizon_seconds,
    is_relative_to,
    iter_children,
    resolve_soft,
    tree_size,
    format_bytes,
)
from sase.core.managed_tmp_reaper import reap_managed_tmpdir
from sase.core.paths import managed_tmpdir_root, sase_home, sase_projects_dir
from sase.core.time import local_now
from sase.procs.paths import procs_dir
from sase.procs.runtime import sweep_orphan_proc_runtime_dirs
from sase.procs.store import prune_procs
from sase.workspace_provider.inventory import collect_workspace_inventory

_DiskFootprintRow = DiskFootprintRow
_DiskReapStep = DiskReapStep
_GIB = _inventory._GIB
_cargo_stray_rows = _inventory.cargo_stray_rows
_du_size = _utils.du_size
_format_horizon_seconds = format_horizon_seconds
_is_cargo_target_root = _inventory.is_cargo_target_root
_is_relative_to = is_relative_to
_is_repo_checkout = _inventory.is_repo_checkout
_iter_children = iter_children
_managed_tmp_reap_step = _reap.managed_tmp_reap_step
_managed_tmp_rows = _inventory.managed_tmp_rows
_proc_runtime_reap_step = _reap.proc_runtime_reap_step
_resolve_sase_core_dir = _inventory.resolve_sase_core_dir
_resolve_soft = resolve_soft
_rust_target_rows = _inventory.rust_target_rows
_sase_state_rows = _inventory.sase_state_rows
_tree_size = tree_size
_tree_size_walk = _utils.tree_size_walk
_workspace_compact_steps = _reap.workspace_compact_steps
_workspace_project_keys = _reap.workspace_project_keys
_workspace_rows = _inventory.workspace_rows
_artifact_run_reap_step = _reap.artifact_run_reap_step


def collect_disk_footprint(
    *,
    include_strays: bool = True,
    home: Path | None = None,
    tree_size_fn: Callable[[Path], int] | None = None,
    workspace_inventory_fn: Callable[..., Any] | None = None,
    now: datetime | None = None,
) -> DiskFootprintReport:
    """Collect SASE-owned and SASE-shaped disk usage rows."""

    _sync_inventory_patchables()
    return _inventory.collect_disk_footprint(
        include_strays=include_strays,
        home=home,
        tree_size_fn=tree_size_fn,
        workspace_inventory_fn=workspace_inventory_fn or collect_workspace_inventory,
        now=now,
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


def run_disk_reap(
    *,
    apply: bool = False,
    include_artifact_runs: bool = True,
    project: str | None = None,
    include_workspace_compact: bool = True,
    filesystem_available_bytes: int | None = None,
    managed_tmp_pressure_min_available_bytes: int | None = None,
    managed_tmp_pressure_recovery_available_bytes: int | None = None,
    subprocess_run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> DiskReapResult:
    """Preview or invoke each owner reaper without inventing deletion policy."""

    _sync_reap_patchables()
    return _reap.run_disk_reap(
        apply=apply,
        include_artifact_runs=include_artifact_runs,
        project=project,
        include_workspace_compact=include_workspace_compact,
        filesystem_available_bytes=filesystem_available_bytes,
        managed_tmp_pressure_min_available_bytes=managed_tmp_pressure_min_available_bytes,
        managed_tmp_pressure_recovery_available_bytes=(
            managed_tmp_pressure_recovery_available_bytes
        ),
        subprocess_run=subprocess_run,
    )


def _sync_inventory_patchables() -> None:
    _inventory.managed_tmpdir_root = managed_tmpdir_root
    _inventory.sase_home = sase_home
    _inventory.sase_projects_dir = sase_projects_dir
    _inventory.procs_dir = procs_dir
    _inventory.collect_workspace_inventory = collect_workspace_inventory
    _inventory.get_artifact_retention_keep_recent_run_months = (
        get_artifact_retention_keep_recent_run_months
    )
    _inventory.local_now = local_now
    _inventory.tree_size = _tree_size
    _inventory.iter_children = _iter_children
    _inventory.format_horizon_seconds = _format_horizon_seconds
    _inventory.resolve_soft = _resolve_soft
    _inventory.is_relative_to = _is_relative_to
    _inventory.managed_tmp_rows = _managed_tmp_rows
    _inventory.sase_state_rows = _sase_state_rows
    _inventory.workspace_rows = _workspace_rows
    _inventory.rust_target_rows = _rust_target_rows
    _inventory.cargo_stray_rows = _cargo_stray_rows
    _inventory.resolve_sase_core_dir = _resolve_sase_core_dir


def _sync_reap_patchables() -> None:
    _reap.AceRunRetentionPolicy = AceRunRetentionPolicy  # type: ignore[misc]
    _reap.apply_ace_run_retention = apply_ace_run_retention
    _reap.collect_ace_run_retention_protections = collect_ace_run_retention_protections
    _reap.plan_ace_run_retention = plan_ace_run_retention
    _reap.get_artifact_retention_keep_recent_run_months = (
        get_artifact_retention_keep_recent_run_months
    )
    _reap.local_now = local_now
    _reap.reap_managed_tmpdir = reap_managed_tmpdir
    _reap.prune_procs = prune_procs
    _reap.sweep_orphan_proc_runtime_dirs = sweep_orphan_proc_runtime_dirs
    _reap.collect_workspace_inventory = collect_workspace_inventory
    _reap.managed_tmp_reap_step = _managed_tmp_reap_step
    _reap.proc_runtime_reap_step = _proc_runtime_reap_step
    _reap.artifact_run_reap_step = _artifact_run_reap_step
    _reap.workspace_compact_steps = _workspace_compact_steps
    _reap.workspace_project_keys = _workspace_project_keys


__all__ = [
    "DiskFootprintReport",
    "DiskReapResult",
    "collect_disk_footprint",
    "format_bytes",
    "largest_unowned_rows",
    "run_disk_reap",
]

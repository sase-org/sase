"""Owner-delegated cleanup orchestration for ``sase disk reap``."""

from __future__ import annotations

import subprocess
from collections.abc import Callable

from sase.config import get_artifact_retention_keep_recent_run_months
from sase.core import disk_footprint_reap_artifacts as _artifacts
from sase.core import disk_footprint_reap_managed_tmp as _managed_tmp
from sase.core import disk_footprint_reap_proc as _proc
from sase.core import disk_footprint_reap_workspace as _workspace
from sase.core.agent_artifact_run_retention import (
    AceRunRetentionPolicy,
    apply_ace_run_retention,
    collect_ace_run_retention_protections,
    plan_ace_run_retention,
)
from sase.core.disk_footprint_models import DiskReapResult, DiskReapStep
from sase.core.disk_pressure import filesystem_pressure_policy
from sase.core.managed_tmp_reaper import reap_managed_tmpdir
from sase.core.paths import managed_tmpdir_root as _paths_managed_tmpdir_root
from sase.core.time import local_now
from sase.procs.runtime import sweep_orphan_proc_runtime_dirs
from sase.procs.store import prune_procs
from sase.workspace_provider.inventory import collect_workspace_inventory

managed_tmpdir_root = _paths_managed_tmpdir_root


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
    workspace_compact_timeout_seconds: float = 120.0,
) -> DiskReapResult:
    """Preview or invoke each owner reaper without inventing deletion policy."""

    steps: list[DiskReapStep] = []
    steps.append(
        managed_tmp_reap_step(
            apply=apply,
            filesystem_available_bytes=filesystem_available_bytes,
            pressure_min_available_bytes=managed_tmp_pressure_min_available_bytes,
            pressure_recovery_available_bytes=(
                managed_tmp_pressure_recovery_available_bytes
            ),
        )
    )
    steps.append(proc_runtime_reap_step(apply=apply))
    if include_artifact_runs:
        steps.append(artifact_run_reap_step(apply=apply, project=project))
    if include_workspace_compact:
        steps.extend(
            workspace_compact_steps(
                apply=apply,
                project=project,
                subprocess_run=subprocess_run,
                timeout_seconds=workspace_compact_timeout_seconds,
            )
        )
    return DiskReapResult(apply=apply, project=project, steps=tuple(steps))


def managed_tmp_reap_step(
    *,
    apply: bool,
    filesystem_available_bytes: int | None = None,
    pressure_min_available_bytes: int | None = None,
    pressure_recovery_available_bytes: int | None = None,
) -> DiskReapStep:
    _sync_managed_tmp_patchables()
    return _managed_tmp.managed_tmp_reap_step(
        apply=apply,
        filesystem_available_bytes=filesystem_available_bytes,
        pressure_min_available_bytes=pressure_min_available_bytes,
        pressure_recovery_available_bytes=pressure_recovery_available_bytes,
    )


def proc_runtime_reap_step(*, apply: bool) -> DiskReapStep:
    _sync_proc_patchables()
    return _proc.proc_runtime_reap_step(apply=apply)


def artifact_run_reap_step(*, apply: bool, project: str | None) -> DiskReapStep:
    _sync_artifact_patchables()
    return _artifacts.artifact_run_reap_step(apply=apply, project=project)


def workspace_compact_steps(
    *,
    apply: bool,
    project: str | None,
    subprocess_run: Callable[..., subprocess.CompletedProcess[str]],
    timeout_seconds: float = 120.0,
) -> tuple[DiskReapStep, ...]:
    _sync_workspace_patchables()
    return _workspace.workspace_compact_steps(
        apply=apply,
        project=project,
        subprocess_run=subprocess_run,
        timeout_seconds=timeout_seconds,
    )


def workspace_project_keys() -> tuple[str, ...]:
    _sync_workspace_patchables()
    return _workspace.workspace_project_keys()


def _sync_managed_tmp_patchables() -> None:
    _managed_tmp.managed_tmpdir_root = managed_tmpdir_root
    _managed_tmp.filesystem_pressure_policy = filesystem_pressure_policy
    _managed_tmp.reap_managed_tmpdir = reap_managed_tmpdir


def _sync_proc_patchables() -> None:
    _proc.prune_procs = prune_procs
    _proc.sweep_orphan_proc_runtime_dirs = sweep_orphan_proc_runtime_dirs


def _sync_artifact_patchables() -> None:
    _artifacts.AceRunRetentionPolicy = AceRunRetentionPolicy  # type: ignore[misc]
    _artifacts.apply_ace_run_retention = apply_ace_run_retention
    _artifacts.collect_ace_run_retention_protections = (
        collect_ace_run_retention_protections
    )
    _artifacts.get_artifact_retention_keep_recent_run_months = (
        get_artifact_retention_keep_recent_run_months
    )
    _artifacts.local_now = local_now
    _artifacts.plan_ace_run_retention = plan_ace_run_retention


def _sync_workspace_patchables() -> None:
    _workspace.collect_workspace_inventory = collect_workspace_inventory


__all__ = [
    "artifact_run_reap_step",
    "managed_tmp_reap_step",
    "proc_runtime_reap_step",
    "run_disk_reap",
    "workspace_compact_steps",
    "workspace_project_keys",
]

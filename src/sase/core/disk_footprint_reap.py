"""Owner-delegated cleanup orchestration for ``sase disk reap``."""

from __future__ import annotations

import subprocess
from collections.abc import Callable

from sase.config import get_artifact_retention_keep_recent_run_months
from sase.core.agent_artifact_run_retention import (
    AceRunRetentionPolicy,
    apply_ace_run_retention,
    collect_ace_run_retention_protections,
    plan_ace_run_retention,
)
from sase.core.disk_footprint_models import DiskReapResult, DiskReapStep
from sase.core.managed_tmp_reaper import reap_managed_tmpdir
from sase.core.time import local_now
from sase.procs.runtime import sweep_orphan_proc_runtime_dirs
from sase.procs.store import prune_procs
from sase.workspace_provider.inventory import collect_workspace_inventory


def run_disk_reap(
    *,
    apply: bool = False,
    include_artifact_runs: bool = True,
    project: str | None = None,
    include_workspace_compact: bool = True,
    subprocess_run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> DiskReapResult:
    """Preview or invoke each owner reaper without inventing deletion policy."""

    steps: list[DiskReapStep] = []
    steps.append(managed_tmp_reap_step(apply=apply))
    steps.append(proc_runtime_reap_step(apply=apply))
    if include_artifact_runs:
        steps.append(artifact_run_reap_step(apply=apply, project=project))
    if include_workspace_compact:
        steps.extend(
            workspace_compact_steps(
                apply=apply,
                project=project,
                subprocess_run=subprocess_run,
            )
        )
    return DiskReapResult(apply=apply, project=project, steps=tuple(steps))


def managed_tmp_reap_step(*, apply: bool) -> DiskReapStep:
    if not apply:
        return DiskReapStep(
            owner="managed_tmp_reaper",
            mode="dry_run",
            summary="would invoke managed temp reaper; it owns age and pressure policy",
            command=("sase", "axe", "chop", "run", "managed_tmp_reap"),
        )
    result = reap_managed_tmpdir()
    return DiskReapStep(
        owner="managed_tmp_reaper",
        mode="apply",
        summary=result.describe(),
        reclaimed_bytes=result.pressure_reclaimed_bytes,
        changed=bool(result.removed),
    )


def proc_runtime_reap_step(*, apply: bool) -> DiskReapStep:
    try:
        preview = sweep_orphan_proc_runtime_dirs(apply=False)
    except Exception as exc:  # noqa: BLE001 - one owner must not crash the group.
        return DiskReapStep(
            owner="proc_runtime_sweep",
            mode="blocked",
            summary=f"could not inspect proc runtime owner: {exc}",
            command=("sase", "disk", "reap", "--apply"),
            exit_code=1,
        )
    if not apply:
        return DiskReapStep(
            owner="proc_runtime_sweep",
            mode="dry_run",
            summary=preview.describe(),
            reclaimed_bytes=preview.reclaimable_bytes,
        )
    try:
        prune_procs()
        result = sweep_orphan_proc_runtime_dirs(apply=True)
    except Exception as exc:  # noqa: BLE001 - report owner failure as a step.
        return DiskReapStep(
            owner="proc_runtime_sweep",
            mode="error",
            summary=f"proc runtime sweep failed: {exc}",
            command=("sase", "disk", "reap", "--apply"),
            exit_code=1,
        )
    return DiskReapStep(
        owner="proc_runtime_sweep",
        mode="apply",
        summary=result.describe(),
        reclaimed_bytes=result.reclaimed_bytes,
        changed=bool(result.removed),
        exit_code=1 if result.errors else None,
    )


def artifact_run_reap_step(*, apply: bool, project: str | None) -> DiskReapStep:
    policy = AceRunRetentionPolicy(
        now=local_now(),
        keep_recent_months=get_artifact_retention_keep_recent_run_months(),
        project=project,
    )
    try:
        protections = collect_ace_run_retention_protections(
            projects_root=policy.projects_root
        )
        plan = plan_ace_run_retention(policy, protections=protections)
    except Exception as exc:  # noqa: BLE001 - one owner must not crash the group.
        return DiskReapStep(
            owner="artifact_run_retention",
            mode="blocked",
            summary=f"could not plan artifact run retention: {exc}",
            command=("sase", "artifact", "prune-runs", "--apply"),
        )
    if plan.sources_unavailable:
        return DiskReapStep(
            owner="artifact_run_retention",
            mode="blocked",
            summary=(
                "protection sources unavailable: " + ", ".join(plan.sources_unavailable)
            ),
            reclaimed_bytes=plan.reclaimable_bytes,
            command=("sase", "artifact", "prune-runs", "--apply"),
        )
    if not apply:
        return DiskReapStep(
            owner="artifact_run_retention",
            mode="dry_run",
            summary=(
                f"would remove {plan.counts.selected} run dir(s) and "
                f"{plan.counts.empty_out_of_range_shards} empty shard(s)"
            ),
            reclaimed_bytes=plan.reclaimable_bytes,
            command=("sase", "artifact", "prune-runs", "--apply"),
        )
    try:
        execution = apply_ace_run_retention(plan)
    except Exception as exc:  # noqa: BLE001 - report owner failure as a step.
        return DiskReapStep(
            owner="artifact_run_retention",
            mode="error",
            summary=f"artifact run retention failed: {exc}",
            reclaimed_bytes=plan.reclaimable_bytes,
            command=("sase", "artifact", "prune-runs", "--apply"),
            exit_code=1,
        )
    return DiskReapStep(
        owner="artifact_run_retention",
        mode="apply",
        summary=(
            f"removed {execution.removed_runs} run dir(s), "
            f"{execution.removed_empty_shards} empty shard(s)"
        ),
        reclaimed_bytes=execution.bytes_reclaimed,
        changed=bool(execution.removed_runs or execution.removed_empty_shards),
    )


def workspace_compact_steps(
    *,
    apply: bool,
    project: str | None,
    subprocess_run: Callable[..., subprocess.CompletedProcess[str]],
) -> tuple[DiskReapStep, ...]:
    projects = (project,) if project else workspace_project_keys()
    steps: list[DiskReapStep] = []
    for project_key in projects:
        command = [
            "sase",
            "workspace",
            "compact",
            "-p",
            project_key,
        ]
        if not apply:
            command.append("-n")
        try:
            completed = subprocess_run(
                command,
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError as exc:
            steps.append(
                DiskReapStep(
                    owner="workspace_compact",
                    mode="error",
                    summary=f"{project_key}: {type(exc).__name__}: {exc}",
                    command=tuple(command),
                    exit_code=1,
                )
            )
            continue
        output = (completed.stdout + completed.stderr).strip()
        steps.append(
            DiskReapStep(
                owner="workspace_compact",
                mode="apply" if apply else "dry_run",
                summary=f"{project_key}: {output.splitlines()[-1] if output else 'no output'}",
                changed=apply and completed.returncode == 0 and "compacted #" in output,
                command=tuple(command),
                exit_code=completed.returncode,
                output=output,
            )
        )
    if not steps:
        return (
            DiskReapStep(
                owner="workspace_compact",
                mode="dry_run" if not apply else "apply",
                summary="no workspace projects found",
            ),
        )
    return tuple(steps)


def workspace_project_keys() -> tuple[str, ...]:
    try:
        inventory = collect_workspace_inventory(include_disabled=False)
    except Exception:
        return ()
    return tuple(project.project_key for project in inventory.projects)


__all__ = [
    "artifact_run_reap_step",
    "managed_tmp_reap_step",
    "proc_runtime_reap_step",
    "run_disk_reap",
    "workspace_compact_steps",
    "workspace_project_keys",
]

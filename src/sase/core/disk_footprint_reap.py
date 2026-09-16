"""Owner-delegated cleanup orchestration for ``sase disk reap``."""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

from sase.config import get_artifact_retention_keep_recent_run_months
from sase.core.agent_artifact_run_retention import (
    AceRunRetentionPolicy,
    apply_ace_run_retention,
    collect_ace_run_retention_protections,
    plan_ace_run_retention,
)
from sase.core.disk_footprint_models import DiskReapResult, DiskReapStep
from sase.core.disk_pressure import filesystem_pressure_policy
from sase.core import managed_tmp_reaper as _managed_tmp_reaper
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
    try:
        return _managed_tmp_reap_step_impl(
            apply=apply,
            filesystem_available_bytes=filesystem_available_bytes,
            pressure_min_available_bytes=pressure_min_available_bytes,
            pressure_recovery_available_bytes=pressure_recovery_available_bytes,
        )
    except Exception as exc:  # noqa: BLE001 - one owner must not crash the group.
        return DiskReapStep(
            owner="managed_tmp_reaper",
            mode="error",
            summary=f"managed tmp cleanup failed: {type(exc).__name__}: {exc}",
            command=("sase", "disk", "reap", "--apply"),
            exit_code=1,
            owner_error=f"{type(exc).__name__}: {exc}",
            byte_accounting_complete=False,
        )


def _managed_tmp_reap_step_impl(
    *,
    apply: bool,
    filesystem_available_bytes: int | None = None,
    pressure_min_available_bytes: int | None = None,
    pressure_recovery_available_bytes: int | None = None,
) -> DiskReapStep:
    root = _current_managed_tmpdir_root()
    if (
        filesystem_available_bytes is None
        or pressure_min_available_bytes is None
        or pressure_recovery_available_bytes is None
    ):
        policy = filesystem_pressure_policy(
            label="managed_tmp",
            role="owner",
            path=root,
        )
        if filesystem_available_bytes is None:
            filesystem_available_bytes = policy.free_bytes
        if pressure_min_available_bytes is None:
            pressure_min_available_bytes = policy.warn_free_bytes
        if pressure_recovery_available_bytes is None:
            pressure_recovery_available_bytes = policy.warn_free_bytes
    result = reap_managed_tmpdir(
        root=root,
        apply=apply,
        filesystem_available_bytes=filesystem_available_bytes,
        pressure_min_available_bytes=pressure_min_available_bytes,
        pressure_recovery_available_bytes=pressure_recovery_available_bytes,
    )
    details = _managed_tmp_details(result)
    return DiskReapStep(
        owner="managed_tmp_reaper",
        mode="apply" if apply else "dry_run",
        summary=result.describe(),
        reclaimed_bytes=result.removed_bytes if apply else result.selected_bytes,
        changed=apply and bool(result.removed),
        exit_code=1 if result.failed else None,
        owner_error=(
            f"managed tmp cleanup reported {result.failed} failure(s)"
            if result.failed
            else None
        ),
        required_observation_unavailable=bool(result.incomplete_observations),
        incomplete_reason=(
            f"{result.incomplete_observations} required observation(s) incomplete"
            if result.incomplete_observations
            else None
        ),
        byte_accounting_complete=not bool(result.incomplete_observations),
        protective_skip=(
            "; ".join(str(reason) for reason in result.skip_reasons)
            if result.skip_reasons
            else None
        ),
        capped=bool(getattr(result, "capped", False)),
        details=details,
    )


def _current_managed_tmpdir_root() -> Path:
    if managed_tmpdir_root is not _paths_managed_tmpdir_root:
        return managed_tmpdir_root()
    return _managed_tmp_reaper.managed_tmpdir_root()


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
        details = _proc_retention_details(preview, phase="orphan_runtime_preview")
        return DiskReapStep(
            owner="proc_runtime_sweep",
            mode="dry_run",
            summary=preview.describe(),
            reclaimed_bytes=preview.reclaimable_bytes,
            exit_code=1 if preview.errors else None,
            owner_error=(
                f"proc runtime preview reported {preview.errors} error(s)"
                if preview.errors
                else None
            ),
            byte_accounting_complete=details["byte_accounting_complete"],
            capped=bool(details["capped"]),
            details=details,
        )
    phase_errors: list[str] = []
    prune_result = None
    log_retention = None
    pruned_runtime = None
    try:
        prune_result = prune_procs()
    except Exception as exc:  # noqa: BLE001 - preserve later independent passes.
        phase_errors.append(f"row prune failed: {type(exc).__name__}: {exc}")
    else:
        log_retention = getattr(prune_result, "log_retention", None)
        pruned_runtime = getattr(prune_result, "runtime_retention", None)
        state_retention = getattr(prune_result, "state_retention", None)
        phase_errors.extend(
            str(error) for error in getattr(state_retention, "errors", ())
        )
    orphan_result = None
    try:
        orphan_result = sweep_orphan_proc_runtime_dirs(apply=True)
    except Exception as exc:  # noqa: BLE001 - report after retaining prior effects.
        phase_errors.append(f"orphan sweep failed: {type(exc).__name__}: {exc}")
    result = _combine_proc_runtime_results(
        log_retention,
        pruned_runtime,
        orphan_result,
        errors=tuple(phase_errors),
    )
    owner_error = (
        "; ".join(phase_errors)
        if phase_errors
        else (
            f"proc cleanup reported {result['errors']} error(s)"
            if result["errors"]
            else None
        )
    )
    return DiskReapStep(
        owner="proc_runtime_sweep",
        mode="apply",
        summary=_proc_runtime_summary(
            log_retention=log_retention,
            pruned_runtime=pruned_runtime,
            orphan_result=orphan_result,
            errors=tuple(phase_errors),
        ),
        reclaimed_bytes=result["reclaimed_bytes"],
        changed=bool(result["removed"]),
        exit_code=1 if result["errors"] else None,
        owner_error=owner_error,
        byte_accounting_complete=result["byte_accounting_complete"],
        incomplete_reason=(
            "proc cleanup byte accounting incomplete"
            if not result["byte_accounting_complete"]
            else None
        ),
        capped=bool(result["capped"]),
        details=result,
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
    if plan.sources_unavailable and not apply:
        return DiskReapStep(
            owner="artifact_run_retention",
            mode="blocked",
            summary=(
                "protection sources unavailable: " + ", ".join(plan.sources_unavailable)
            ),
            reclaimed_bytes=plan.reclaimable_bytes,
            command=("sase", "artifact", "prune-runs", "--apply"),
            exit_code=1,
            details={"sources_unavailable": list(plan.sources_unavailable)},
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
            details={
                "selected_runs": plan.counts.selected,
                "empty_out_of_range_shards": plan.counts.empty_out_of_range_shards,
                "sources_unavailable": list(plan.sources_unavailable),
            },
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
    details = {
        "removed_runs": execution.removed_runs,
        "removed_empty_shards": execution.removed_empty_shards,
        "bytes_reclaimed": execution.bytes_reclaimed,
        "deindexed": execution.deindexed,
        "skipped": list(execution.skipped),
        "errors": list(execution.errors),
        "preview_reclaimable_bytes": plan.reclaimable_bytes,
        "sources_unavailable": list(plan.sources_unavailable),
    }
    if execution.errors:
        return DiskReapStep(
            owner="artifact_run_retention",
            mode="blocked",
            summary="; ".join(execution.errors),
            reclaimed_bytes=execution.bytes_reclaimed,
            changed=bool(execution.removed_runs or execution.removed_empty_shards),
            command=("sase", "artifact", "prune-runs", "--apply"),
            exit_code=1,
            blocked_reason="; ".join(execution.errors),
            details=details,
        )
    return DiskReapStep(
        owner="artifact_run_retention",
        mode="apply",
        summary=_artifact_execution_summary(execution),
        reclaimed_bytes=execution.bytes_reclaimed,
        changed=bool(execution.removed_runs or execution.removed_empty_shards),
        command=("sase", "artifact", "prune-runs", "--apply"),
        details=details,
    )


def workspace_compact_steps(
    *,
    apply: bool,
    project: str | None,
    subprocess_run: Callable[..., subprocess.CompletedProcess[str]],
    timeout_seconds: float = 120.0,
) -> tuple[DiskReapStep, ...]:
    projects: tuple[str, ...]
    if project:
        projects = (project,)
    else:
        try:
            inventory = collect_workspace_inventory(include_disabled=False)
        except Exception as exc:  # noqa: BLE001 - one owner must not crash the group.
            return (
                DiskReapStep(
                    owner="workspace_compact",
                    mode="error",
                    summary=(
                        f"workspace discovery failed: {type(exc).__name__}: {exc}"
                    ),
                    command=("sase", "workspace", "compact", "--json"),
                    exit_code=1,
                    owner_error=f"{type(exc).__name__}: {exc}",
                    byte_accounting_complete=False,
                ),
            )
        projects = tuple(project.project_key for project in inventory.projects)
    steps: list[DiskReapStep] = []
    for project_key in projects:
        command = [
            "sase",
            "workspace",
            "compact",
            "-p",
            project_key,
            "--json",
        ]
        if not apply:
            command.append("-n")
        try:
            completed = subprocess_run(
                command,
                capture_output=True,
                text=True,
                check=False,
                timeout=timeout_seconds,
            )
        except OSError as exc:
            steps.append(
                DiskReapStep(
                    owner="workspace_compact",
                    mode="error",
                    summary=f"{project_key}: {type(exc).__name__}: {exc}",
                    command=tuple(command),
                    exit_code=1,
                    owner_error=f"{type(exc).__name__}: {exc}",
                    byte_accounting_complete=False,
                )
            )
            continue
        except subprocess.TimeoutExpired as exc:
            output = _timeout_output(exc)
            steps.append(
                DiskReapStep(
                    owner="workspace_compact",
                    mode="error",
                    summary=f"{project_key}: timed out after {timeout_seconds:g}s",
                    command=tuple(command),
                    exit_code=124,
                    output=output,
                    owner_error=f"timed out after {timeout_seconds:g}s",
                    byte_accounting_complete=False,
                    details={
                        "project": project_key,
                        "timeout_seconds": timeout_seconds,
                    },
                )
            )
            continue
        output = (completed.stdout + completed.stderr).strip()
        payload = _workspace_compact_payload(completed.stdout)
        if payload is None:
            steps.append(
                DiskReapStep(
                    owner="workspace_compact",
                    mode="error",
                    summary=f"{project_key}: invalid workspace compact JSON",
                    command=tuple(command),
                    exit_code=completed.returncode or 1,
                    output=output,
                    invalid_result="invalid workspace compact JSON",
                    byte_accounting_complete=False,
                    details={"project": project_key},
                )
            )
            continue
        parsed = _workspace_compact_fields(payload)
        if isinstance(parsed, str):
            steps.append(
                DiskReapStep(
                    owner="workspace_compact",
                    mode="error",
                    summary=f"{project_key}: invalid workspace compact result: {parsed}",
                    command=tuple(command),
                    exit_code=completed.returncode or 1,
                    output=output,
                    invalid_result=parsed,
                    byte_accounting_complete=False,
                    details={"project": project_key, "payload": payload},
                )
            )
            continue
        rows, failed, reclaimed, changed = parsed
        owner_error = (
            f"workspace compact reported {failed} error(s)" if failed else None
        )
        steps.append(
            DiskReapStep(
                owner="workspace_compact",
                mode="apply" if apply else "dry_run",
                summary=_workspace_compact_summary(
                    project_key,
                    rows=rows,
                    apply=apply,
                    failed=failed,
                    reclaimed_bytes=reclaimed,
                ),
                reclaimed_bytes=reclaimed,
                changed=apply and changed,
                command=tuple(command),
                exit_code=completed.returncode,
                output=output,
                owner_error=owner_error,
                byte_accounting_complete=True,
                details=payload,
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


def _managed_tmp_details(result: Any) -> dict[str, Any]:
    return {
        "root": str(result.root),
        "scanned": result.scanned,
        "selected": result.selected,
        "removed": result.removed,
        "selected_bytes": result.selected_bytes,
        "removed_bytes": result.removed_bytes,
        "ordinary_selected": result.ordinary_selected,
        "ordinary_removed": result.ordinary_removed,
        "ordinary_reclaimable_bytes": result.ordinary_reclaimable_bytes,
        "ordinary_reclaimed_bytes": result.ordinary_reclaimed_bytes,
        "launch_selected": result.launch_selected,
        "launch_removed": result.launch_removed,
        "launch_reclaimable_bytes": result.launch_reclaimable_bytes,
        "launch_reclaimed_bytes": result.launch_reclaimed_bytes,
        "pressure_selected": result.pressure_selected,
        "pressure_removed": result.pressure_removed,
        "pressure_reclaimable_bytes": result.pressure_reclaimable_bytes,
        "pressure_reclaimed_bytes": result.pressure_reclaimed_bytes,
        "pressure_trigger": result.pressure_trigger,
        "pressure_root_size_bytes": result.pressure_root_size_bytes,
        "pressure_available_bytes": result.pressure_available_bytes,
        "pressure_recovery_available_bytes": result.pressure_recovery_available_bytes,
        "pressure_effective_min_age_seconds": (
            result.pressure_effective_min_age_seconds
        ),
        "skipped": result.skipped,
        "failed": result.failed,
        "incomplete_observations": result.incomplete_observations,
        "skip_reasons": list(result.skip_reasons),
        "removal_errors": list(result.removal_errors),
    }


def _proc_retention_details(result: Any, *, phase: str) -> dict[str, Any]:
    root = getattr(result, "runtime_root", None)
    log_root = getattr(result, "log_root", None)
    entries = getattr(result, "entries", ())
    details = {
        "phase": phase,
        "apply": bool(getattr(result, "apply", False)),
        "scanned": int(getattr(result, "scanned", 0)),
        "selected": int(getattr(result, "selected", 0)),
        "removed": int(getattr(result, "removed", 0)),
        "skipped": int(getattr(result, "skipped", 0)),
        "errors": int(getattr(result, "errors", 0)),
        "reclaimable_bytes": int(getattr(result, "reclaimable_bytes", 0)),
        "reclaimed_bytes": int(getattr(result, "reclaimed_bytes", 0)),
        "byte_accounting_complete": bool(
            getattr(result, "byte_accounting_complete", True)
        ),
        "capped": bool(getattr(result, "capped", False)),
        "entries": [
            entry.to_dict() if hasattr(entry, "to_dict") else entry for entry in entries
        ],
    }
    if root is not None:
        details["runtime_root"] = str(root)
    if log_root is not None:
        details["log_root"] = str(log_root)
    return details


def _combine_proc_runtime_results(
    *results: Any,
    errors: tuple[str, ...] = (),
) -> dict[str, Any]:
    phase_names = (
        "pruned_logs",
        "pruned_row_runtime",
        "orphan_runtime",
    )
    details = [
        _proc_retention_details(result, phase=phase_names[index])
        for index, result in enumerate(results)
        if result is not None
    ]
    error_count = sum(int(detail["errors"]) for detail in details) + len(errors)
    byte_accounting_complete = all(
        bool(detail["byte_accounting_complete"]) for detail in details
    )
    return {
        "phases": details,
        "scanned": sum(int(detail["scanned"]) for detail in details),
        "selected": sum(int(detail["selected"]) for detail in details),
        "removed": sum(int(detail["removed"]) for detail in details),
        "skipped": sum(int(detail["skipped"]) for detail in details),
        "errors": error_count,
        "error_details": list(errors),
        "reclaimable_bytes": sum(
            int(detail["reclaimable_bytes"]) for detail in details
        ),
        "reclaimed_bytes": sum(int(detail["reclaimed_bytes"]) for detail in details),
        "byte_accounting_complete": byte_accounting_complete,
        "capped": any(bool(detail["capped"]) for detail in details),
    }


def _proc_runtime_summary(
    *,
    log_retention: Any,
    pruned_runtime: Any,
    orphan_result: Any,
    errors: tuple[str, ...] = (),
) -> str:
    combined = _combine_proc_runtime_results(
        log_retention,
        pruned_runtime,
        orphan_result,
        errors=errors,
    )
    suffixes = []
    if log_retention is not None and log_retention.removed:
        suffixes.append(f"logs={log_retention.removed}")
    if pruned_runtime is not None and pruned_runtime.removed:
        suffixes.append(f"row-pruned={pruned_runtime.removed}")
    if orphan_result is not None and orphan_result.removed:
        suffixes.append(f"orphans={orphan_result.removed}")
    if combined["errors"]:
        suffixes.append(f"errors={combined['errors']}")
    if not combined["byte_accounting_complete"]:
        suffixes.append("byte-accounting=incomplete")
    suffix = "; " + ", ".join(suffixes) if suffixes else ""
    return (
        f"removed {combined['removed']} proc cleanup artifact(s); "
        f"scanned={combined['scanned']}, "
        f"reclaimable={combined['reclaimable_bytes']}, "
        f"reclaimed={combined['reclaimed_bytes']}{suffix}"
    )


def _artifact_execution_summary(execution: Any) -> str:
    suffix = ""
    if execution.skipped:
        suffix += f", skipped {len(execution.skipped)}"
    if execution.errors:
        suffix += f", errors {len(execution.errors)}"
    return (
        f"removed {execution.removed_runs} run dir(s), "
        f"{execution.removed_empty_shards} empty shard(s){suffix}"
    )


def _timeout_output(exc: subprocess.TimeoutExpired) -> str:
    stdout = exc.stdout or ""
    stderr = exc.stderr or ""
    if isinstance(stdout, bytes):
        stdout = stdout.decode(errors="replace")
    if isinstance(stderr, bytes):
        stderr = stderr.decode(errors="replace")
    return (str(stdout) + str(stderr)).strip()


def _workspace_compact_fields(
    payload: dict[str, Any],
) -> tuple[tuple[dict[str, Any], ...], int, int, bool] | str:
    raw_rows = payload.get("rows", ())
    if raw_rows is None:
        raw_rows = ()
    if not isinstance(raw_rows, list | tuple):
        return "rows must be a list"
    rows: list[dict[str, Any]] = []
    for index, row in enumerate(raw_rows):
        if not isinstance(row, dict):
            return f"rows[{index}] must be an object"
        rows.append(row)
    errors = _nonnegative_int_field(payload, "errors", default=0)
    if isinstance(errors, str):
        return errors
    reclaimed = _nonnegative_int_field(payload, "reclaimed_bytes", default=0)
    if isinstance(reclaimed, str):
        return reclaimed
    changed = _bool_field(payload, "changed", default=False)
    if isinstance(changed, str):
        return changed
    return (tuple(rows), errors, reclaimed, changed)


def _nonnegative_int_field(
    payload: dict[str, Any],
    name: str,
    *,
    default: int,
) -> int | str:
    value = payload.get(name, default)
    if value is None:
        value = default
    if isinstance(value, bool) or not isinstance(value, int):
        return f"{name} must be an integer"
    if value < 0:
        return f"{name} must be nonnegative"
    return value


def _bool_field(
    payload: dict[str, Any],
    name: str,
    *,
    default: bool,
) -> bool | str:
    value = payload.get(name, default)
    if value is None:
        value = default
    if not isinstance(value, bool):
        return f"{name} must be a boolean"
    return value


def _workspace_compact_payload(stdout: str) -> dict[str, Any] | None:
    import json

    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _workspace_compact_summary(
    project_key: str,
    *,
    rows: tuple[dict[str, Any], ...],
    apply: bool,
    failed: int,
    reclaimed_bytes: int,
) -> str:
    planned = sum(1 for row in rows if row.get("status") in {"planned", "compacted"})
    skipped = sum(1 for row in rows if row.get("status") == "skipped")
    verb = "compacted" if apply else "would compact"
    pieces = [f"{project_key}: {verb} {planned} checkout(s)"]
    pieces.append(f"skipped={skipped}")
    pieces.append(f"failed={failed}")
    pieces.append(f"reclaimed={reclaimed_bytes}")
    return "; ".join(pieces)


__all__ = [
    "artifact_run_reap_step",
    "managed_tmp_reap_step",
    "proc_runtime_reap_step",
    "run_disk_reap",
    "workspace_compact_steps",
    "workspace_project_keys",
]

"""JSON payload builders for ``sase update``."""

from __future__ import annotations

from typing import Any

from sase.dev_update import (
    DevReconcileStep,
    DevUpdateOutcome,
    DevUpdatePackagePlan,
    DevUpdatePlan,
    DevUpdateResult,
    DevUpdateRootPlan,
)
from sase.main.update_state import combined_changed, dev_counts
from sase.main.update_types import UPDATE_JSON_SCHEMA_VERSION, RestartInfo
from sase.uv_tool.render import PlannedPackage, UpdateOutcome, UpdateSummary


def _outcome_json(outcome: UpdateOutcome) -> dict[str, Any]:
    return {
        "name": outcome.name,
        "role": outcome.role,
        "kind": outcome.kind.value,
        "old_version": outcome.old_version,
        "new_version": outcome.new_version,
    }


def dry_run_json(
    argv: list[str],
    packages: tuple[PlannedPackage, ...],
    *,
    mode: str = "managed",
    dev_plan: DevUpdatePlan | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": UPDATE_JSON_SCHEMA_VERSION,
        "dry_run": True,
        "mode": mode,
        "command": list(argv),
        "packages": [
            {
                "name": package.name,
                "role": package.role,
                "current_version": package.current_version,
            }
            for package in packages
        ],
        "managed": {
            "command": list(argv),
            "packages": [
                {
                    "name": package.name,
                    "role": package.role,
                    "current_version": package.current_version,
                }
                for package in packages
            ],
        }
        if argv
        else None,
        "dev": _dev_plan_json(dev_plan) if dev_plan is not None else None,
    }


def combined_result_json(
    *,
    mode: str,
    managed_argv: list[str],
    managed_summary: UpdateSummary | None,
    dev_plan: DevUpdatePlan | None,
    dev_result: DevUpdateResult | None,
    elapsed: float,
    restart: RestartInfo,
) -> dict[str, Any]:
    changed = combined_changed(dev_result, managed_summary)
    return {
        "schema_version": UPDATE_JSON_SCHEMA_VERSION,
        "dry_run": False,
        "mode": mode,
        "command": list(managed_argv),
        "changed": changed,
        "elapsed_seconds": round(elapsed, 3),
        "counts": _combined_counts(dev_result, managed_summary),
        "packages": _combined_package_json(dev_result, managed_summary),
        "managed": _managed_result_json(managed_argv, managed_summary)
        if managed_summary is not None
        else None,
        "dev": _dev_result_json(dev_plan, dev_result)
        if dev_result is not None or dev_plan is not None
        else None,
        "restart": restart_info_json(restart),
    }


def _managed_result_json(
    argv: list[str], summary: UpdateSummary | None
) -> dict[str, Any]:
    if summary is None:
        return {"command": list(argv), "changed": False, "packages": []}
    return {
        "command": list(argv),
        "changed": summary.changed,
        "counts": {
            "updated": len(summary.updated),
            "already_current": len(summary.already_current),
            "removed": len(summary.removed),
        },
        "packages": [_outcome_json(outcome) for outcome in summary.outcomes],
    }


def _dev_plan_json(plan: DevUpdatePlan | None) -> dict[str, Any] | None:
    if plan is None:
        return None
    return {
        "packages": [_dev_package_plan_json(package) for package in plan.packages],
        "roots": [_dev_root_plan_json(root) for root in plan.roots],
        "reconcile_steps": [
            _dev_reconcile_step_json(step) for step in plan.reconcile_steps
        ],
    }


def _dev_result_json(
    plan: DevUpdatePlan | None, result: DevUpdateResult | None
) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    if plan is not None:
        payload["plan"] = _dev_plan_json(plan)
    if result is not None:
        payload.update(
            {
                "changed": result.changed,
                "duration_seconds": round(result.duration_seconds, 3),
                "counts": dev_counts(result),
                "packages": [_dev_outcome_json(outcome) for outcome in result.outcomes],
                "commands": [_dev_command_json(command) for command in result.commands],
            }
        )
    return payload


def _dev_package_plan_json(package: DevUpdatePackagePlan) -> dict[str, Any]:
    return {
        "name": package.record.name,
        "role": package.record.role,
        "status": package.status,
        "reason": package.reason,
        "current_version": package.current_version,
        "latest_version": package.latest_version,
        "git_root": package.git_root,
        "upstream": package.upstream,
        "ahead": package.ahead,
        "behind": package.behind,
        "fetch_error": package.fetch_error,
    }


def _dev_root_plan_json(root: DevUpdateRootPlan) -> dict[str, Any]:
    return {
        "git_root": root.git_root,
        "status": root.status,
        "reason": root.reason,
        "upstream": root.upstream,
        "remote": root.remote,
        "remote_branch": root.remote_branch,
        "packages": list(root.packages),
        "ahead": root.ahead,
        "behind": root.behind,
        "fetch_error": root.fetch_error,
    }


def _dev_reconcile_step_json(step: DevReconcileStep) -> dict[str, Any]:
    return {
        "kind": step.kind,
        "label": step.label,
        "command": list(step.command),
        "cwd": step.cwd,
        "available": step.available,
        "reason": step.reason,
        "repair_command": list(step.repair_command),
        "repair_cwd": step.repair_cwd,
        "repair_label": step.repair_label,
        "repair_reason": step.repair_reason,
    }


def _dev_outcome_json(outcome: DevUpdateOutcome) -> dict[str, Any]:
    return {
        "name": outcome.record.name,
        "role": outcome.record.role,
        "status": outcome.status,
        "reason": outcome.reason,
        "old_version": outcome.old_version,
        "new_version": outcome.new_version,
        "git_root": outcome.git_root,
    }


def _dev_command_json(command: Any) -> dict[str, Any]:
    return {
        "label": command.label,
        "command": list(command.command),
        "cwd": command.cwd,
        "returncode": command.returncode,
        "duration_seconds": round(float(command.duration_seconds or 0.0), 3),
        "stdout": command.stdout,
        "stderr": command.stderr,
    }


def _combined_counts(
    dev_result: DevUpdateResult | None, managed_summary: UpdateSummary | None
) -> dict[str, int]:
    managed_updated = len(managed_summary.updated) if managed_summary else 0
    managed_current = len(managed_summary.already_current) if managed_summary else 0
    managed_removed = len(managed_summary.removed) if managed_summary else 0
    if dev_result is None:
        return {
            "updated": managed_updated,
            "already_current": managed_current,
            "removed": managed_removed,
        }
    counts = dev_counts(dev_result) if dev_result else {}
    return {
        "updated": managed_updated + int(counts.get("updated", 0)),
        "already_current": managed_current,
        "removed": managed_removed,
        "skipped": int(counts.get("skipped", 0)),
        "failed": int(counts.get("failed", 0)),
    }


def _combined_package_json(
    dev_result: DevUpdateResult | None, managed_summary: UpdateSummary | None
) -> list[dict[str, Any]]:
    packages: list[dict[str, Any]] = []
    if dev_result is not None:
        packages.extend(_dev_outcome_json(outcome) for outcome in dev_result.outcomes)
    if managed_summary is not None:
        packages.extend(_outcome_json(outcome) for outcome in managed_summary.outcomes)
    return packages


def restart_info_json(restart: RestartInfo) -> dict[str, Any]:
    return {
        "attempted": restart.attempted,
        "status": restart.status,
        "pid": restart.pid,
        "message": restart.message,
        "reason": restart.reason,
    }


_restart_json = restart_info_json

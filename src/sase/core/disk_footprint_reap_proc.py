"""Proc runtime owner step for ``sase disk reap``."""

from __future__ import annotations

from typing import Any

from sase.core.disk_footprint_models import DiskReapStep
from sase.procs.runtime import sweep_orphan_proc_runtime_dirs
from sase.procs.store import prune_procs


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


__all__ = ["proc_runtime_reap_step"]

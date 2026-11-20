"""Agent-name registry temp-file owner step for ``sase disk reap``."""

from __future__ import annotations

from typing import Any

from sase.agent.names._registry_store import (
    registry_path,
    sweep_stale_registry_tmp_files,
)
from sase.config.core import (
    get_agent_name_registry_tmp_horizon_seconds,
    get_agent_name_registry_tmp_max_removals,
)
from sase.core.disk_footprint_models import DiskReapStep

#: Owner name shared by the inventory row, the reap step, and pressure notices.
REGISTRY_TMP_SWEEP_OWNER = "registry_tmp_sweep"


def registry_tmp_reap_step(*, apply: bool) -> DiskReapStep:
    """Preview or apply the stale registry temp-file sweep.

    The sweep itself is age-gated: temp files younger than the horizon are
    always kept, which protects the dump an active writer is producing. The
    registry writer runs the same sweep under the mutation lock before every
    write; this owner reaps the backlog the hourly retention chop applies.
    """
    try:
        path = registry_path()
        result = sweep_stale_registry_tmp_files(
            path,
            max_age_seconds=get_agent_name_registry_tmp_horizon_seconds(),
            max_removals=get_agent_name_registry_tmp_max_removals(),
            apply=apply,
        )
    except Exception as exc:  # noqa: BLE001 - one owner must not crash the group.
        return DiskReapStep(
            owner=REGISTRY_TMP_SWEEP_OWNER,
            mode="blocked",
            summary=f"could not sweep registry temp files: {exc}",
            command=("sase", "disk", "reap", "--apply"),
            exit_code=1,
        )
    if not apply:
        capped = " (removal budget reached)" if result.capped else ""
        return DiskReapStep(
            owner=REGISTRY_TMP_SWEEP_OWNER,
            mode="dry_run",
            summary=(
                f"would remove {result.selected} stale registry temp file(s)"
                f"{capped}; scanned={result.scanned}, "
                f"reclaimable={result.reclaimable_bytes}"
            ),
            reclaimed_bytes=result.reclaimable_bytes,
            exit_code=1 if result.errors else None,
            owner_error="; ".join(result.errors) if result.errors else None,
            byte_accounting_complete=not result.errors,
            capped=result.capped,
            details=_result_details(result, phase="registry_tmp_preview"),
        )
    capped = " (removal budget reached)" if result.capped else ""
    summary = (
        f"removed {result.removed} stale registry temp file(s){capped}; "
        f"scanned={result.scanned}, reclaimed={result.reclaimed_bytes}"
    )
    if result.errors:
        summary += f"; errors={len(result.errors)}"
    return DiskReapStep(
        owner=REGISTRY_TMP_SWEEP_OWNER,
        mode="apply",
        summary=summary,
        reclaimed_bytes=result.reclaimed_bytes,
        changed=bool(result.removed),
        exit_code=1 if result.errors else None,
        owner_error="; ".join(result.errors) if result.errors else None,
        byte_accounting_complete=not result.errors,
        capped=result.capped,
        details=_result_details(result, phase="registry_tmp_apply"),
    )


def _result_details(result: Any, *, phase: str) -> dict[str, Any]:
    errors = list(result.errors)
    return {
        "phase": phase,
        "apply": phase.endswith("apply"),
        "scanned": result.scanned,
        "selected": result.selected,
        "removed": result.removed,
        "skipped": result.skipped,
        "errors": len(errors),
        "error_details": errors,
        "reclaimable_bytes": result.reclaimable_bytes,
        "reclaimed_bytes": result.reclaimed_bytes,
        "capped": bool(result.capped),
        "paths": list(result.paths),
    }


__all__ = [
    "REGISTRY_TMP_SWEEP_OWNER",
    "registry_tmp_reap_step",
]

"""Disk capacity checks for ``sase doctor`` resources."""

from __future__ import annotations

import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol, TYPE_CHECKING

from sase.config import (
    get_disk_pressure_error_free_percent,
    get_disk_pressure_top_owner_min_bytes,
    get_disk_pressure_warn_free_percent,
)
from sase.config.core import load_merged_config
from sase.diagnostics import CheckStatus, DiagnosticCheck
from sase.workspace_provider.store import WorkspaceStore

if TYPE_CHECKING:
    from sase.doctor.runner import DoctorContext

_GIB = 1024**3
_DISK_ERROR_FREE_BYTES = _GIB
_DISK_WARN_FREE_BYTES = 3 * _GIB
_DISK_ERROR_FREE_PERCENT = 1.0
_DISK_WARN_FREE_PERCENT = 5.0


class _DiskUsage(Protocol):
    @property
    def total(self) -> int: ...

    @property
    def used(self) -> int: ...

    @property
    def free(self) -> int: ...


type _DiskUsageFn = Callable[[str], _DiskUsage]
type _WorkspaceRootFn = Callable[["DoctorContext"], tuple[Path | None, str | None]]


def check_disk_free(
    context: DoctorContext,
    *,
    disk_usage_fn: _DiskUsageFn | None = None,
    workspace_root_fn: _WorkspaceRootFn | None = None,
) -> DiagnosticCheck:
    """Check free space where managed workspaces and SASE state live."""
    if disk_usage_fn is None:
        disk_usage_fn = _disk_usage
    if workspace_root_fn is None:
        workspace_root_fn = workspace_root_path

    workspace_root, workspace_error = workspace_root_fn(context)
    if workspace_error is not None or workspace_root is None:
        return DiagnosticCheck(
            id="resources.disk_free",
            group="resources",
            status="ERROR",
            title="Free disk space",
            summary="workspace root free space could not be checked",
            details=(workspace_error or "workspace root was not resolved",),
            next_steps=("Fix workspace root configuration, then rerun `sase doctor`.",),
            data={
                "paths": (),
                "workspace_error": workspace_error,
                "error_threshold_bytes": _DISK_ERROR_FREE_BYTES,
                "warn_threshold_bytes": _DISK_WARN_FREE_BYTES,
            },
        )

    thresholds = _disk_thresholds()
    rows = (
        _disk_target(
            "workspace_root",
            "primary",
            workspace_root,
            disk_usage_fn,
            thresholds=thresholds,
        ),
        _disk_target(
            "sase_home",
            "secondary",
            context.sase_home,
            disk_usage_fn,
            thresholds=thresholds,
        ),
    )
    status = _aggregate_disk_status(rows)
    problem_rows = tuple(row for row in rows if row["status"] != "OK")
    worst = _worst_disk_row(rows)

    return DiagnosticCheck(
        id="resources.disk_free",
        group="resources",
        status=status,
        title="Free disk space",
        summary=_disk_summary(status, worst, len(rows)),
        details=tuple(_disk_detail(row) for row in rows),
        next_steps=_disk_next_steps() if problem_rows else (),
        data={
            "paths": rows,
            "workspace_error": None,
            "error_threshold_bytes": _DISK_ERROR_FREE_BYTES,
            "warn_threshold_bytes": _DISK_WARN_FREE_BYTES,
            "error_threshold_percent": thresholds["error_percent"],
            "warn_threshold_percent": thresholds["warn_percent"],
        },
    )


_check_disk_free = check_disk_free


def workspace_root_path(context: DoctorContext) -> tuple[Path | None, str | None]:
    try:
        config = load_merged_config()
        store = WorkspaceStore(
            str(context.cwd),
            config=config,
            env=context.env,
        )
    except Exception as exc:  # noqa: BLE001 - report config/root resolution failures.
        return None, f"{type(exc).__name__}: {exc}"
    return Path(store.root_dir), None


def _disk_usage(path: str) -> _DiskUsage:
    return shutil.disk_usage(path)


def _disk_target(
    label: str,
    role: str,
    path: Path,
    disk_usage_fn: _DiskUsageFn,
    *,
    thresholds: dict[str, float],
) -> dict[str, Any]:
    expanded = path.expanduser()
    measured_path = _nearest_existing_parent(expanded)
    if measured_path is None:
        return {
            "label": label,
            "role": role,
            "path": str(expanded),
            "measurement_path": None,
            "status": "ERROR",
            "problem": f"{expanded} has no existing parent path to inspect",
        }

    try:
        usage = disk_usage_fn(str(measured_path))
    except OSError as exc:
        return {
            "label": label,
            "role": role,
            "path": str(expanded),
            "measurement_path": str(measured_path),
            "status": "ERROR",
            "problem": f"{type(exc).__name__}: {exc}",
        }

    free_bytes = int(usage.free)
    total_bytes = int(usage.total)
    status = _free_space_status(
        free_bytes,
        total_bytes=total_bytes,
        thresholds=thresholds,
    )
    problem = None
    if status == "ERROR":
        problem = _threshold_problem(
            label,
            "error",
            free_bytes=free_bytes,
            total_bytes=total_bytes,
            thresholds=thresholds,
        )
    elif status == "WARN":
        problem = _threshold_problem(
            label,
            "warn",
            free_bytes=free_bytes,
            total_bytes=total_bytes,
            thresholds=thresholds,
        )

    return {
        "label": label,
        "role": role,
        "path": str(expanded),
        "measurement_path": str(measured_path),
        "status": status,
        "problem": problem,
        "total_bytes": total_bytes,
        "used_bytes": int(usage.used),
        "free_bytes": free_bytes,
        "free_gib": round(free_bytes / _GIB, 2),
        "free_percent": _free_percent(free_bytes, total_bytes),
        "error_threshold_bytes_effective": int(thresholds["error_bytes"]),
        "warn_threshold_bytes_effective": int(thresholds["warn_bytes"]),
    }


def _disk_thresholds() -> dict[str, float]:
    warn_percent = get_disk_pressure_warn_free_percent()
    error_percent = get_disk_pressure_error_free_percent()
    if warn_percent < error_percent:
        warn_percent = error_percent
    return {
        "error_percent": error_percent,
        "warn_percent": warn_percent,
        "error_bytes": float(_DISK_ERROR_FREE_BYTES),
        "warn_bytes": float(_DISK_WARN_FREE_BYTES),
    }


def _effective_threshold_bytes(
    total_bytes: int,
    *,
    absolute_bytes: float,
    percent: float,
) -> int:
    proportional = int(total_bytes * (percent / 100.0))
    return max(int(absolute_bytes), proportional)


def _free_space_status(
    free_bytes: int,
    *,
    total_bytes: int,
    thresholds: dict[str, float],
) -> CheckStatus:
    error_bytes = _effective_threshold_bytes(
        total_bytes,
        absolute_bytes=thresholds["error_bytes"],
        percent=thresholds["error_percent"],
    )
    warn_bytes = _effective_threshold_bytes(
        total_bytes,
        absolute_bytes=thresholds["warn_bytes"],
        percent=thresholds["warn_percent"],
    )
    if free_bytes < error_bytes:
        return "ERROR"
    if free_bytes < warn_bytes:
        return "WARN"
    return "OK"


def _aggregate_disk_status(rows: tuple[dict[str, Any], ...]) -> CheckStatus:
    statuses = {row["status"] for row in rows}
    if "ERROR" in statuses:
        return "ERROR"
    if "WARN" in statuses:
        return "WARN"
    return "OK"


def _worst_disk_row(rows: tuple[dict[str, Any], ...]) -> dict[str, Any]:
    severity = {"ERROR": 2, "WARN": 1, "OK": 0}
    return max(
        rows,
        key=lambda row: (severity[row["status"]], -row.get("free_bytes", 0)),
    )


def _disk_summary(status: CheckStatus, row: dict[str, Any], path_count: int) -> str:
    label = str(row["label"])
    free_bytes = row.get("free_bytes")
    if status == "ERROR":
        if isinstance(free_bytes, int):
            return str(row.get("problem") or f"{label} free space is critically low")
        return f"{label} free space could not be checked"
    if status == "WARN":
        if not isinstance(free_bytes, int):
            return f"{label} free space could not be checked"
        return str(row.get("problem") or f"{label} free space is low")
    return f"{path_count} resource path(s) have ample free space"


def _disk_detail(row: dict[str, Any]) -> str:
    problem = row.get("problem")
    if problem:
        return str(problem)
    free_bytes = int(row["free_bytes"])
    return (
        f"{row['label']}: {_format_bytes(free_bytes)} free at "
        f"{row['measurement_path']} (path: {row['path']})"
    )


def _disk_next_steps() -> tuple[str, ...]:
    steps = [
        "Run `sase disk list` to inspect SASE-owned and unowned disk usage.",
        "Run `sase disk reap` to preview owner cleanup passes; add `--apply` only when the plan looks right.",
    ]
    try:
        from sase.core.disk_footprint import format_bytes, largest_unowned_rows

        rows = largest_unowned_rows(
            min_bytes=get_disk_pressure_top_owner_min_bytes(),
            limit=3,
        )
    except Exception:
        rows = ()
    if rows:
        detail = ", ".join(f"{format_bytes(row.size_bytes)} {row.path}" for row in rows)
        steps.append(f"Largest unowned SASE-shaped paths: {detail}.")
    else:
        steps.append(
            "Live workspaces can consume hundreds of MB to over 1 GB after checkout and `.venv` creation."
        )
    return tuple(steps)


def _threshold_problem(
    label: str,
    severity: str,
    *,
    free_bytes: int,
    total_bytes: int,
    thresholds: dict[str, float],
) -> str:
    if severity == "error":
        percent = thresholds["error_percent"]
        absolute = _DISK_ERROR_FREE_BYTES
    else:
        percent = thresholds["warn_percent"]
        absolute = _DISK_WARN_FREE_BYTES
    effective = _effective_threshold_bytes(
        total_bytes,
        absolute_bytes=absolute,
        percent=percent,
    )
    basis = f"{percent:g}%" if effective > absolute else f"{absolute // _GIB} GB"
    return (
        f"{label} has less than {basis} free "
        f"({_format_bytes(free_bytes)} available, "
        f"{_free_percent(free_bytes, total_bytes):.1f}% of volume)"
    )


def _free_percent(free_bytes: int, total_bytes: int) -> float:
    if total_bytes <= 0:
        return 0.0
    return round((free_bytes / total_bytes) * 100.0, 3)


def _format_bytes(value: int) -> str:
    if value >= _GIB:
        return f"{value / _GIB:.1f} GiB"
    return f"{value / (1024**2):.0f} MiB"


def _nearest_existing_parent(path: Path) -> Path | None:
    for candidate in (path, *path.parents):
        if candidate.exists():
            return candidate if candidate.is_dir() else candidate.parent
    return None

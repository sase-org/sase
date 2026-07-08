"""Disk capacity checks for ``sase doctor`` resources."""

from __future__ import annotations

import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol, TYPE_CHECKING

from sase.config.core import load_merged_config
from sase.diagnostics import CheckStatus, DiagnosticCheck
from sase.workspace_provider.store import WorkspaceStore

if TYPE_CHECKING:
    from sase.doctor.runner import DoctorContext

_GIB = 1024**3
_DISK_ERROR_FREE_BYTES = _GIB
_DISK_WARN_FREE_BYTES = 3 * _GIB


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
        workspace_root_fn = _workspace_root_path

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

    rows = (
        _disk_target("workspace_root", "primary", workspace_root, disk_usage_fn),
        _disk_target("sase_home", "secondary", context.sase_home, disk_usage_fn),
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
        },
    )


_check_disk_free = check_disk_free


def _workspace_root_path(context: DoctorContext) -> tuple[Path | None, str | None]:
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
    status = _free_space_status(free_bytes)
    problem = None
    if status == "ERROR":
        problem = (
            f"{label} has less than 1 GB free ({_format_bytes(free_bytes)} available)"
        )
    elif status == "WARN":
        problem = (
            f"{label} has less than 3 GB free ({_format_bytes(free_bytes)} available)"
        )

    return {
        "label": label,
        "role": role,
        "path": str(expanded),
        "measurement_path": str(measured_path),
        "status": status,
        "problem": problem,
        "total_bytes": int(usage.total),
        "used_bytes": int(usage.used),
        "free_bytes": free_bytes,
        "free_gib": round(free_bytes / _GIB, 2),
    }


def _free_space_status(free_bytes: int) -> CheckStatus:
    if free_bytes < _DISK_ERROR_FREE_BYTES:
        return "ERROR"
    if free_bytes < _DISK_WARN_FREE_BYTES:
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
            return (
                f"{label} has less than 1 GB free "
                f"({_format_bytes(free_bytes)} available)"
            )
        return f"{label} free space could not be checked"
    if status == "WARN":
        if not isinstance(free_bytes, int):
            return f"{label} free space could not be checked"
        return (
            f"{label} has less than 3 GB free ({_format_bytes(free_bytes)} available)"
        )
    return f"{path_count} resource path(s) have at least 3 GB free"


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
    return (
        "Free disk space or run `sase workspace cleanup`.",
        "Live workspaces can consume hundreds of MB to over 1 GB after checkout and `.venv` creation.",
    )


def _format_bytes(value: int) -> str:
    if value >= _GIB:
        return f"{value / _GIB:.1f} GiB"
    return f"{value / (1024**2):.0f} MiB"


def _nearest_existing_parent(path: Path) -> Path | None:
    for candidate in (path, *path.parents):
        if candidate.exists():
            return candidate if candidate.is_dir() else candidate.parent
    return None

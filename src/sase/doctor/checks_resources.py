"""Resource capacity checks for ``sase doctor``."""

from __future__ import annotations

import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol, TYPE_CHECKING

from sase.config.core import CHEZMOI_HOME, get_use_chezmoi, load_merged_config
from sase.diagnostics import CheckSpec, CheckStatus, DiagnosticCheck
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
type _CommandResolver = Callable[[str], str | None]


def resource_check_specs(context: DoctorContext) -> tuple[CheckSpec, ...]:
    """Return default host-resource check specs."""
    return (
        CheckSpec(
            id="resources.disk_free",
            group="resources",
            title="Free disk space",
            runner=lambda: _check_disk_free(context),
        ),
        CheckSpec(
            id="resources.chezmoi",
            group="resources",
            title="Chezmoi source",
            runner=_check_chezmoi,
            deep=True,
        ),
    )


def _check_disk_free(
    context: DoctorContext,
    *,
    disk_usage_fn: _DiskUsageFn | None = None,
) -> DiagnosticCheck:
    """Check free space where managed workspaces and SASE state live."""
    if disk_usage_fn is None:
        disk_usage_fn = _disk_usage

    workspace_root, workspace_error = _workspace_root_path(context)
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


def _check_chezmoi(
    *,
    use_chezmoi: bool | None = None,
    source_home: Path | None = None,
    command_resolver: _CommandResolver | None = None,
) -> DiagnosticCheck:
    """Check the optional chezmoi source tree used for home-managed files."""
    if use_chezmoi is None:
        use_chezmoi = get_use_chezmoi()
    source_home = source_home or CHEZMOI_HOME
    command_resolver = command_resolver or shutil.which

    source_exists = source_home.exists()
    source_is_dir = source_home.is_dir() if source_exists else False
    command_path = command_resolver("chezmoi")
    source_entry_count = _source_entry_count(source_home) if source_is_dir else None
    data = {
        "use_chezmoi": use_chezmoi,
        "source_path": str(source_home),
        "source_exists": source_exists,
        "source_is_dir": source_is_dir,
        "source_entry_count": source_entry_count,
        "command_found": command_path is not None,
        "command_path": command_path,
    }

    if not use_chezmoi and not source_exists:
        return DiagnosticCheck(
            id="resources.chezmoi",
            group="resources",
            status="SKIP",
            title="Chezmoi source",
            summary="chezmoi remapping is disabled and no source tree was found",
            data=data,
        )

    problems = _chezmoi_source_problems(
        use_chezmoi=use_chezmoi,
        source_home=source_home,
        source_exists=source_exists,
        source_is_dir=source_is_dir,
        source_entry_count=source_entry_count,
        command_found=command_path is not None,
    )

    if use_chezmoi and command_path is None:
        return DiagnosticCheck(
            id="resources.chezmoi",
            group="resources",
            status="ERROR",
            title="Chezmoi source",
            summary="use_chezmoi is enabled but the chezmoi command is missing",
            details=tuple(problems),
            next_steps=(
                "Install `chezmoi` or set `use_chezmoi: false` if SASE should write live home files directly.",
            ),
            data=data,
        )

    if problems:
        return DiagnosticCheck(
            id="resources.chezmoi",
            group="resources",
            status="WARN",
            title="Chezmoi source",
            summary="chezmoi source state needs attention",
            details=tuple(problems),
            next_steps=_chezmoi_next_steps(problems),
            data=data,
        )

    return DiagnosticCheck(
        id="resources.chezmoi",
        group="resources",
        status="OK",
        title="Chezmoi source",
        summary=(
            "chezmoi command and source state look usable"
            if use_chezmoi
            else "chezmoi source tree exists; SASE chezmoi remapping is disabled"
        ),
        data=data,
    )


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


def _chezmoi_source_problems(
    *,
    use_chezmoi: bool,
    source_home: Path,
    source_exists: bool,
    source_is_dir: bool,
    source_entry_count: int | None,
    command_found: bool,
) -> list[str]:
    problems: list[str] = []
    if use_chezmoi and not source_exists:
        problems.append(
            f"`use_chezmoi` is true but the chezmoi source home is missing: {source_home}"
        )
    if source_exists and not source_is_dir:
        problems.append(f"chezmoi source home is not a directory: {source_home}")
    if source_is_dir and source_entry_count == 0:
        problems.append(f"chezmoi source home is empty: {source_home}")
    if source_exists and not command_found:
        problems.append("chezmoi source tree exists but `chezmoi` is not on PATH")
    return problems


def _source_entry_count(source_home: Path) -> int | None:
    try:
        return sum(1 for _entry in source_home.iterdir())
    except OSError:
        return None


def _chezmoi_next_steps(problems: list[str]) -> tuple[str, ...]:
    steps: list[str] = []
    if any("not a directory" in problem for problem in problems):
        steps.append("Move or remove the non-directory chezmoi source path.")
    if any("missing" in problem or "empty" in problem for problem in problems):
        steps.append(
            "Create or restore the chezmoi source tree, then rerun `sase doctor -D`."
        )
    if any("not on PATH" in problem for problem in problems):
        steps.append("Install `chezmoi` or remove the unused source tree.")
    return tuple(steps)


def _format_bytes(value: int) -> str:
    if value >= _GIB:
        return f"{value / _GIB:.1f} GiB"
    return f"{value / (1024**2):.0f} MiB"


def _nearest_existing_parent(path: Path) -> Path | None:
    for candidate in (path, *path.parents):
        if candidate.exists():
            return candidate if candidate.is_dir() else candidate.parent
    return None

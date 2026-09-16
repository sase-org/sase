"""Workspace compact owner step for ``sase disk reap``."""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable
from typing import Any

from sase.core.disk_footprint_models import DiskReapStep
from sase.workspace_provider.inventory import collect_workspace_inventory


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


__all__ = ["workspace_compact_steps", "workspace_project_keys"]

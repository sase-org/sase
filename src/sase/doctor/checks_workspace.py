"""Workspace registry checks for ``sase doctor``."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, TYPE_CHECKING

from sase.config.core import load_merged_config
from sase.diagnostics import CheckSpec, CheckStatus, DiagnosticCheck
from sase.doctor.checks_project import resolve_current_project_record
from sase.workspace_provider.registry import (
    SCHEMA_VERSION,
    WorkspaceRegistry,
    registry_path,
)
from sase.workspace_provider.store import WorkspaceStore

if TYPE_CHECKING:
    from sase.doctor.runner import DoctorContext
    from sase.workspace_provider.inventory import WorkspaceInventory

_MAX_DETAIL_ROWS = 10


def _collect_workspace_inventory(projects_root: Path) -> WorkspaceInventory:
    """Load the inventory lazily to avoid the running-field import cycle."""

    # The inventory imports the Rust-backed claim parser through the
    # ``running_field`` package. Initialize that package first so importing the
    # inventory from a standalone doctor process cannot observe a partially
    # initialized ``agent_launch_claims`` module.
    import importlib

    importlib.import_module("sase.running_field")
    from sase.workspace_provider.inventory import collect_workspace_inventory

    return collect_workspace_inventory(projects_root, include_disabled=True)


def workspace_check_specs(context: DoctorContext) -> tuple[CheckSpec, ...]:
    """Return default workspace check specs."""
    return (
        CheckSpec(
            id="workspace.registry",
            group="workspace",
            title="Workspace registry",
            runner=lambda: _check_workspace_registry(context),
        ),
        CheckSpec(
            id="workspace.missing_checkouts",
            group="workspace",
            title="Missing workspace checkouts",
            runner=lambda: _check_missing_workspace_checkouts(context),
        ),
    )


def _check_missing_workspace_checkouts(context: DoctorContext) -> DiagnosticCheck:
    """Report missing registry checkouts across enabled and disabled projects."""

    projects_root = context.sase_home / "projects"
    try:
        inventory = _collect_workspace_inventory(projects_root)
    except Exception as exc:  # noqa: BLE001 - doctor reports inventory failures.
        error = f"{type(exc).__name__}: {exc}"
        return DiagnosticCheck(
            id="workspace.missing_checkouts",
            group="workspace",
            status="ERROR",
            title="Missing workspace checkouts",
            summary="workspace inventory could not be loaded",
            details=(error,),
            next_steps=("Run `sase workspace list --all --json` for details.",),
            data={
                "projects_root": str(projects_root),
                "error": error,
            },
        )

    missing = [record for record in inventory.records if not record.exists]
    visible_missing = missing[:_MAX_DETAIL_ROWS]
    visible_issues = inventory.issues[: max(0, _MAX_DETAIL_ROWS - len(visible_missing))]
    details = [
        (
            f"{record.project} workspace #{record.workspace_num} is missing: "
            f"{record.checkout_dir}"
        )
        for record in visible_missing
    ]
    details.extend(
        f"{issue.project}: inventory warning: {issue.message}"
        for issue in visible_issues
    )

    if missing:
        summary = f"{len(missing)} registered workspace checkout(s) are missing"
    elif inventory.issues:
        summary = f"workspace inventory has {len(inventory.issues)} warning(s)"
    else:
        summary = f"all {len(inventory.records)} registered workspace checkout(s) exist"

    repair_projects = tuple(dict.fromkeys(record.project_key for record in missing))
    next_steps = tuple(
        f"Preview repair with `sase workspace repair -p {project} -n`."
        for project in repair_projects
    )
    if inventory.issues:
        next_steps = (
            *next_steps,
            "Inspect inventory warnings with `sase workspace list --all --json`.",
        )

    return DiagnosticCheck(
        id="workspace.missing_checkouts",
        group="workspace",
        status="WARN" if missing or inventory.issues else "OK",
        title="Missing workspace checkouts",
        summary=summary,
        details=tuple(details),
        next_steps=next_steps,
        data={
            "projects_root": str(projects_root),
            "workspace_count": len(inventory.records),
            "missing_checkout_count": len(missing),
            "missing_checkouts": [
                {
                    "project": record.project,
                    "project_key": record.project_key,
                    "workspace_num": record.workspace_num,
                    "checkout_dir": record.checkout_dir,
                    "registry_path": record.registry_path,
                }
                for record in visible_missing
            ],
            "inventory_issue_count": len(inventory.issues),
            "inventory_issues": [
                {"project": issue.project, "message": issue.message}
                for issue in visible_issues
            ],
            "details_truncated": (len(missing) + len(inventory.issues) > len(details)),
        },
    )


def _check_workspace_registry(context: DoctorContext) -> DiagnosticCheck:
    resolution = resolve_current_project_record(context)
    if resolution.error:
        return DiagnosticCheck(
            id="workspace.registry",
            group="workspace",
            status="SKIP",
            title="Workspace registry",
            summary="project records could not be loaded",
            details=(resolution.error,),
            next_steps=(
                "Fix `project.current` before inspecting workspace registry state.",
            ),
            data={"project_error": resolution.error},
        )

    record = resolution.record
    if record is None:
        return DiagnosticCheck(
            id="workspace.registry",
            group="workspace",
            status="SKIP",
            title="Workspace registry",
            summary="no current project workspace to inspect",
            data={
                "project_name": resolution.project_name,
                "record_found": False,
            },
        )

    primary = record.workspace_dir
    if not primary:
        return DiagnosticCheck(
            id="workspace.registry",
            group="workspace",
            status="WARN",
            title="Workspace registry",
            summary=f"project {record.project_name!r} has no WORKSPACE_DIR",
            next_steps=(f"Update WORKSPACE_DIR in {record.project_file}.",),
            data={
                "project": record.project_name,
                "project_file": record.project_file,
                "primary_workspace_dir": None,
            },
        )

    primary_path = Path(primary).expanduser()
    if not primary_path.is_dir():
        return DiagnosticCheck(
            id="workspace.registry",
            group="workspace",
            status="WARN",
            title="Workspace registry",
            summary=f"primary workspace path is missing: {primary_path}",
            next_steps=(f"Fix WORKSPACE_DIR in {record.project_file}.",),
            data={
                "project": record.project_name,
                "project_file": record.project_file,
                "primary_workspace_dir": str(primary_path),
                "primary_exists": False,
            },
        )

    try:
        store = WorkspaceStore(str(primary_path), config=load_merged_config())
    except Exception as exc:  # noqa: BLE001 - store config failures are diagnostic.
        return DiagnosticCheck(
            id="workspace.registry",
            group="workspace",
            status="ERROR",
            title="Workspace registry",
            summary="workspace root configuration could not be resolved",
            details=(f"{type(exc).__name__}: {exc}",),
            next_steps=("Fix the workspace section in sase.yml.",),
            data={
                "project": record.project_name,
                "primary_workspace_dir": str(primary_path),
                "error": f"{type(exc).__name__}: {exc}",
            },
        )

    path = Path(registry_path(store.root_dir))
    registry, read_error, exists = _read_registry(path)
    base_data = {
        "project": record.project_name,
        "project_key": store.project_key,
        "root_policy": store.root_policy,
        "root_dir": store.root_dir,
        "registry_path": str(path),
        "registry_exists": exists,
        "primary_workspace_dir": str(primary_path),
        "active_claim_count": record.active_claim_count,
    }

    if read_error:
        return DiagnosticCheck(
            id="workspace.registry",
            group="workspace",
            status="WARN",
            title="Workspace registry",
            summary="workspace registry could not be read",
            details=(read_error,),
            next_steps=(f"Run `sase workspace repair -p {record.project_name} -n`.",),
            data={**base_data, "read_error": read_error},
        )

    if registry is None:
        if store.root_policy == "adjacent":
            status: CheckStatus = "SKIP"
            summary = "adjacent workspace root does not require a registry"
            next_steps: tuple[str, ...] = ()
        elif record.active_claim_count:
            status = "WARN"
            summary = "managed workspace registry is missing while claims are active"
            next_steps = (f"Run `sase workspace repair -p {record.project_name} -n`.",)
        else:
            status = "SKIP"
            summary = "managed workspace registry is not present"
            next_steps = ()
        return DiagnosticCheck(
            id="workspace.registry",
            group="workspace",
            status=status,
            title="Workspace registry",
            summary=summary,
            next_steps=next_steps,
            data=base_data,
        )

    problems = _registry_problems(registry)
    entries = _registry_entries(registry)
    missing = [row for row in entries if not row["exists"]]
    problems.extend(
        f"workspace #{row['workspace_num']} path is missing: {row['checkout_dir']}"
        for row in missing[:_MAX_DETAIL_ROWS]
    )
    status = "WARN" if problems else "OK"
    summary = (
        f"registry schema {registry.schema_version}; {len(entries)} workspace row(s)"
        if status == "OK"
        else f"workspace registry has {len(problems)} problem(s)"
    )

    return DiagnosticCheck(
        id="workspace.registry",
        group="workspace",
        status=status,
        title="Workspace registry",
        summary=summary,
        details=tuple(problems[:_MAX_DETAIL_ROWS]),
        next_steps=(f"Run `sase workspace repair -p {record.project_name} -n`.",)
        if problems
        else (),
        data={
            **base_data,
            "schema_version": registry.schema_version,
            "workspace_count": len(entries),
            "missing_checkout_count": len(missing),
            "workspaces": entries[:_MAX_DETAIL_ROWS],
        },
    )


def _read_registry(
    path: Path,
) -> tuple[WorkspaceRegistry | None, str | None, bool]:
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None, None, False
    except OSError as exc:
        return None, f"{type(exc).__name__}: {exc}", True

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        return None, f"JSONDecodeError: {exc}", True
    if not isinstance(data, dict):
        return None, "registry JSON root is not an object", True
    try:
        return WorkspaceRegistry.from_dict(data), None, True
    except (TypeError, ValueError) as exc:
        return None, f"{type(exc).__name__}: {exc}", True


def _registry_problems(registry: WorkspaceRegistry) -> list[str]:
    problems: list[str] = []
    if registry.schema_version != SCHEMA_VERSION:
        problems.append(
            f"registry schema {registry.schema_version} != expected {SCHEMA_VERSION}"
        )
    if not registry.project_key:
        problems.append("registry project_key is empty")
    if not registry.primary_workspace_dir:
        problems.append("registry primary_workspace_dir is empty")
    if "0" not in registry.workspaces:
        problems.append("registry is missing primary workspace #0")
    return problems


def _registry_entries(registry: WorkspaceRegistry) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for raw_num, entry in registry.workspaces.items():
        try:
            workspace_num = int(raw_num)
        except (TypeError, ValueError):
            continue
        checkout_dir = entry.checkout_dir.rstrip("/") or entry.checkout_dir
        rows.append(
            {
                "workspace_num": workspace_num,
                "checkout_dir": checkout_dir,
                "materialization": entry.materialization,
                "role": entry.role,
                "pinned": entry.pinned,
                "exists": Path(checkout_dir).is_dir(),
            }
        )
    rows.sort(key=lambda row: int(row["workspace_num"]))
    return rows


__all__ = [
    "workspace_check_specs",
]

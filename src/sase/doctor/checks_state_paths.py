"""State, config, project, and workspace path checks for ``sase doctor``."""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path
from typing import Any, TYPE_CHECKING

from sase.config.core import CONFIG_DIR, load_merged_config
from sase.core.paths import sase_projects_dir
from sase.diagnostics import CheckStatus, DiagnosticCheck
from sase.workspace_provider.store import WorkspaceStore

if TYPE_CHECKING:
    from sase.doctor.runner import DoctorContext


LoadConfigFn = Callable[[], Any]


def check_state_paths(
    context: DoctorContext,
    *,
    load_config_fn: LoadConfigFn | None = None,
    workspace_store_cls: type[WorkspaceStore] = WorkspaceStore,
) -> DiagnosticCheck:
    """Check required SASE state, config, project, and workspace paths."""
    path_rows: list[dict[str, Any]] = [
        directory_target("sase_home", context.sase_home),
        directory_target("config_dir", CONFIG_DIR),
        directory_target("projects_dir", sase_projects_dir()),
    ]
    workspace_error: str | None = None
    try:
        load_config = load_config_fn or load_merged_config
        config = load_config()
        store = workspace_store_cls(str(context.cwd), config=config)
        path_rows.append(directory_target("workspace_root", Path(store.root_dir)))
    except Exception as exc:  # noqa: BLE001 - report config/root resolution failures.
        workspace_error = f"{type(exc).__name__}: {exc}"

    errors = [
        f"{row['label']}: {row['problem']}" for row in path_rows if row.get("problem")
    ]
    if workspace_error:
        errors.append(f"workspace_root: {workspace_error}")

    status: CheckStatus = "ERROR" if errors else "OK"
    existing = sum(1 for row in path_rows if row["exists"])
    creatable = sum(1 for row in path_rows if row["creatable"])
    summary = (
        f"{existing}/{len(path_rows)} paths exist; missing paths are creatable"
        if status == "OK"
        else f"{len(errors)} path problem(s) found"
    )

    return DiagnosticCheck(
        id="state.paths",
        group="state",
        status=status,
        title="State and config paths",
        summary=summary,
        details=tuple(errors),
        next_steps=("Fix ownership/permissions for the reported paths.",)
        if errors
        else (),
        data={
            "paths": path_rows,
            "creatable_count": creatable,
            "workspace_error": workspace_error,
        },
    )


def directory_target(label: str, path: Path) -> dict[str, Any]:
    expanded = path.expanduser()
    exists = expanded.exists()
    is_dir = expanded.is_dir()
    problem: str | None = None
    creatable = False

    if exists and not is_dir:
        problem = f"{expanded} exists but is not a directory"
    elif exists:
        if not os.access(expanded, os.W_OK | os.X_OK):
            problem = f"{expanded} is not writable"
        else:
            creatable = True
    else:
        parent = nearest_existing_parent(expanded)
        if parent is None or not os.access(parent, os.W_OK | os.X_OK):
            problem = f"{expanded} does not exist and parent is not writable"
        else:
            creatable = True

    return {
        "label": label,
        "path": str(expanded),
        "exists": exists,
        "is_dir": is_dir,
        "creatable": creatable,
        "problem": problem,
    }


def nearest_existing_parent(path: Path) -> Path | None:
    for candidate in (path.parent, *path.parents):
        if candidate.exists():
            return candidate if candidate.is_dir() else None
    return None


__all__ = [
    "check_state_paths",
    "directory_target",
    "nearest_existing_parent",
]

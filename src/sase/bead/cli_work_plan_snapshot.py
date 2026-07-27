"""Approved-plan snapshot storage for epic bead launches."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import sys
import tempfile
from collections.abc import Callable
from typing import TYPE_CHECKING

from sase.bead.project import BeadProject
from sase.sdd.plan_refs import (
    resolve_plan_reference,
    workspace_context_for_plan_resolution,
)

if TYPE_CHECKING:
    from sase.bead.work import VCSLaunchContext


def epic_plan_source_path(proj: BeadProject, plan_ref: str) -> Path:
    """Resolve an epic's approved plan from its authoritative bead store."""
    if not plan_ref.strip():
        raise ValueError("the epic has no approved plan reference")

    workspace_dir, workspace_num = _snapshot_resolution_workspace(proj)
    resolution = resolve_plan_reference(
        plan_ref,
        workspace_dir=workspace_dir,
        workspace_num=workspace_num,
    )
    if resolution.resolved_path is not None:
        return resolution.resolved_path
    if resolution.status == "ambiguous":
        raise ValueError(f"the approved plan reference is ambiguous: {plan_ref!r}")
    raise ValueError(f"the approved plan reference could not be resolved: {plan_ref!r}")


def _snapshot_resolution_workspace(proj: BeadProject) -> tuple[Path, int]:
    """Return the checkout context that owns *proj*'s active SDD store."""

    current_dir, current_num = workspace_context_for_plan_resolution(Path.cwd())
    project_root = proj.root_dir.expanduser().resolve(strict=False)
    if project_root == current_dir or current_dir in project_root.parents:
        return current_dir, current_num
    if project_root in current_dir.parents:
        return project_root, current_num
    return workspace_context_for_plan_resolution(project_root)


def epic_plan_snapshot_destination(project_name: str, epic_id: str) -> Path:
    """Return a project-scoped snapshot path confined to one safe filename."""
    from sase.core.paths import sase_projects_dir, validate_sase_project_name

    validate_sase_project_name(project_name)
    if (
        not epic_id
        or epic_id in {".", ".."}
        or "\x00" in epic_id
        or "/" in epic_id
        or "\\" in epic_id
    ):
        raise ValueError(f"invalid epic identifier for snapshot: {epic_id!r}")
    filename = f"{epic_id}.md"
    destination = (
        sase_projects_dir() / project_name / "artifacts" / "epic-plans" / filename
    )
    return destination.expanduser().resolve(strict=False)


def atomic_copy_epic_plan(source: Path, destination: Path) -> None:
    """Replace *destination* with a complete copy of *source*."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(
        dir=destination.parent,
        prefix=f".{destination.name}.",
        suffix=".tmp",
    )
    os.close(fd)
    temporary_path = Path(temporary)
    try:
        shutil.copyfile(source, temporary_path)
        os.replace(temporary_path, destination)
    finally:
        temporary_path.unlink(missing_ok=True)


def snapshot_epic_plan(
    proj: BeadProject,
    epic_id: str,
    *,
    plan_ref: str,
    launch_context: VCSLaunchContext | None,
    copy_plan: Callable[[Path, Path], None] = atomic_copy_epic_plan,
) -> str | None:
    """Best-effort copy of an approved plan into durable project state."""
    project_name = launch_context.project_name if launch_context is not None else None
    if not project_name:
        from sase.bead.project_name import infer_project_name_from_cwd

        project_name = infer_project_name_from_cwd()

    try:
        if not project_name:
            raise ValueError("the current SASE project could not be inferred")
        source = epic_plan_source_path(proj, plan_ref)
        destination = epic_plan_snapshot_destination(project_name, epic_id)
        copy_plan(source, destination)
    except Exception as exc:
        destination_context = project_name or "unknown project"
        failure = type(exc).__name__
        if isinstance(exc, ValueError):
            failure = f"{failure}: {exc}"
        print(
            f"Warning: could not snapshot approved plan for epic {epic_id!r} "
            f"from reference {plan_ref!r} into project "
            f"{destination_context!r}: {failure}",
            file=sys.stderr,
        )
        return None
    return str(destination)

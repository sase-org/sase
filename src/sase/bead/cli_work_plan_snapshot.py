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

if TYPE_CHECKING:
    from sase.bead.work import VCSLaunchContext


def epic_plan_source_path(proj: BeadProject, plan_ref: str) -> Path:
    """Resolve an epic's approved plan from its authoritative bead store."""
    expanded = Path(plan_ref).expanduser()
    if expanded.is_absolute():
        return expanded.resolve(strict=False)
    if not plan_ref.strip():
        raise ValueError("the epic has no approved plan reference")

    root = proj.root_dir.expanduser().resolve(strict=False)
    beads_dir = proj.beads_dir.expanduser().resolve(strict=False)
    try:
        beads_relative = beads_dir.relative_to(root)
    except ValueError as exc:
        raise ValueError("the bead store is outside its project root") from exc

    parts = tuple(part for part in Path(plan_ref.replace("\\", "/")).parts if part)
    if beads_relative == Path("sdd/beads"):
        plans_root = root / "sdd" / "plans"
        relative = plan_ref_after_marker(parts, ("sdd", "plans"))
        if relative is None:
            relative = plan_ref_after_marker(parts, ("plans",)) or parts
    elif beads_relative == Path("beads"):
        sidecar_relative = plan_ref_after_marker(
            parts,
            ("sase", "repos", "plans"),
        )
        local_relative = plan_ref_after_marker(
            parts,
            (".sase", "sdd", "plans"),
        )
        if sidecar_relative is not None:
            plans_root = root
            relative = sidecar_relative
        elif local_relative is not None:
            plans_root = root / "plans"
            relative = local_relative
        else:
            plans_relative = plan_ref_after_marker(parts, ("plans",))
            local_layout = root.name == "sdd" and root.parent.name == ".sase"
            if plans_relative is not None or local_layout or (root / "plans").is_dir():
                plans_root = root / "plans"
                relative = plans_relative or parts
            else:
                plans_root = root
                relative = parts
    else:
        raise ValueError(f"unsupported bead store layout: {beads_relative}")

    resolved_root = plans_root.resolve(strict=False)
    source = resolved_root.joinpath(*relative).resolve(strict=False)
    try:
        source.relative_to(resolved_root)
    except ValueError as exc:
        raise ValueError("the relative plan reference escapes its plans store") from exc
    return source


def plan_ref_after_marker(
    parts: tuple[str, ...],
    marker: tuple[str, ...],
) -> tuple[str, ...] | None:
    """Return the suffix after a known storage marker in a plan reference."""
    marker_length = len(marker)
    for index in range(len(parts) - marker_length + 1):
        if parts[index : index + marker_length] == marker:
            return parts[index + marker_length :]
    return None


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

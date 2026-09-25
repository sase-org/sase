"""Bounded cleanliness checks for enabled projects' agents sidecars."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import subprocess
from typing import TYPE_CHECKING

from sase.agents_sync.prompt_archive.archive_objects import (
    ARCHIVE_OBJECT_ROOT,
    is_valid_archive_object,
)
from sase.agents_sync.targets import resolve_sync_targets
from sase.diagnostics import CheckSpec, DiagnosticCheck

if TYPE_CHECKING:
    from sase.doctor.runner import DoctorContext

_CHECK_ID = "project.agents_sidecar_dirt"
_TITLE = "Agents sidecar dirt"
_GIT_TIMEOUT_SECONDS = 10
_MAX_DETAIL_ROWS = 10


@dataclass(frozen=True, slots=True)
class _SidecarDirt:
    project: str
    project_key: str
    clone: Path
    path: str
    xy: str
    pending_object: bool


def agents_sidecar_check_specs(context: DoctorContext) -> tuple[CheckSpec, ...]:
    """Return the default check for local agents-sidecar dirt."""

    return (
        CheckSpec(
            id=_CHECK_ID,
            group="project",
            title=_TITLE,
            runner=lambda: _check_agents_sidecar_dirt(context),
        ),
    )


def _check_agents_sidecar_dirt(context: DoctorContext) -> DiagnosticCheck:
    """Warn about bounded, per-project agents-sidecar worktree dirt."""

    selection = resolve_sync_targets(projects_root=context.sase_home / "projects")
    targets = selection.targets
    if not targets:
        return DiagnosticCheck(
            id=_CHECK_ID,
            group="project",
            status="SKIP",
            title=_TITLE,
            summary="no enabled project has an available agents sidecar clone",
            data={"checked_clones": 0, "entries": ()},
        )

    dirt = tuple(
        entry
        for target in targets
        for entry in _sidecar_dirt(
            project=target.project,
            project_key=target.project_key,
            clone=target.sidecar_path,
        )
    )
    if not dirt:
        return DiagnosticCheck(
            id=_CHECK_ID,
            group="project",
            status="OK",
            title=_TITLE,
            summary=f"{len(targets)} enabled agents sidecar clone(s) are clean",
            data={"checked_clones": len(targets), "entries": ()},
        )

    pending = tuple(entry for entry in dirt if entry.pending_object)
    unexpected = tuple(entry for entry in dirt if not entry.pending_object)
    details = tuple(_detail(entry) for entry in dirt[:_MAX_DETAIL_ROWS])
    return DiagnosticCheck(
        id=_CHECK_ID,
        group="project",
        status="WARN",
        title=_TITLE,
        summary=(
            f"{len(dirt)} uncommitted path(s) in {len({entry.clone for entry in dirt})} "
            "agents sidecar clone(s)"
        ),
        details=details,
        next_steps=_next_steps(pending, unexpected),
        data={
            "checked_clones": len(targets),
            "pending_object_count": len(pending),
            "unexpected_dirt_count": len(unexpected),
            "entries": tuple(_data(entry) for entry in dirt),
        },
    )


def _sidecar_dirt(
    *, project: str, project_key: str, clone: Path
) -> tuple[_SidecarDirt, ...]:
    """Read a clone's full porcelain status once, within a hard time bound."""

    try:
        result = subprocess.run(
            [
                "git",
                "-C",
                str(clone),
                "status",
                "--porcelain=v1",
                "--untracked-files=all",
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=_GIT_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ()
    if result.returncode != 0:
        return ()
    entries: list[_SidecarDirt] = []
    for line in result.stdout.splitlines():
        if len(line) < 4:
            continue
        xy, path = line[:2], line[3:]
        if path.startswith("./"):
            path = path[2:]
        entries.append(
            _SidecarDirt(
                project=project,
                project_key=project_key,
                clone=clone,
                path=path,
                xy=xy,
                pending_object=(
                    xy == "??"
                    and path.startswith(f"{ARCHIVE_OBJECT_ROOT}/")
                    and is_valid_archive_object(clone, path)
                ),
            )
        )
    return tuple(entries)


def _detail(entry: _SidecarDirt) -> str:
    classification = (
        "pending hash-valid archive object"
        if entry.pending_object
        else "unexpected dirt"
    )
    return f"{entry.project}: {entry.xy} {entry.path} ({classification})"


def _next_steps(
    pending: tuple[_SidecarDirt, ...], unexpected: tuple[_SidecarDirt, ...]
) -> tuple[str, ...]:
    steps: list[str] = []
    for project in dict.fromkeys(entry.project for entry in pending):
        steps.append(
            f"Run `sase agent sync -p {project}` to publish hash-valid pending archive objects."
        )
    if unexpected:
        steps.append(
            "Inspect unexpected dirt in the listed agents sidecar clone(s); this check never changes them."
        )
    return tuple(steps)


def _data(entry: _SidecarDirt) -> dict[str, object]:
    return {
        "project": entry.project,
        "project_key": entry.project_key,
        "clone": str(entry.clone),
        "path": entry.path,
        "xy": entry.xy,
        "classification": "pending_object" if entry.pending_object else "unexpected",
    }


__all__ = ["agents_sidecar_check_specs"]

"""Project lifecycle checks for ``sase doctor``."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from sase.core.paths import is_valid_sase_project_name, sase_projects_dir
from sase.core.project_lifecycle_facade import list_project_records
from sase.core.project_lifecycle_wire import (
    ProjectRecordWire,
    is_disabled_project_lifecycle_state,
    project_lifecycle_wire_to_json_dict,
)
from sase.diagnostics import CheckSpec, CheckStatus, DiagnosticCheck

if TYPE_CHECKING:
    from sase.doctor.runner import DoctorContext

_ALL_PROJECT_STATES = ("enabled", "disabled", "sibling")
_MAX_DETAIL_ROWS = 10


@dataclass(frozen=True)
class _ProjectResolution:
    """Read-only current-project resolution for doctor checks."""

    requested_project: str | None
    inferred_project: str | None
    project_name: str | None
    record: ProjectRecordWire | None
    records: tuple[ProjectRecordWire, ...]
    matched_by: str | None = None
    error: str | None = None


def project_check_specs(context: DoctorContext) -> tuple[CheckSpec, ...]:
    """Return default project check specs."""
    return (
        CheckSpec(
            id="project.current",
            group="project",
            title="Current project",
            runner=lambda: _check_project_current(context),
        ),
        CheckSpec(
            id="project.junk_directories",
            group="project",
            title="Unregistered project directories",
            runner=lambda: _check_junk_project_directories(context),
        ),
    )


def _check_junk_project_directories(context: DoctorContext) -> DiagnosticCheck:
    """Report project-root directories that have no active ProjectSpec."""

    projects_root = context.sase_home / "projects"
    try:
        project_dirs = sorted(
            (
                path
                for path in projects_root.iterdir()
                if path.is_dir() and path.name != "home"
            ),
            key=lambda path: path.name.casefold(),
        )
    except FileNotFoundError:
        return DiagnosticCheck(
            id="project.junk_directories",
            group="project",
            status="SKIP",
            title="Unregistered project directories",
            summary="SASE projects directory is not present",
            data={
                "projects_root": str(projects_root),
                "projects_root_exists": False,
                "junk_directory_count": 0,
                "junk_directories": [],
            },
        )
    except OSError as exc:
        error = f"{type(exc).__name__}: {exc}"
        return DiagnosticCheck(
            id="project.junk_directories",
            group="project",
            status="ERROR",
            title="Unregistered project directories",
            summary="SASE projects directory could not be scanned",
            details=(error,),
            next_steps=(f"Check permissions for {projects_root}.",),
            data={
                "projects_root": str(projects_root),
                "projects_root_exists": True,
                "error": error,
            },
        )

    junk_dirs = [
        path for path in project_dirs if not (path / f"{path.name}.sase").is_file()
    ]
    if not junk_dirs:
        return DiagnosticCheck(
            id="project.junk_directories",
            group="project",
            status="OK",
            title="Unregistered project directories",
            summary=f"all {len(project_dirs)} project directories have a ProjectSpec",
            data={
                "projects_root": str(projects_root),
                "projects_root_exists": True,
                "directory_count": len(project_dirs),
                "junk_directory_count": 0,
                "junk_directories": [],
            },
        )

    visible = junk_dirs[:_MAX_DETAIL_ROWS]
    return DiagnosticCheck(
        id="project.junk_directories",
        group="project",
        status="WARN",
        title="Unregistered project directories",
        summary=f"found {len(junk_dirs)} project directories without a ProjectSpec",
        details=tuple(f"{path}: missing {path.name}.sase" for path in visible),
        next_steps=(
            "Review these directories, then manually remove any obsolete state; "
            "SASE only registers a directory containing its canonical <name>.sase file.",
        ),
        data={
            "projects_root": str(projects_root),
            "projects_root_exists": True,
            "directory_count": len(project_dirs),
            "junk_directory_count": len(junk_dirs),
            "junk_directories": [str(path) for path in visible],
            "details_truncated": len(junk_dirs) > len(visible),
        },
    )


def resolve_current_project_record(context: DoctorContext) -> _ProjectResolution:
    """Resolve the selected or inferred project without materializing state."""
    requested = context.project
    inferred: str | None = None
    if not requested:
        try:
            from sase.bead.project_name import infer_project_name_from_cwd

            inferred = infer_project_name_from_cwd(str(context.cwd))
        except Exception:
            inferred = None

    project_name = requested or inferred
    try:
        records = tuple(
            list_project_records(
                sase_projects_dir(),
                _ALL_PROJECT_STATES,
                include_home=True,
            )
        )
    except Exception as exc:  # noqa: BLE001 - doctor reports facade failures.
        return _ProjectResolution(
            requested_project=requested,
            inferred_project=inferred,
            project_name=project_name,
            record=None,
            records=(),
            error=f"{type(exc).__name__}: {exc}",
        )

    if project_name:
        context.project = project_name
    if not project_name:
        return _ProjectResolution(
            requested_project=requested,
            inferred_project=inferred,
            project_name=None,
            record=None,
            records=records,
        )

    if not is_valid_sase_project_name(project_name):
        return _ProjectResolution(
            requested_project=requested,
            inferred_project=inferred,
            project_name=project_name,
            record=None,
            records=records,
            error=f"invalid project name: {project_name!r}",
        )

    record, matched_by = _find_record(records, project_name)
    if record is not None:
        context.project = record.project_name

    return _ProjectResolution(
        requested_project=requested,
        inferred_project=inferred,
        project_name=context.project,
        record=record,
        records=records,
        matched_by=matched_by,
    )


def _check_project_current(context: DoctorContext) -> DiagnosticCheck:
    resolution = resolve_current_project_record(context)
    if resolution.error:
        return DiagnosticCheck(
            id="project.current",
            group="project",
            status="ERROR",
            title="Current project",
            summary="project lifecycle records could not be loaded",
            details=(resolution.error,),
            next_steps=(
                "Run `sase core health -j` and `sase project list -s all -j`.",
            ),
            data=_resolution_data(resolution),
        )

    if resolution.project_name is None:
        return DiagnosticCheck(
            id="project.current",
            group="project",
            status="SKIP",
            title="Current project",
            summary="no SASE project could be inferred from this checkout",
            next_steps=("Pass `sase doctor -p <project>` to inspect a project.",),
            data=_resolution_data(resolution),
        )

    record = resolution.record
    if record is None:
        return DiagnosticCheck(
            id="project.current",
            group="project",
            status="WARN",
            title="Current project",
            summary=f"project {resolution.project_name!r} was not found",
            next_steps=("Run `sase project list -s all` and pass a known project.",),
            data=_resolution_data(resolution),
        )

    problems = _project_record_problems(record)
    status: CheckStatus = "WARN" if problems else "OK"
    launch = (
        "launchable"
        if record.launchable and record.state == "enabled"
        else "not launchable"
    )
    summary = (
        f"{record.project_name}: state={record.state}; {launch}; "
        f"{record.active_claim_count} active claim(s)"
    )
    next_steps = _project_next_steps(record, problems)

    return DiagnosticCheck(
        id="project.current",
        group="project",
        status=status,
        title="Current project",
        summary=summary,
        details=tuple(problems[:_MAX_DETAIL_ROWS]),
        next_steps=next_steps,
        data=_resolution_data(resolution),
    )


def _find_record(
    records: tuple[ProjectRecordWire, ...], project_name: str
) -> tuple[ProjectRecordWire | None, str | None]:
    for record in records:
        if record.project_name == project_name:
            return record, "project_name"
    for record in records:
        if project_name in record.aliases:
            return record, "alias"
    return None, None


def _project_record_problems(record: ProjectRecordWire) -> list[str]:
    problems: list[str] = []
    if is_disabled_project_lifecycle_state(record.state):
        problems.append(f"project state is {record.state}")
    elif record.state != "enabled":
        problems.append(f"project state is {record.state}")
    if not record.workspace_dir:
        problems.append("project has no WORKSPACE_DIR")
    if not record.launchable:
        problems.append("project is not launchable")
    problems.extend(record.parse_warnings)
    problems.extend(record.warnings)
    return problems


def _project_next_steps(
    record: ProjectRecordWire,
    problems: list[str],
) -> tuple[str, ...]:
    if not problems:
        return ()
    steps: list[str] = []
    if record.state != "enabled":
        steps.append(f"Run `sase project enable {record.project_name}`.")
    if not record.workspace_dir:
        steps.append(f"Update WORKSPACE_DIR in {record.project_file}.")
    if record.parse_warnings or record.warnings:
        steps.append(f"Run `sase project show {record.project_name}`.")
    return tuple(dict.fromkeys(steps))


def _resolution_data(resolution: _ProjectResolution) -> dict[str, object]:
    record = resolution.record
    return {
        "projects_root": str(sase_projects_dir()),
        "requested_project": resolution.requested_project,
        "inferred_project": resolution.inferred_project,
        "project_name": resolution.project_name,
        "matched_by": resolution.matched_by,
        "record_count": len(resolution.records),
        "error": resolution.error,
        "record": project_lifecycle_wire_to_json_dict(record) if record else None,
    }


__all__ = [
    "project_check_specs",
    "resolve_current_project_record",
]

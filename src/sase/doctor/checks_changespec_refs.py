"""ChangeSpec artifact-reference validation for ``sase doctor``."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from sase.ace.changespec import ChangeSpec, parse_project_file
from sase.artifact_ref_lists import resolve_artifact_ref_list
from sase.diagnostics import CheckSpec, DiagnosticCheck
from sase.doctor.checks_project import resolve_current_project_record

if TYPE_CHECKING:
    from sase.artifact_ref_models import ArtifactRefContext
    from sase.core.project_lifecycle_wire import ProjectRecordWire
    from sase.doctor.runner import DoctorContext

_MAX_DETAIL_ROWS = 10
_NAMESPACE_STATUSES = frozenset({"unknown_kind", "unknown_repo", "unknown_project"})


def changespec_ref_check_specs(context: DoctorContext) -> tuple[CheckSpec, ...]:
    """Return the ChangeSpec reference validation check."""

    return (
        CheckSpec(
            id="project.changespec_refs",
            group="project",
            title="ChangeSpec artifact references",
            runner=lambda: _check_changespec_refs(context),
        ),
    )


def _check_changespec_refs(context: DoctorContext) -> DiagnosticCheck:
    resolution = resolve_current_project_record(context)
    record = resolution.record
    if record is None:
        return _skip("no current project store is available", context)

    changespecs = _load_changespecs(record)
    refs = [
        (changespec.name, reference)
        for changespec in changespecs
        for reference in (changespec.refs or ())
    ]
    reference_context = _reference_context(record)
    if reference_context is None:
        return _skip(
            "artifact-reference context is unavailable",
            context,
            record=record,
            changespec_count=len(changespecs),
            reference_count=len(refs),
        )

    if not refs:
        return DiagnosticCheck(
            id="project.changespec_refs",
            group="project",
            status="OK",
            title="ChangeSpec artifact references",
            summary=(
                f"all {len(changespecs)} ChangeSpecs have valid artifact "
                "references (0 stored)"
            ),
            data={
                "project": record.project_name,
                "changespec_count": len(changespecs),
                "reference_count": 0,
                "findings": [],
            },
        )

    outcomes = resolve_artifact_ref_list(
        (reference for _, reference in refs),
        context=reference_context,
    )
    unknown: list[str] = []
    missing: list[str] = []
    ambiguous: list[str] = []
    findings: list[dict[str, str]] = []
    for (changespec_name, reference), outcome in zip(refs, outcomes, strict=True):
        status = outcome.resolution.status
        if status in _NAMESPACE_STATUSES:
            unknown.append(f"{changespec_name} [{reference}]")
        elif status == "missing":
            missing.append(f"{changespec_name} [{reference}]")
        elif status == "ambiguous":
            ambiguous.append(f"{changespec_name} [{reference}]")
        else:
            continue
        findings.append(
            {
                "changespec": changespec_name,
                "reference": reference,
                "status": status,
            }
        )

    details: list[str] = []
    _append_group(
        details,
        "WARNING: artifact references with unknown kinds",
        unknown,
    )
    _append_group(details, "WARNING: unresolvable artifact references", missing)
    _append_group(details, "WARNING: ambiguous artifact references", ambiguous)
    problem_count = len(findings)
    return DiagnosticCheck(
        id="project.changespec_refs",
        group="project",
        status="WARN" if problem_count else "OK",
        title="ChangeSpec artifact references",
        summary=(
            f"{problem_count} of {len(refs)} ChangeSpec artifact references "
            "do not resolve cleanly"
            if problem_count
            else f"all {len(refs)} ChangeSpec artifact references resolve cleanly"
        ),
        details=tuple(details[:_MAX_DETAIL_ROWS]),
        next_steps=(
            (
                "Review the named REFS entries with "
                "`sase changespec ref list --resolve`.",
            )
            if problem_count
            else ()
        ),
        data={
            "project": record.project_name,
            "changespec_count": len(changespecs),
            "reference_count": len(refs),
            "findings": findings,
        },
    )


def _load_changespecs(record: ProjectRecordWire) -> list[ChangeSpec]:
    changespecs: list[ChangeSpec] = []
    for raw_path in (record.project_file, record.archive_file):
        if raw_path and Path(raw_path).is_file():
            changespecs.extend(parse_project_file(raw_path))
    return changespecs


def _reference_context(record: ProjectRecordWire) -> ArtifactRefContext | None:
    if not record.workspace_dir:
        return None
    from sase.artifact_ref_context import artifact_ref_context
    from sase.sdd.plan_refs import workspace_context_for_plan_resolution

    try:
        workspace, workspace_num = workspace_context_for_plan_resolution(
            record.workspace_dir
        )
        return artifact_ref_context(workspace, workspace_num, record.project_name)
    except Exception:
        return None


def _append_group(details: list[str], label: str, values: list[str]) -> None:
    if values:
        details.append(f"{label} ({len(values)}): {', '.join(values)}")


def _skip(
    summary: str,
    context: DoctorContext,
    *,
    record: ProjectRecordWire | None = None,
    changespec_count: int = 0,
    reference_count: int = 0,
) -> DiagnosticCheck:
    return DiagnosticCheck(
        id="project.changespec_refs",
        group="project",
        status="SKIP",
        title="ChangeSpec artifact references",
        summary=summary,
        data={
            "project": record.project_name if record is not None else context.project,
            "changespec_count": changespec_count,
            "reference_count": reference_count,
            "findings": [],
        },
    )


__all__ = ["changespec_ref_check_specs"]

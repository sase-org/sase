"""Mobile helper bridge operations for reading bead stores."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sase.bead.model import BeadTier, Issue, IssueType, Status
from sase.bead.store_locator import (
    canonical_beads_dir_for_project,
    open_bead_project_for_beads_dir,
)

from ._mobile_helper_common import (
    GATEWAY_WIRE_SCHEMA_VERSION,
    MobileHelperBridgeError,
    MobileHelperNotFoundError,
    optional_bool,
    optional_limit,
    optional_project,
    optional_string,
    required_string,
    sase_home,
    skip_record,
)


@dataclass(frozen=True)
class _BeadReadScope:
    project: str | None
    scope: str
    groups: tuple[tuple[str, Path], ...]
    skipped: tuple[dict[str, str | None], ...] = ()


def beads_list_response(request: dict[str, Any]) -> dict[str, Any]:
    scope = _resolve_bead_read_scope(request)
    statuses = _bead_status_filter(
        optional_string(request.get("status"), "status"),
        include_closed=optional_bool(request.get("include_closed"), "include_closed"),
    )
    issue_types = _optional_enum_filter(
        optional_string(request.get("bead_type"), "bead_type"),
        IssueType,
        "bead_type",
    )
    tiers = _optional_enum_filter(
        optional_string(request.get("tier"), "tier"),
        BeadTier,
        "tier",
    )
    limit = optional_limit(request.get("limit"))

    projected: dict[tuple[str, str], tuple[str, Issue, list[Issue], Path | None]] = {}
    skipped = list(scope.skipped)
    for project, beads_dir in scope.groups:
        try:
            all_issues = _read_store_issues(beads_dir)
        except Exception as exc:
            skipped.append(skip_record(project, str(exc)))
            continue
        filtered = _filter_bead_issues(
            all_issues,
            statuses=statuses,
            issue_types=issue_types,
            tiers=tiers,
        )
        for issue in filtered:
            key = (project, issue.id)
            current = projected.get(key)
            if current is None or _issue_sort_key(issue) > _issue_sort_key(current[1]):
                projected[key] = (project, issue, all_issues, beads_dir)

    projected_values = list(projected.values())
    projected_values.sort(key=lambda row: _issue_sort_key(row[1]), reverse=True)
    projected_values.sort(key=lambda row: row[0])
    summaries = [
        _bead_summary_wire(issue, project, all_issues, beads_dir)
        for project, issue, all_issues, beads_dir in projected_values
    ]
    total_count = len(summaries)
    if limit is not None:
        summaries = summaries[:limit]

    return {
        "schema_version": GATEWAY_WIRE_SCHEMA_VERSION,
        "result": _bead_helper_result(
            _beads_list_message(len(summaries), len(skipped)),
            skipped=skipped,
        ),
        "context": {"project": scope.project, "scope": scope.scope},
        "beads": summaries,
        "total_count": total_count,
    }


def beads_show_response(request: dict[str, Any]) -> dict[str, Any]:
    bead_id = required_string(request.get("bead_id"), "bead_id")
    scope = _resolve_bead_read_scope(request)

    best: tuple[str, Issue, list[Issue], Path | None] | None = None
    skipped = list(scope.skipped)
    for project, beads_dir in scope.groups:
        try:
            all_issues = _read_store_issues(beads_dir)
            with open_bead_project_for_beads_dir(beads_dir) as bead_project:
                issue = bead_project.show(bead_id)
        except KeyError:
            continue
        except Exception as exc:
            skipped.append(skip_record(project, str(exc)))
            continue
        if best is None or _issue_sort_key(issue) > _issue_sort_key(best[1]):
            best = (project, issue, all_issues, beads_dir)

    if best is None:
        raise MobileHelperNotFoundError(bead_id)

    project, issue, all_issues, detail_representative_dir = best
    return {
        "schema_version": GATEWAY_WIRE_SCHEMA_VERSION,
        "result": _bead_helper_result(
            f"loaded bead {bead_id}",
            skipped=skipped,
        ),
        "context": {"project": scope.project, "scope": scope.scope},
        "bead": _bead_detail_wire(
            issue, project, all_issues, detail_representative_dir
        ),
    }


def _resolve_bead_read_scope(request: dict[str, Any]) -> _BeadReadScope:
    project = optional_project(request.get("project"))
    all_projects = optional_bool(request.get("all_projects"), "all_projects")
    device_id = optional_string(request.get("device_id"), "device_id")

    if project is not None:
        return _explicit_project_scope(project)
    if not all_projects:
        device_project = _remembered_device_project(device_id)
        if device_project is not None:
            return _device_project_scope(device_project)
    return _all_known_project_scope()


def _explicit_project_scope(project: str) -> _BeadReadScope:
    beads_dir = canonical_beads_dir_for_project(project)
    if beads_dir is None:
        return _BeadReadScope(
            project=project,
            scope="explicit",
            groups=(),
            skipped=(skip_record(project, "no readable bead store"),),
        )
    if not beads_dir.is_dir():
        return _BeadReadScope(
            project=project,
            scope="explicit",
            groups=(),
            skipped=(skip_record(str(beads_dir), "bead store is unavailable"),),
        )
    return _BeadReadScope(
        project=project,
        scope="explicit",
        groups=((project, beads_dir),),
    )


def _device_project_scope(project: str) -> _BeadReadScope:
    explicit = _explicit_project_scope(project)
    return _BeadReadScope(
        project=explicit.project,
        scope="device_default",
        groups=explicit.groups,
        skipped=explicit.skipped,
    )


def _all_known_project_scope() -> _BeadReadScope:
    groups: list[tuple[str, Path]] = []
    for project in _known_project_names():
        beads_dir = canonical_beads_dir_for_project(project)
        if beads_dir is None or not beads_dir.is_dir():
            continue
        groups.append((project, beads_dir))

    return _BeadReadScope(
        project=None,
        scope="all_known",
        groups=tuple(groups),
    )


def _known_project_names() -> list[str]:
    projects_dir = sase_home() / "projects"
    if not projects_dir.is_dir():
        return []

    from sase.core.project_lifecycle_facade import list_project_records

    return [
        record.project_name
        for record in list_project_records(
            projects_dir,
            ("enabled",),
            include_home=False,
        )
        if Path(record.project_file).is_file()
    ]


def _remembered_device_project(device_id: str | None) -> str | None:
    if not device_id:
        return None
    try:
        from sase.integrations.mobile_agents import mobile_device_project_context_path

        context_path = mobile_device_project_context_path(device_id)
        payload = json.loads(context_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    context = payload.get("project_context")
    if not isinstance(context, dict):
        return None
    project = optional_string(context.get("project"), "project")
    if project is None or project == "home":
        return None
    try:
        return optional_project(project)
    except MobileHelperBridgeError:
        return None


def _read_store_issues(beads_dir: Path) -> list[Issue]:
    with open_bead_project_for_beads_dir(beads_dir) as project:
        return project.list_issues()


def _bead_summary_wire(
    issue: Issue,
    project: str | None,
    all_issues: list[Issue],
    beads_dir: Path | None,
) -> dict[str, Any]:
    issue_by_id = {row.id: row for row in all_issues}
    design = _issue_plan_path(
        issue,
        issue_by_id,
        project=project,
        beads_dir=beads_dir,
    )
    return {
        "id": issue.id,
        "title": issue.title,
        "status": issue.status.value,
        "bead_type": issue.issue_type.value,
        "tier": issue.tier.value if issue.tier is not None else None,
        "project": project,
        "parent_id": issue.parent_id,
        "assignee": issue.assignee or None,
        "size": issue.size.value if issue.size is not None else None,
        "plus_one_count": issue.plus_one_count,
        "created_at": issue.created_at or None,
        "updated_at": issue.updated_at or None,
        "dependency_count": len(issue.dependencies),
        "block_count": _block_count(issue.id, all_issues),
        "child_count": _child_count(issue.id, all_issues),
        "plan_path_display": design,
        "patch_name": issue.patch_name or None,
        "changespec_name": issue.changespec_name or None,
        "patch_bug_id": issue.patch_bug_id or None,
        "changespec_bug_id": issue.changespec_bug_id or None,
        "changespec_status": None,
    }


def _bead_detail_wire(
    issue: Issue,
    project: str | None,
    all_issues: list[Issue],
    representative_dir: Path | None,
) -> dict[str, Any]:
    issue_by_id = {row.id: row for row in all_issues}
    blocks = sorted(
        other.id
        for other in all_issues
        for dependency in other.dependencies
        if dependency.depends_on_id == issue.id
    )
    children = sorted(row.id for row in all_issues if row.parent_id == issue.id)
    return {
        "summary": _bead_summary_wire(
            issue,
            project,
            all_issues,
            representative_dir,
        ),
        "description": issue.description or None,
        "notes": issue.notes or None,
        "model": issue.model or None,
        "design_path_display": _issue_plan_path(
            issue,
            issue_by_id,
            project=project,
            beads_dir=representative_dir,
        ),
        "refs": _reference_displays(
            issue.refs,
            project=project,
            beads_dir=representative_dir,
        ),
        "plus_one_evidence": [
            {
                "timestamp": evidence.timestamp,
                "reporter": evidence.reporter,
                "note": evidence.note,
                "refs": _reference_displays(
                    evidence.refs,
                    project=project,
                    beads_dir=representative_dir,
                ),
            }
            for evidence in issue.plus_one_evidence
        ],
        "dependencies": [dependency.depends_on_id for dependency in issue.dependencies],
        "blocks": blocks,
        "children": children,
        "workspace_display": _workspace_display(representative_dir),
    }


def _issue_plan_path(
    issue: Issue,
    issue_by_id: dict[str, Issue],
    *,
    project: str | None,
    beads_dir: Path | None,
) -> str | None:
    reference: str | None = None
    if issue.design:
        reference = issue.design
    elif issue.parent_id:
        parent = issue_by_id.get(issue.parent_id)
        if parent is not None and parent.design:
            reference = parent.design
    if reference is None:
        return None

    workspace_dir = _plan_resolution_workspace(project, beads_dir)
    if workspace_dir is None:
        return reference
    try:
        from sase.sdd.plan_refs import resolve_plan_reference

        resolution = resolve_plan_reference(
            reference,
            workspace_dir=workspace_dir,
            workspace_num=1,
        )
    except Exception:
        return reference
    return (
        str(resolution.resolved_path)
        if resolution.resolved_path is not None
        else reference
    )


def _reference_displays(
    refs: list[str] | tuple[str, ...],
    *,
    project: str | None,
    beads_dir: Path | None,
) -> list[str]:
    """Return each stored reference, resolved where this machine can resolve it.

    A reference that resolves nowhere here — an ``agent:`` from another host,
    a document not yet pushed — still travels to the client in its stored
    form, which is the whole point of storing references instead of paths.
    """

    if not refs:
        return []
    workspace_dir = _plan_resolution_workspace(project, beads_dir)
    if workspace_dir is None:
        return list(refs)
    try:
        from sase.artifact_ref_context import artifact_ref_context
        from sase.artifact_ref_lists import resolve_artifact_ref_list

        entries = resolve_artifact_ref_list(
            refs,
            context=artifact_ref_context(workspace_dir, 1),
        )
    except Exception:
        return list(refs)
    return [
        entry.rendered
        if entry.resolution.resolved_path is None
        else str(entry.resolution.resolved_path)
        for entry in entries
    ]


def _plan_resolution_workspace(
    project: str | None,
    beads_dir: Path | None,
) -> Path | None:
    if project is not None:
        try:
            from sase.running_field import get_workspace_directory

            return Path(get_workspace_directory(project, 1))
        except Exception:
            pass
    if beads_dir is None:
        return None
    parts = beads_dir.parts
    if len(parts) >= 3 and parts[-3:] == (".sase", "sdd", "beads"):
        return beads_dir.parents[2]
    if len(parts) >= 2 and parts[-2:] == ("sdd", "beads"):
        return beads_dir.parents[1]
    return None


def _filter_bead_issues(
    issues: list[Issue],
    *,
    statuses: list[Status] | None,
    issue_types: list[IssueType] | None,
    tiers: list[BeadTier] | None,
) -> list[Issue]:
    result = issues
    if statuses is not None:
        status_set = set(statuses)
        result = [issue for issue in result if issue.status in status_set]
    if issue_types is not None:
        type_set = set(issue_types)
        result = [issue for issue in result if issue.issue_type in type_set]
    if tiers is not None:
        tier_set = set(tiers)
        result = [issue for issue in result if issue.tier in tier_set]
    return result


def _bead_status_filter(
    status: str | None, *, include_closed: bool
) -> list[Status] | None:
    if status is not None:
        return [_enum_value(Status, status, "status")]
    if include_closed:
        return None
    # ``snoozed`` belongs here for the same reason it is in ``sase bead list``
    # and in ``DEFAULT_BEAD_FILTER_QUERY``: a snoozed task is live work the
    # user chose to defer, not a black hole it disappears into.
    return [
        Status.OPEN,
        Status.CLAIMED,
        Status.READY,
        Status.SNOOZED,
        Status.IN_PROGRESS,
    ]


def _optional_enum_filter(
    value: str | None,
    enum_type: type[Status] | type[IssueType] | type[BeadTier],
    field: str,
) -> list[Any] | None:
    if value is None:
        return None
    return [_enum_value(enum_type, value, field)]


def _enum_value(
    enum_type: type[Status] | type[IssueType] | type[BeadTier],
    value: str,
    field: str,
) -> Any:
    try:
        return enum_type(value)
    except ValueError as exc:
        choices = ", ".join(row.value for row in enum_type)
        raise MobileHelperBridgeError(f"{field} must be one of: {choices}") from exc


def _bead_helper_result(
    message: str,
    *,
    skipped: list[dict[str, str | None]],
) -> dict[str, Any]:
    return {
        "status": "partial_success" if skipped else "success",
        "message": message,
        "warnings": [],
        "skipped": skipped,
        "partial_failure_count": len(skipped) if skipped else None,
    }


def _beads_list_message(count: int, skipped_count: int) -> str:
    if skipped_count:
        return f"loaded {count} bead(s), skipped {skipped_count}"
    return f"loaded {count} bead(s)"


def _block_count(issue_id: str, issues: list[Issue]) -> int:
    return sum(
        1
        for other in issues
        for dependency in other.dependencies
        if dependency.depends_on_id == issue_id
    )


def _child_count(issue_id: str, issues: list[Issue]) -> int:
    return sum(1 for issue in issues if issue.parent_id == issue_id)


def _issue_sort_key(issue: Issue) -> tuple[str, str]:
    return (issue.updated_at or issue.created_at or "", issue.id)


def _workspace_display(beads_dir: Path | None) -> str | None:
    if beads_dir is None:
        return None
    parts = beads_dir.parts
    if len(parts) >= 3 and parts[-3:] == (".sase", "sdd", "beads"):
        return str(beads_dir.parents[2])
    if len(parts) >= 2 and parts[-2:] == ("sdd", "beads"):
        return str(beads_dir.parents[1])
    return str(beads_dir)

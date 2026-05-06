"""Hidden mobile helper bridge operations."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TextIO

from sase.bead.model import BeadTier, Issue, IssueType, Status
from sase.bead.workspace import (
    MergedBeadView,
    get_all_project_beads_dirs,
    get_project_beads_dirs_for_project,
)
from sase.integrations.changespec_tags import list_changespec_xprompt_tags
from sase.integrations.chat_install import (
    ChatInstallLaunchResult,
    ChatInstallStatusResult,
    read_chat_install_status,
    start_chat_install_worker,
)
from sase.xprompt.catalog import build_structured_xprompts_catalog

GATEWAY_WIRE_SCHEMA_VERSION = 1
_SAFE_PROJECT_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


class _MobileHelperBridgeError(RuntimeError):
    """Deterministic bridge error for invalid mobile helper requests."""


class _MobileUpdateAlreadyRunning(RuntimeError):
    """Bridge sentinel mapped to update_already_running by the gateway."""


class _MobileUpdateJobNotFound(RuntimeError):
    """Bridge sentinel mapped to update_job_not_found by the gateway."""


class _MobileHelperNotFoundError(_MobileHelperBridgeError):
    """Deterministic bridge error for missing helper records."""


@dataclass(frozen=True)
class _BeadReadScope:
    project: str | None
    scope: str
    groups: tuple[tuple[str | None, tuple[Path, ...]], ...]
    skipped: tuple[dict[str, str | None], ...] = ()


def handle_mobile_helper_bridge(
    args: argparse.Namespace,
    *,
    stdin: TextIO = sys.stdin,
    stdout: TextIO = sys.stdout,
    stderr: TextIO = sys.stderr,
) -> int:
    """Run one fixed mobile helper bridge operation over JSON stdin/stdout."""
    try:
        request = _read_request(stdin)
        operation = getattr(args, "mobile_helper_bridge_subcommand", None)
        if operation == "changespec-tags":
            response = _changespec_tags_response(request)
        elif operation == "xprompt-catalog":
            response = _xprompt_catalog_response(request)
        elif operation == "beads-list":
            response = _beads_list_response(request)
        elif operation == "beads-show":
            response = _beads_show_response(request)
        elif operation == "update-start":
            response = _update_start_response(request)
        elif operation == "update-status":
            response = _update_status_response(request)
        else:
            raise _MobileHelperBridgeError("unknown mobile helper bridge operation")
    except (
        _MobileHelperNotFoundError,
        _MobileUpdateAlreadyRunning,
        _MobileUpdateJobNotFound,
    ) as exc:
        print(f"mobile helper bridge error: {exc}", file=stderr)
        return 4
    except (_MobileHelperBridgeError, ValueError, TypeError) as exc:
        print(f"mobile helper bridge error: {exc}", file=stderr)
        return 2

    json.dump(response, stdout, separators=(",", ":"))
    stdout.write("\n")
    return 0


def _read_request(stdin: TextIO) -> dict[str, Any]:
    raw = stdin.read()
    if not raw.strip():
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise _MobileHelperBridgeError(f"invalid JSON request: {exc.msg}") from exc
    if not isinstance(payload, dict):
        raise _MobileHelperBridgeError("request JSON must be an object")
    return payload


def _changespec_tags_response(request: dict[str, Any]) -> dict[str, Any]:
    project = _optional_string(request.get("project"), "project")
    limit = _optional_limit(request.get("limit"))
    listing = list_changespec_xprompt_tags(project)
    entries = listing.entries
    total_count = len(entries)
    if limit is not None:
        entries = entries[:limit]

    skipped = [_skipped_wire(row) for row in listing.skipped]
    return {
        "schema_version": GATEWAY_WIRE_SCHEMA_VERSION,
        "result": {
            "status": "partial_success" if skipped else "success",
            "message": _changespec_tags_message(len(entries), len(skipped)),
            "warnings": [],
            "skipped": skipped,
            "partial_failure_count": len(skipped) if skipped else None,
        },
        "context": {
            "project": project,
            "scope": "explicit" if project is not None else "all_known",
        },
        "tags": [
            {
                "tag": entry.tag,
                "project": entry.project,
                "changespec": entry.name,
                "title": None,
                "status": entry.status,
                "workflow": entry.workflow_type,
                "source_path_display": None,
            }
            for entry in entries
        ],
        "total_count": total_count,
    }


def _xprompt_catalog_response(request: dict[str, Any]) -> dict[str, Any]:
    project = _optional_string(request.get("project"), "project")
    source = _optional_string(request.get("source"), "source")
    tag = _optional_string(request.get("tag"), "tag")
    query = _optional_string(request.get("query"), "query")
    include_pdf = _optional_bool(request.get("include_pdf"), "include_pdf")
    limit = _optional_limit(request.get("limit"))
    projection = build_structured_xprompts_catalog(
        project=project,
        source=source,
        tag=tag,
        query=query,
        include_pdf=include_pdf,
        limit=limit,
    )
    skipped = [
        {"target": row.target, "reason": row.reason} for row in projection.skipped
    ]
    status = "partial_success" if skipped else "success"
    return {
        "schema_version": GATEWAY_WIRE_SCHEMA_VERSION,
        "result": {
            "status": status,
            "message": _xprompt_catalog_message(len(projection.entries), len(skipped)),
            "warnings": projection.warnings,
            "skipped": skipped,
            "partial_failure_count": len(skipped) if skipped else None,
        },
        "context": {
            "project": project,
            "scope": "explicit" if project is not None else "all_known",
        },
        "entries": [
            {
                "name": entry.name,
                "display_label": entry.display_label,
                "description": entry.description,
                "source_bucket": entry.source_bucket,
                "project": entry.project,
                "tags": entry.tags,
                "input_signature": entry.input_signature,
                "is_skill": entry.is_skill,
                "content_preview": entry.content_preview,
                "source_path_display": entry.source_path_display,
            }
            for entry in projection.entries
        ],
        "stats": {
            "total_count": projection.stats.total_count,
            "project_count": projection.stats.project_count,
            "skill_count": projection.stats.skill_count,
            "pdf_requested": projection.stats.pdf_requested,
        },
        "catalog_attachment": None
        if projection.catalog_attachment is None
        else {
            "display_name": projection.catalog_attachment.display_name,
            "content_type": projection.catalog_attachment.content_type,
            "byte_size": projection.catalog_attachment.byte_size,
            "path_display": projection.catalog_attachment.path_display,
            "generated": projection.catalog_attachment.generated,
        },
    }


def _beads_list_response(request: dict[str, Any]) -> dict[str, Any]:
    scope = _resolve_bead_read_scope(request)
    statuses = _bead_status_filter(
        _optional_string(request.get("status"), "status"),
        include_closed=_optional_bool(request.get("include_closed"), "include_closed"),
    )
    issue_types = _optional_enum_filter(
        _optional_string(request.get("bead_type"), "bead_type"),
        IssueType,
        "bead_type",
    )
    tiers = _optional_enum_filter(
        _optional_string(request.get("tier"), "tier"),
        BeadTier,
        "tier",
    )
    limit = _optional_limit(request.get("limit"))

    projected: dict[str, tuple[str | None, Issue, list[Issue], Path | None]] = {}
    skipped = list(scope.skipped)
    for project, beads_dirs in scope.groups:
        try:
            with MergedBeadView(list(beads_dirs)) as view:
                all_issues = view.list_issues()
        except Exception as exc:
            skipped.append(_skip_record(project or _paths_label(beads_dirs), str(exc)))
            continue
        filtered = _filter_bead_issues(
            all_issues,
            statuses=statuses,
            issue_types=issue_types,
            tiers=tiers,
        )
        representative_dir = beads_dirs[0] if beads_dirs else None
        for issue in filtered:
            current = projected.get(issue.id)
            if current is None or _issue_sort_key(issue) > _issue_sort_key(current[1]):
                projected[issue.id] = (project, issue, all_issues, representative_dir)

    summaries = [
        _bead_summary_wire(issue, project, all_issues)
        for project, issue, all_issues, _ in sorted(
            projected.values(), key=lambda row: _issue_sort_key(row[1]), reverse=True
        )
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


def _beads_show_response(request: dict[str, Any]) -> dict[str, Any]:
    bead_id = _required_string(request.get("bead_id"), "bead_id")
    scope = _resolve_bead_read_scope(request)

    best: tuple[str | None, Issue, list[Issue], Path | None] | None = None
    skipped = list(scope.skipped)
    for project, beads_dirs in scope.groups:
        try:
            with MergedBeadView(list(beads_dirs)) as view:
                issue = view.show(bead_id)
                all_issues = view.list_issues()
        except KeyError:
            continue
        except Exception as exc:
            skipped.append(_skip_record(project or _paths_label(beads_dirs), str(exc)))
            continue
        representative_dir = beads_dirs[0] if beads_dirs else None
        if best is None or _issue_sort_key(issue) > _issue_sort_key(best[1]):
            best = (project, issue, all_issues, representative_dir)

    if best is None:
        raise _MobileHelperNotFoundError(bead_id)

    project, issue, all_issues, representative_dir = best
    return {
        "schema_version": GATEWAY_WIRE_SCHEMA_VERSION,
        "result": _bead_helper_result(
            f"loaded bead {bead_id}",
            skipped=skipped,
        ),
        "context": {"project": scope.project, "scope": scope.scope},
        "bead": _bead_detail_wire(issue, project, all_issues, representative_dir),
    }


def _update_start_response(request: dict[str, Any]) -> dict[str, Any]:
    _reject_unexpected_fields(request, {"schema_version", "request_id", "device_id"})
    _optional_string(request.get("request_id"), "request_id")
    _optional_string(request.get("device_id"), "device_id")

    result = start_chat_install_worker()
    if result.status == "already_running":
        raise _MobileUpdateAlreadyRunning(result.message)
    if result.status in {"config_missing_command", "workspace_resolution_failed"}:
        raise _MobileHelperBridgeError(result.message)

    if result.status == "launch_failed":
        return {
            "schema_version": GATEWAY_WIRE_SCHEMA_VERSION,
            "result": _helper_result("failed", result.message),
            "job": _launch_job_wire(result, "failed"),
        }

    return {
        "schema_version": GATEWAY_WIRE_SCHEMA_VERSION,
        "result": _helper_result("success", result.message),
        "job": _launch_job_wire(result, "running"),
    }


def _update_status_response(request: dict[str, Any]) -> dict[str, Any]:
    _reject_unexpected_fields(request, {"schema_version", "job_id", "device_id"})
    job_id = _required_string(request.get("job_id"), "job_id")
    _optional_string(request.get("device_id"), "device_id")

    result = read_chat_install_status(job_id)
    if result.status == "not_found":
        raise _MobileUpdateJobNotFound(result.message)

    helper_status = "failed" if result.status == "failed" else "success"
    return {
        "schema_version": GATEWAY_WIRE_SCHEMA_VERSION,
        "result": _helper_result(helper_status, result.message),
        "job": _status_job_wire(result),
    }


def _resolve_bead_read_scope(request: dict[str, Any]) -> _BeadReadScope:
    project = _optional_project(request.get("project"))
    all_projects = _optional_bool(request.get("all_projects"), "all_projects")
    device_id = _optional_string(request.get("device_id"), "device_id")

    if project is not None:
        return _explicit_project_scope(project)
    if not all_projects:
        device_project = _remembered_device_project(device_id)
        if device_project is not None:
            return _device_project_scope(device_project)
    return _all_known_project_scope()


def _explicit_project_scope(project: str) -> _BeadReadScope:
    beads_dirs = get_project_beads_dirs_for_project(project)
    if not beads_dirs:
        return _BeadReadScope(
            project=project,
            scope="explicit",
            groups=(),
            skipped=(_skip_record(project, "no readable bead store"),),
        )
    existing_dirs = tuple(path for path in beads_dirs if path.is_dir())
    skipped = tuple(
        _skip_record(str(path), "bead store is unavailable")
        for path in beads_dirs
        if not path.is_dir()
    )
    if not existing_dirs:
        return _BeadReadScope(
            project=project,
            scope="explicit",
            groups=(),
            skipped=skipped,
        )
    return _BeadReadScope(
        project=project,
        scope="explicit",
        groups=((project, existing_dirs),),
        skipped=skipped,
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
    all_dirs = tuple(get_all_project_beads_dirs())
    groups: list[tuple[str | None, tuple[Path, ...]]] = []
    covered: set[Path] = set()
    for project in _known_project_names():
        beads_dirs = get_project_beads_dirs_for_project(project) or []
        usable = tuple(beads_dirs)
        if not usable:
            continue
        groups.append((project, usable))
        covered.update(_resolved_paths(usable))

    orphan_dirs = tuple(
        path for path in all_dirs if path.resolve() not in covered and path.is_dir()
    )
    if orphan_dirs:
        groups.append((None, orphan_dirs))

    return _BeadReadScope(
        project=None,
        scope="all_known",
        groups=tuple(groups),
    )


def _known_project_names() -> list[str]:
    projects_dir = _sase_home() / "projects"
    if not projects_dir.is_dir():
        return []
    result: list[str] = []
    for project_dir in sorted(projects_dir.iterdir()):
        if not project_dir.is_dir():
            continue
        project_name = project_dir.name
        if (project_dir / f"{project_name}.gp").is_file():
            result.append(project_name)
    return result


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
    project = _optional_string(context.get("project"), "project")
    if project is None or project == "home":
        return None
    try:
        return _optional_project(project)
    except _MobileHelperBridgeError:
        return None


def _bead_summary_wire(
    issue: Issue,
    project: str | None,
    all_issues: list[Issue],
) -> dict[str, Any]:
    issue_by_id = {row.id: row for row in all_issues}
    design = _issue_plan_path(issue, issue_by_id)
    return {
        "id": issue.id,
        "title": issue.title,
        "status": issue.status.value,
        "bead_type": issue.issue_type.value,
        "tier": issue.tier.value if issue.tier is not None else None,
        "project": project,
        "parent_id": issue.parent_id,
        "assignee": issue.assignee or None,
        "updated_at": issue.updated_at or None,
        "dependency_count": len(issue.dependencies),
        "block_count": _block_count(issue.id, all_issues),
        "child_count": _child_count(issue.id, all_issues),
        "plan_path_display": design,
        "changespec_name": issue.changespec_name or None,
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
        "summary": _bead_summary_wire(issue, project, all_issues),
        "description": issue.description or None,
        "notes": issue.notes or None,
        "design_path_display": _issue_plan_path(issue, issue_by_id),
        "dependencies": [dependency.depends_on_id for dependency in issue.dependencies],
        "blocks": blocks,
        "children": children,
        "workspace_display": _workspace_display(representative_dir),
    }


def _issue_plan_path(issue: Issue, issue_by_id: dict[str, Issue]) -> str | None:
    if issue.design:
        return issue.design
    if issue.parent_id:
        parent = issue_by_id.get(issue.parent_id)
        if parent is not None and parent.design:
            return parent.design
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
    return [Status.OPEN, Status.IN_PROGRESS]


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
        raise _MobileHelperBridgeError(f"{field} must be one of: {choices}") from exc


def _optional_string(value: object, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise _MobileHelperBridgeError(f"{field} must be a string")
    value = value.strip()
    return value or None


def _optional_limit(value: object) -> int | None:
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool):
        raise _MobileHelperBridgeError("limit must be an integer")
    if value < 0:
        raise _MobileHelperBridgeError("limit must be non-negative")
    return value


def _optional_bool(value: object, field: str) -> bool:
    if value is None:
        return False
    if not isinstance(value, bool):
        raise _MobileHelperBridgeError(f"{field} must be a boolean")
    return value


def _required_string(value: object, field: str) -> str:
    parsed = _optional_string(value, field)
    if parsed is None:
        raise _MobileHelperBridgeError(f"{field} is required")
    return parsed


def _reject_unexpected_fields(request: dict[str, Any], allowed: set[str]) -> None:
    unexpected = sorted(set(request) - allowed)
    if unexpected:
        fields = ", ".join(unexpected)
        raise _MobileHelperBridgeError(f"unexpected request field(s): {fields}")


def _optional_project(value: object) -> str | None:
    project = _optional_string(value, "project")
    if project is None:
        return None
    if (
        "/" in project
        or "\\" in project
        or project in {".", ".."}
        or not _SAFE_PROJECT_NAME_RE.fullmatch(project)
    ):
        raise _MobileHelperBridgeError(
            "project must be a known SASE project name, not a path"
        )
    return project


def _skipped_wire(row: str) -> dict[str, str | None]:
    target, sep, reason = row.partition(": ")
    if not sep:
        return {"target": None, "reason": row}
    return {"target": target, "reason": reason}


def _changespec_tags_message(count: int, skipped_count: int) -> str:
    if skipped_count:
        return f"loaded {count} ChangeSpec tag(s), skipped {skipped_count}"
    return f"loaded {count} ChangeSpec tag(s)"


def _xprompt_catalog_message(count: int, skipped_count: int) -> str:
    if skipped_count:
        return f"loaded {count} xprompt(s), skipped {skipped_count}"
    return f"loaded {count} xprompt(s)"


def _helper_result(status: str, message: str) -> dict[str, object]:
    return {
        "status": status,
        "message": message,
        "warnings": [],
        "skipped": [],
        "partial_failure_count": None,
    }


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


def _launch_job_wire(result: ChatInstallLaunchResult, status: str) -> dict[str, object]:
    return {
        "job_id": result.job_id or "",
        "status": status,
        "started_at": None,
        "finished_at": None,
        "message": result.message,
        "log_path_display": _path_display(result.log_path),
        "completion_path_display": _path_display(result.status_path),
    }


def _status_job_wire(result: ChatInstallStatusResult) -> dict[str, object]:
    return {
        "job_id": result.job_id,
        "status": result.status,
        "started_at": result.started_at,
        "finished_at": result.finished_at,
        "message": result.message,
        "log_path_display": _path_display(result.log_path),
        "completion_path_display": _path_display(result.completion_path),
    }


def _path_display(path: object) -> str | None:
    if path is None:
        return None
    return str(path)


def _skip_record(target: str | None, reason: str) -> dict[str, str | None]:
    return {"target": target, "reason": reason}


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


def _paths_label(paths: Iterable[Path]) -> str:
    return ",".join(str(path) for path in paths)


def _resolved_paths(paths: Iterable[Path]) -> set[Path]:
    return {path.resolve() for path in paths}


def _sase_home() -> Path:
    import os

    return Path(os.environ.get("SASE_HOME") or Path.home() / ".sase").expanduser()

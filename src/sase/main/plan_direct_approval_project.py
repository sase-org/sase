"""Planner and project resolution for gateless plan approvals."""

from __future__ import annotations

from pathlib import Path

from sase.main.plan_direct_approval_types import (
    DirectApprovalRefusal,
    DirectApprovalRequest,
)


def resolve_planner(source_path: Path, history: object) -> str | None:
    action_data = getattr(history, "action_data", None)
    if isinstance(action_data, dict):
        for key in ("agent_name", "agent_cl_name"):
            value = action_data.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    try:
        from sase.bead.attribution import plan_proposed_by
    except Exception:
        return None
    try:
        return plan_proposed_by(source_path)
    except Exception:
        return None


def resolve_project(
    request: DirectApprovalRequest,
    source_path: Path,
    history: object,
    planner: str | None,
) -> str | DirectApprovalRefusal:
    if request.project:
        canonical = _canonicalize_project(request.project)
        if canonical is None:
            return DirectApprovalRefusal(
                code="unknown_project",
                header=f"\u2717 unknown project {request.project}",
                detail_lines=("See `sase project list` for known projects.",),
                hints=("sase project list",),
            )
        return canonical
    from sase.sdd.plan_project import read_plan_project_file

    frontmatter_project = read_plan_project_file(source_path)
    if frontmatter_project is not None:
        canonical = _canonicalize_project(frontmatter_project)
        try:
            from sase.bead.cross_project import origin_for_project_ref

            origin = (
                origin_for_project_ref(canonical) if canonical is not None else None
            )
        except Exception:
            origin = None
        if origin is None:
            return DirectApprovalRefusal(
                code="unknown_project",
                header=f"\u2717 unknown project {frontmatter_project}",
                detail_lines=(
                    "The plan's project field must name a registered, enabled project.",
                    "Pass one with -P/--project (see `sase project list`).",
                ),
                hints=("sase project list",),
            )
        return origin.project_key
    action_data = getattr(history, "action_data", None)
    if isinstance(action_data, dict) and action_data:
        project = _project_from_action_data(action_data)
        if project:
            return project
    if planner:
        project = _project_from_planner(planner)
        if project:
            return project
    project = _project_from_marker(source_path)
    if project:
        return project
    project = _project_from_cwd()
    if project:
        return project
    from sase.main._plan_direct_approval_shared import plan_stem

    name = plan_stem(source_path)
    return DirectApprovalRefusal(
        code="unknown_project",
        header=f"\u2717 cannot tell which project {name} belongs to",
        detail_lines=("Pass one with -P/--project (see `sase project list`)",),
        hints=("sase project list",),
    )


def project_tag_for(project: str) -> str:
    try:
        from sase.project_tags.catalog import load_project_tag_catalog
        from sase.project_tags.tags import known_project_tag_for

        tag = known_project_tag_for(load_project_tag_catalog(), project)
    except Exception:
        tag = None
    return tag or f"+{project}"


def _project_from_action_data(action_data: dict[str, str]) -> str | None:
    try:
        from sase._plan_approval_artifacts import resolve_plan_action_project_name

        return resolve_plan_action_project_name(action_data)
    except Exception:
        return None


def _project_from_planner(planner: str) -> str | None:
    try:
        from sase.agent.names import find_named_agent
    except Exception:
        return None
    try:
        named = find_named_agent(planner)
    except Exception:
        return None
    if named is None:
        return None
    artifacts_dir = getattr(named, "artifacts_dir", None)
    if not artifacts_dir:
        return None
    try:
        from sase.core.agent_artifact_paths import parse_agent_artifact_path

        info = parse_agent_artifact_path(artifacts_dir)
    except Exception:
        return None
    return info.project_name if info is not None else None


def _project_from_marker(source_path: Path) -> str | None:
    try:
        from sase.workspace_provider.marker import find_marker_from_cwd

        found = find_marker_from_cwd(str(source_path.expanduser().parent))
    except Exception:
        return None
    if found is None:
        return None
    project_key = getattr(found[1], "project_key", "")
    return project_key or None


def _project_from_cwd() -> str | None:
    try:
        from sase.main.utils import ensure_project_file_and_get_workspace_num

        project_info = ensure_project_file_and_get_workspace_num(create_missing=False)
    except Exception:
        return None
    if project_info is None:
        return None
    return project_info[2]


def _canonicalize_project(project: str) -> str | None:
    try:
        from sase.project_aliases import resolve_project_alias_ref
    except Exception:
        resolve_project_alias_ref = None  # type: ignore[assignment]
    value = project.strip()
    if resolve_project_alias_ref is not None:
        try:
            value = resolve_project_alias_ref(value)
        except Exception:
            pass
    try:
        from sase.core.paths import is_valid_sase_project_name

        if not is_valid_sase_project_name(value):
            return None
    except Exception:
        if not value:
            return None
    return value


def display_project_name(project: str) -> str:
    """Return a project's effective display name for human-facing output."""
    try:
        from sase.project_aliases import registered_project_records
        from sase.core.project_lifecycle_wire import effective_project_name

        record = next(
            (
                item
                for item in registered_project_records()
                if item.project_name == project
            ),
            None,
        )
        if record is not None:
            return effective_project_name(record)
    except Exception:
        pass
    return project


__all__ = [
    "display_project_name",
    "project_tag_for",
    "resolve_planner",
    "resolve_project",
]

"""Plan approval artifact and durable-plan path resolution."""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path

from sase._plan_approval_protocol import PlanApprovalActionContext


def durable_plan_file_for_context(
    notification: PlanApprovalActionContext,
) -> Path | None:
    """Resolve the durable proposal file represented by an approval context."""
    explicit = _nonempty(notification.host_action_data.get("original_plan_file"))
    if explicit is not None:
        return Path(explicit).expanduser()

    from sase.plan_gate import (
        original_plan_file_for_resource,
        original_plan_file_from_bundle,
    )

    for raw_file in notification.host_files:
        if original := original_plan_file_for_resource(Path(raw_file)):
            return original
    for key in ("bundle_path", "response_dir"):
        raw_bundle = _nonempty(notification.host_action_data.get(key))
        if raw_bundle and (
            original := original_plan_file_from_bundle(Path(raw_bundle))
        ):
            return original
    return None


def resolve_plan_agent_artifacts_dir(action_data: Mapping[str, str]) -> str | None:
    """Resolve the agent artifact dir carried by a plan-approval notification."""
    explicit = _nonempty(action_data.get("artifacts_dir"))
    if explicit:
        resolved = _existing_agent_artifacts_dir(explicit)
        if resolved is not None:
            return resolved

    timestamp = _normalize_agent_timestamp(action_data.get("agent_timestamp"))
    if timestamp is None:
        return None

    project_name = _plan_action_project_name(action_data)
    if project_name is None:
        return None

    workflow_dir = (
        _nonempty(action_data.get("agent_workflow_dir"))
        or _nonempty(action_data.get("workflow_dir"))
        or "ace-run"
    )
    resolved = _resolve_project_timestamp_artifacts_dir(
        project_name, workflow_dir, timestamp
    )
    if resolved is not None:
        return resolved
    if workflow_dir != "ace-run":
        return None
    return _find_project_timestamp_artifacts_dir(project_name, timestamp)


def _nonempty(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _existing_agent_artifacts_dir(path: str) -> str | None:
    try:
        from sase.core.agent_artifact_paths import resolve_agent_artifact_path

        candidate = resolve_agent_artifact_path(path)
    except Exception:
        candidate = Path(path).expanduser()
    return str(candidate) if candidate.is_dir() else None


def _normalize_agent_timestamp(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        from sase.ace.tui.models._timestamps import normalize_to_14_digit

        return normalize_to_14_digit(value.strip())
    except Exception:
        return value.strip() or None


def _plan_action_project_name(action_data: Mapping[str, str]) -> str | None:
    if project_file := _nonempty(action_data.get("agent_project_file")):
        return _canonical_plan_project_name(Path(project_file).expanduser().parent.name)

    if project_dir := _nonempty(action_data.get("project_dir")):
        try:
            from sase.workspace_provider import get_workspace_name

            workspace_name = get_workspace_name(str(Path(project_dir).expanduser()))
        except Exception:
            workspace_name = None
        if workspace_name:
            project_name = _canonical_plan_project_name(workspace_name)
            if project_name is not None:
                return project_name
        basename = re.sub(r"_\d+$", "", Path(project_dir).expanduser().name)
        return _canonical_plan_project_name(basename)

    return None


def _canonical_plan_project_name(value: str) -> str | None:
    try:
        from sase.project_aliases import resolve_project_alias_ref

        value = resolve_project_alias_ref(value)
    except Exception:
        pass
    try:
        from sase.core.paths import is_valid_sase_project_name

        if not is_valid_sase_project_name(value):
            return None
    except Exception:
        return None
    return value


def _resolve_project_timestamp_artifacts_dir(
    project_name: str,
    workflow_dir: str,
    timestamp: str,
) -> str | None:
    try:
        from sase.core.agent_artifact_paths import resolve_agent_artifact_timestamp_path

        candidate = resolve_agent_artifact_timestamp_path(
            project_name,
            workflow_dir,
            timestamp,
        )
    except Exception:
        from sase.core.paths import sase_projects_dir

        candidate = (
            sase_projects_dir() / project_name / "artifacts" / workflow_dir / timestamp
        )
    return str(candidate) if candidate.is_dir() else None


def _find_project_timestamp_artifacts_dir(
    project_name: str,
    timestamp: str,
) -> str | None:
    from sase.core.paths import sase_projects_dir

    artifacts_root = sase_projects_dir() / project_name / "artifacts"
    if not artifacts_root.is_dir():
        return None
    try:
        workflow_dirs = [path for path in artifacts_root.iterdir() if path.is_dir()]
    except OSError:
        return None
    for workflow_dir in sorted(workflow_dirs, key=lambda path: path.name):
        resolved = _resolve_project_timestamp_artifacts_dir(
            project_name,
            workflow_dir.name,
            timestamp,
        )
        if resolved is not None:
            return resolved
    return None

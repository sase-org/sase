"""VCS/ChangeSpec launch context helpers for ``sase bead work``."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from sase.core.paths import sase_projects_dir

if TYPE_CHECKING:
    from sase.bead.work import ChangeSpecLaunchContext, VCSLaunchContext


def resolve_changespec_launch_context(
    *,
    changespec_name: str,
    bug_id: str,
) -> ChangeSpecLaunchContext:
    """Resolve VCS/project context for a ChangeSpec-attached epic launch."""
    from sase.bead.work import ChangeSpecLaunchContext

    vcs_context = _resolve_required_vcs_launch_context(
        purpose="ChangeSpec-attached epic"
    )

    return ChangeSpecLaunchContext(
        changespec_name=changespec_name,
        bug_id=bug_id,
        vcs_workflow=vcs_context.vcs_workflow,
        project_name=vcs_context.project_name,
    )


def resolve_vcs_launch_context() -> VCSLaunchContext | None:
    """Best-effort VCS/project context for regular epic launches."""
    try:
        return _resolve_required_vcs_launch_context(purpose="regular epic")
    except ValueError:
        return None


def resolve_task_vcs_launch_context() -> VCSLaunchContext:
    """Resolve the required VCS/project context for a task-bead launch."""
    return _resolve_required_vcs_launch_context(purpose="task bead")


def _resolve_required_vcs_launch_context(*, purpose: str) -> VCSLaunchContext:
    """Resolve current project/workflow context or raise a purpose-specific error."""
    from sase.bead.project_name import infer_project_name_from_cwd
    from sase.bead.work import VCSLaunchContext
    from sase.workspace_provider import detect_workflow_type

    project_name = infer_project_name_from_cwd()
    if not project_name:
        raise ValueError(
            f"cannot launch {purpose}: unable to infer the current SASE "
            "project from this workspace"
        )

    from sase.ace.patch.project_spec_path import preferred_project_spec_path

    project_dir = sase_projects_dir() / project_name
    project_file = Path(preferred_project_spec_path(str(project_dir), project_name))
    if not project_file.exists():
        raise ValueError(
            f"cannot launch {purpose}: project file not found at {project_file}"
        )

    try:
        vcs_workflow = detect_workflow_type(str(project_file))
    except ValueError as exc:
        raise ValueError(
            f"cannot launch {purpose}: unable to detect VCS workflow for "
            f"{project_file}: {exc}"
        ) from exc

    return VCSLaunchContext(vcs_workflow=vcs_workflow, project_name=project_name)

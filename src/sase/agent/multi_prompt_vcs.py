"""VCS context resolution for multi-prompt launches."""

from dataclasses import dataclass


@dataclass(frozen=True)
class SegmentVcsContext:
    cl_name: str
    project_file: str
    project_name: str
    is_home_mode: bool
    vcs_ref: tuple[str, str] | None
    history_sort_key: str
    update_target: str
    workspace_num: int | None = None
    workspace_dir: str | None = None


def extract_vcs_ref(prompt: str) -> tuple[str, str] | None:
    """Return the first VCS ref present in *prompt*, if any."""
    from sase.project_aliases import canonicalize_project_aliases_in_prompt
    from sase.workspace_provider import get_ref_patterns

    prompt = canonicalize_project_aliases_in_prompt(prompt)
    for wf_name, pattern in get_ref_patterns().items():
        match = pattern.search(prompt)
        if match is None:
            continue
        ref_value = match.group(1) or match.group(2)
        if ref_value:
            return wf_name, ref_value
    return None


def _resolve_known_project_segment_context(
    *,
    prompt: str,
    has_wait: bool,
) -> SegmentVcsContext | None:
    from pathlib import Path

    from sase.ace.patch.project_spec_path import preferred_project_spec_path
    from sase.agent.launch_projects import (
        enable_known_project_for_launch_ref,
        extract_known_project_vcs_launch_ref,
    )
    from sase.core.paths import sase_projects_dir
    from sase.vcs_provider import VCS_DEFAULT_REVISION
    from sase.xprompt._parsing import resolve_known_project_ref
    from sase.xprompt.loader import get_known_project_workspaces

    known_ref = extract_known_project_vcs_launch_ref(prompt)
    if known_ref is None:
        return None

    wf_name, ref_value = known_ref
    enable_known_project_for_launch_ref(ref_value)
    workspaces = get_known_project_workspaces()
    project_name = resolve_known_project_ref(ref_value, workspaces)
    if project_name is None:
        return None
    workspace_dir = workspaces.get(project_name)
    if workspace_dir is None:
        return None

    project_dir = sase_projects_dir() / project_name
    project_file = Path(preferred_project_spec_path(str(project_dir), project_name))
    return SegmentVcsContext(
        cl_name=project_name,
        project_file=str(project_file),
        project_name=project_name,
        is_home_mode=False,
        vcs_ref=(wf_name, project_name),
        history_sort_key=project_name,
        update_target=VCS_DEFAULT_REVISION,
        workspace_num=0 if has_wait else None,
        workspace_dir=str(workspace_dir) if has_wait else None,
    )


def resolve_segment_vcs_context(
    *,
    prompt: str,
    fallback_cl_name: str,
    fallback_project_file: str,
    fallback_project_name: str,
    fallback_is_home_mode: bool,
    fallback_vcs_ref: tuple[str, str] | None,
    has_wait: bool,
) -> SegmentVcsContext:
    """Resolve launch metadata for one multi-prompt segment.

    Multi-prompts can mix VCS refs across segments.  The launcher therefore
    derives the display Patch, project context, VCS ref, and history key
    from the segment's own VCS ref when present, falling back to the caller's
    context for legacy prompts that rely on an already-selected ChangeSpec.
    Normal VCS segments leave workspace selection to the shared launch executor;
    deferred ``%wait`` segments keep their resolved workspace context.
    """
    from sase.ace.tui.actions.agent_workflow._ref_resolution import (
        resolve_ref_from_prompt,
    )

    known_project_context = _resolve_known_project_segment_context(
        prompt=prompt,
        has_wait=has_wait,
    )
    segment_vcs_ref = extract_vcs_ref(prompt) or fallback_vcs_ref
    if segment_vcs_ref is None:
        if known_project_context is not None:
            return known_project_context
        return SegmentVcsContext(
            cl_name=fallback_cl_name,
            project_file=fallback_project_file,
            project_name=fallback_project_name,
            is_home_mode=fallback_is_home_mode,
            vcs_ref=None,
            history_sort_key="",
            update_target="",
        )

    wf_name, ref_value = segment_vcs_ref
    from sase.vcs_provider import VCS_DEFAULT_REVISION

    update_target = VCS_DEFAULT_REVISION
    resolved = resolve_ref_from_prompt(
        prompt,
        wf_name,
        skip_workspace=True,
    )
    if resolved is None:
        if known_project_context is not None:
            return known_project_context
        return SegmentVcsContext(
            cl_name=ref_value,
            project_file=fallback_project_file,
            project_name=fallback_project_name,
            is_home_mode=fallback_is_home_mode,
            vcs_ref=segment_vcs_ref,
            history_sort_key=ref_value,
            update_target=update_target,
        )

    project_file, project_name, workspace_dir, workspace_num, resolved_ref = resolved
    return SegmentVcsContext(
        cl_name=resolved_ref,
        project_file=project_file,
        project_name=project_name,
        is_home_mode=False,
        vcs_ref=(wf_name, resolved_ref),
        history_sort_key=resolved_ref,
        update_target=update_target,
        workspace_num=workspace_num if has_wait else None,
        workspace_dir=workspace_dir if has_wait else None,
    )

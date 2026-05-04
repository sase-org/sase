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
    from sase.workspace_provider import get_ref_patterns

    for wf_name, pattern in get_ref_patterns().items():
        match = pattern.search(prompt)
        if match is None:
            continue
        ref_value = match.group(1) or match.group(2)
        if ref_value:
            return wf_name, ref_value
    return None


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
    derives the display CL, workspace/project context, pre-allocation ref, and
    history key from the segment's own VCS ref when present, falling back to the
    caller's context for legacy prompts that rely on an already-selected CL.
    """
    from sase.ace.tui.actions.agent_workflow._ref_resolution import (
        is_non_workspace_workflow,
        resolve_ref_from_prompt,
    )

    segment_vcs_ref = extract_vcs_ref(prompt) or fallback_vcs_ref
    if segment_vcs_ref is None:
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
    if is_non_workspace_workflow(wf_name):
        update_target = ""
    else:
        from sase.vcs_provider import VCS_DEFAULT_REVISION

        update_target = VCS_DEFAULT_REVISION
    resolved = resolve_ref_from_prompt(prompt, wf_name, skip_workspace=has_wait)
    if resolved is None:
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
        is_home_mode=is_non_workspace_workflow(wf_name),
        vcs_ref=(wf_name, resolved_ref),
        history_sort_key=resolved_ref,
        update_target=update_target,
        workspace_num=workspace_num,
        workspace_dir=workspace_dir,
    )

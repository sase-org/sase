"""Reference resolution for registered workspace refs in prompts."""

from __future__ import annotations


def resolve_ref_from_prompt(
    prompt: str,
    workflow_type: str,
    *,
    skip_workspace: bool = False,
) -> tuple[str, str, str, int, str] | None:
    """Resolve a VCS reference from a prompt using the plugin system.

    Matches the regex pattern for the given *workflow_type*, resolves the
    reference via ``resolve_ref()``, and obtains the workspace directory
    appropriate for the workflow type.

    When *skip_workspace* is True, workspace allocation is skipped and the
    primary workspace directory is returned with workspace_num=0. This is used
    for agents with ``%wait`` directives that should defer workspace claiming
    until their dependencies are resolved.
    """
    from sase.project_aliases import canonicalize_project_aliases_in_prompt
    from sase.running_field import get_first_available_axe_workspace
    from sase.workspace_provider import (
        get_ref_patterns,
        get_workspace_directory,
        resolve_ref,
    )
    from sase.workspace_provider.utils import ProjectProviderMismatchError

    prompt = canonicalize_project_aliases_in_prompt(prompt)
    patterns = get_ref_patterns()
    pattern = patterns.get(workflow_type)
    if pattern is None:
        return None

    match = pattern.search(prompt)
    if match is None:
        return None

    ref = match.group(1) or match.group(2)
    if not ref:
        return None

    try:
        resolved = resolve_ref(ref, workflow_type)
        if skip_workspace:
            workspace_num = 0
            workspace_dir = resolved.primary_workspace_dir
        else:
            workspace_num = get_first_available_axe_workspace(resolved.project_file)
            workspace_dir = get_workspace_directory(
                workflow_type,
                workspace_num,
                resolved.project_name,
                resolved.primary_workspace_dir,
            )
    except ProjectProviderMismatchError:
        raise
    except (ValueError, RuntimeError):
        if workflow_type == "git" and ref == "home":
            raise
        return None

    return (
        resolved.project_file,
        resolved.project_name,
        workspace_dir,
        workspace_num,
        resolved.canonical_ref or ref,
    )

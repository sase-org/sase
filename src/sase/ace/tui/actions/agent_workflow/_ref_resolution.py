"""Reference resolution for VCS refs (e.g. #gh, #git, #hg) in prompts."""

from __future__ import annotations


class RefResolutionMixin:
    """Mixin providing dynamic VCS reference resolution."""

    def _resolve_vcs_from_prompt(
        self, prompt: str, workflow_type: str
    ) -> tuple[str, str, str, int, str] | None:
        """Extract and resolve a VCS reference for *workflow_type* from *prompt*.

        Returns (project_file, project_name, workspace_dir, workspace_num,
        ref) or None if not found or resolution fails.
        """
        return _resolve_ref_from_prompt(prompt, workflow_type)


def _resolve_ref_from_prompt(
    prompt: str, workflow_type: str
) -> tuple[str, str, str, int, str] | None:
    """Resolve a VCS reference from a prompt using the plugin system.

    Matches the regex pattern for the given *workflow_type*, resolves the
    reference via ``resolve_ref()``, and obtains the workspace directory
    appropriate for the workflow type.
    """
    from sase.running_field import get_first_available_axe_workspace
    from sase.workspace_provider import (
        get_ref_patterns,
        get_workspace_directory,
        resolve_ref,
    )

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
        workspace_num = get_first_available_axe_workspace(resolved.project_file)
        workspace_dir = get_workspace_directory(
            workflow_type,
            workspace_num,
            resolved.project_name,
            resolved.primary_workspace_dir,
        )
    except (ValueError, RuntimeError):
        return None

    return (
        resolved.project_file,
        resolved.project_name,
        workspace_dir,
        workspace_num,
        ref,
    )


def strip_all_vcs_refs(prompt: str) -> str:
    """Remove all VCS ref tags from *prompt*."""
    from sase.workspace_provider import get_ref_patterns

    for pattern in get_ref_patterns().values():
        prompt = pattern.sub("", prompt)
    return prompt.strip()

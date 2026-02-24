"""Reference resolution mixin for #gh, #git, #hg refs in prompts."""

from __future__ import annotations

import re

_GH_REF_PATTERN = re.compile(r"(?:^|(?<=\s))#gh(?::([a-zA-Z0-9_./-]+)|\(([^)]+)\))")
_GIT_REF_PATTERN = re.compile(r"(?:^|(?<=\s))#git(?::([a-zA-Z0-9_./-]+)|\(([^)]+)\))")
_HG_REF_PATTERN = re.compile(r"(?:^|(?<=\s))#hg(?::([a-zA-Z0-9_./-]+)|\(([^)]+)\))")

_VCS_PATTERNS = {
    "gh": _GH_REF_PATTERN,
    "git": _GIT_REF_PATTERN,
    "hg": _HG_REF_PATTERN,
}


class RefResolutionMixin:
    """Mixin providing #gh, #git, #hg reference resolution."""

    def _resolve_gh_from_prompt(
        self, prompt: str
    ) -> tuple[str, str, str, int, str] | None:
        """Extract and resolve a #gh reference from a prompt.

        Returns (project_file, project_name, workspace_dir, workspace_num,
        gh_ref) or None if not found or resolution fails.
        """
        return _resolve_ref_from_prompt(prompt, "gh")

    def _resolve_git_from_prompt(
        self, prompt: str
    ) -> tuple[str, str, str, int, str] | None:
        """Extract and resolve a #git reference from a prompt.

        Returns (project_file, project_name, workspace_dir, workspace_num,
        git_ref) or None if not found or resolution fails.
        """
        return _resolve_ref_from_prompt(prompt, "git")

    def _resolve_hg_from_prompt(
        self, prompt: str
    ) -> tuple[str, str, str, int, str] | None:
        """Extract and resolve a #hg reference from a prompt.

        Returns (project_file, project_name, workspace_dir, workspace_num,
        hg_ref) or None if not found or resolution fails.
        """
        return _resolve_ref_from_prompt(prompt, "hg")


def _resolve_ref_from_prompt(
    prompt: str, workflow_type: str
) -> tuple[str, str, str, int, str] | None:
    """Resolve a VCS reference from a prompt using the plugin system.

    Matches the regex pattern for the given *workflow_type*, resolves the
    reference via ``resolve_ref()``, and obtains the workspace directory
    appropriate for the workflow type.
    """
    from sase.running_field import (
        get_first_available_axe_workspace,
        get_workspace_directory_for_num,
    )
    from sase.workspace_provider import resolve_ref

    pattern = _VCS_PATTERNS.get(workflow_type)
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

        if workflow_type == "hg":
            workspace_dir, _ = get_workspace_directory_for_num(
                workspace_num, resolved.project_name
            )
        else:
            from sase.workspace_utils import ensure_git_clone

            workspace_dir = ensure_git_clone(
                resolved.primary_workspace_dir, workspace_num
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

"""Reference resolution mixin for #gh, #git, #hg refs in prompts."""

from __future__ import annotations

import os
import re

_GH_REF_PATTERN = re.compile(r"(?:^|(?<=\s))#gh(?::([a-zA-Z0-9_./-]+)|\(([^)]+)\))")
_GIT_REF_PATTERN = re.compile(r"(?:^|(?<=\s))#git(?::([a-zA-Z0-9_./-]+)|\(([^)]+)\))")
_HG_REF_PATTERN = re.compile(r"(?:^|(?<=\s))#hg(?::([a-zA-Z0-9_./-]+)|\(([^)]+)\))")


class RefResolutionMixin:
    """Mixin providing #gh, #git, #hg reference resolution."""

    def _resolve_gh_from_prompt(
        self, prompt: str
    ) -> tuple[str, str, str, int, str] | None:
        """Extract and resolve a #gh reference from a prompt.

        Returns (project_file, project_name, workspace_dir, workspace_num,
        gh_ref) or None if not found or resolution fails.
        """
        from sase.gh_workspace import ensure_git_clone, resolve_gh_ref
        from sase.running_field import get_first_available_axe_workspace

        match = _GH_REF_PATTERN.search(prompt)
        if match is None:
            return None

        gh_ref = match.group(1) or match.group(2)
        if not gh_ref:
            return None

        try:
            resolved = resolve_gh_ref(gh_ref)
            workspace_num = get_first_available_axe_workspace(resolved.project_file)
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
            gh_ref,
        )

    def _resolve_git_from_prompt(
        self, prompt: str
    ) -> tuple[str, str, str, int, str] | None:
        """Extract and resolve a #git reference from a prompt.

        Returns (project_file, project_name, workspace_dir, workspace_num,
        git_ref) or None if not found or resolution fails.
        """
        from sase.gh_workspace import ensure_git_clone
        from sase.git_workspace import resolve_git_ref
        from sase.running_field import get_first_available_axe_workspace

        match = _GIT_REF_PATTERN.search(prompt)
        if match is None:
            return None

        git_ref = match.group(1) or match.group(2)
        if not git_ref:
            return None

        try:
            resolved = resolve_git_ref(git_ref)
            workspace_num = get_first_available_axe_workspace(resolved.project_file)
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
            git_ref,
        )

    def _resolve_hg_from_prompt(
        self, prompt: str
    ) -> tuple[str, str, str, int, str] | None:
        """Extract and resolve a #hg reference from a prompt.

        Returns (project_file, project_name, workspace_dir, workspace_num,
        hg_ref) or None if not found or resolution fails.
        """
        from sase.ace.changespec import find_all_changespecs
        from sase.running_field import (
            get_first_available_axe_workspace,
            get_workspace_directory_for_num,
        )

        match = _HG_REF_PATTERN.search(prompt)
        if match is None:
            return None

        hg_ref = match.group(1) or match.group(2)
        if not hg_ref:
            return None

        try:
            # Resolve hg_ref as changespec name or project shorthand
            cs_match = None
            for cs in find_all_changespecs():
                if cs.name == hg_ref:
                    cs_match = cs
                    break

            if cs_match:
                project_name = cs_match.project_basename
                project_file = cs_match.file_path
            else:
                candidate = os.path.expanduser(f"~/.sase/projects/{hg_ref}/{hg_ref}.gp")
                if os.path.isfile(candidate):
                    project_name = hg_ref
                    project_file = candidate
                else:
                    return None

            workspace_num = get_first_available_axe_workspace(project_file)
            workspace_dir, _ = get_workspace_directory_for_num(
                workspace_num, project_name
            )
        except (ValueError, RuntimeError):
            return None

        return (
            project_file,
            project_name,
            workspace_dir,
            workspace_num,
            hg_ref,
        )

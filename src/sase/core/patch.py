"""Patch name manipulation utilities."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sase.ace.patch import Patch


def ensure_project_prefix(project_name: str, patch_name: str) -> str:
    """Ensure *patch_name* starts with ``<project_name>_``."""
    prefix = f"{project_name}_"
    if patch_name.startswith(prefix):
        return patch_name
    return f"{prefix}{patch_name}"


def strip_reverted_suffix(name: str) -> str:
    """Remove a ``_<N>`` or legacy ``__<N>`` uniqueness suffix from a Patch name."""
    match = re.match(r"^(.+)__\d+$", name)
    if match:
        return match.group(1)
    match = re.match(r"^(.+)_\d+$", name)
    return match.group(1) if match else name


def patch_names_match(name_a: str, name_b: str) -> bool:
    """Return whether two Patch names refer to the same logical Patch."""
    if name_a == name_b:
        return True
    return strip_reverted_suffix(name_a) == name_b or name_a == strip_reverted_suffix(
        name_b
    )


def patch_name_to_branch(name: str, project_basename: str) -> str:
    """Derive the git branch name from a Patch ``NAME``."""
    name = strip_reverted_suffix(name)
    prefix = f"{project_basename}_"
    if name.startswith(prefix):
        name = name[len(prefix) :]
    return name.replace("_", "-")


def patch_name_to_branch_with_suffix(name: str, project_basename: str) -> str:
    """Derive the git branch name from a Patch name, preserving the ``_<N>`` suffix."""
    prefix = f"{project_basename}_"
    if name.startswith(prefix):
        name = name[len(prefix) :]
    match = re.match(r"^(.+)__(\d+)$", name)
    if match:
        base = match.group(1).replace("_", "-")
        return f"{base}__{match.group(2)}"
    match = re.match(r"^(.+)_(\d+)$", name)
    if match:
        base = match.group(1).replace("_", "-")
        return f"{base}_{match.group(2)}"
    return name.replace("_", "-")


def has_suffix(name: str) -> bool:
    """Return whether a Patch name has a ``_<N>`` or legacy ``__<N>`` suffix."""
    return bool(re.match(r"^.+__\d+$", name) or re.match(r"^.+_\d+$", name))


def get_next_suffix_number(base_name: str, existing_names: set[str]) -> int:
    """Find the lowest positive suffix number available for *base_name*."""
    n = 1
    while f"{base_name}_{n}" in existing_names or f"{base_name}__{n}" in existing_names:
        n += 1
    return n


def get_workspace_directory_for_patch(patch: Patch) -> str | None:
    """Get the workspace directory for a Patch."""
    from sase.running_field import get_workspace_directory as get_workspace_dir

    try:
        return get_workspace_dir(patch.project_basename)
    except RuntimeError:
        return None


__all__ = [
    "ensure_project_prefix",
    "get_next_suffix_number",
    "get_workspace_directory_for_patch",
    "has_suffix",
    "patch_name_to_branch",
    "patch_name_to_branch_with_suffix",
    "patch_names_match",
    "strip_reverted_suffix",
]

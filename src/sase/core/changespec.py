"""ChangeSpec name manipulation utilities."""

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sase.ace.changespec import ChangeSpec


def ensure_project_prefix(project_name: str, cl_name: str) -> str:
    """Ensure *cl_name* starts with ``<project_name>_``.

    If the prefix is already present, return as-is; otherwise prepend it.
    """
    prefix = f"{project_name}_"
    if cl_name.startswith(prefix):
        return cl_name
    return f"{prefix}{cl_name}"


def strip_reverted_suffix(name: str) -> str:
    """Remove the _<N> suffix from a reverted ChangeSpec name.

    Supports both legacy ``__<N>`` and current ``_<N>`` suffixes.

    Args:
        name: ChangeSpec name (e.g., "foobar_feature_2")

    Returns:
        Name without the suffix (e.g., "foobar_feature")
    """
    # Try legacy double-underscore first to avoid partial matches
    match = re.match(r"^(.+)__\d+$", name)
    if match:
        return match.group(1)
    # Then try single-underscore
    match = re.match(r"^(.+)_\d+$", name)
    return match.group(1) if match else name


def changespec_names_match(name_a: str, name_b: str) -> bool:
    """Check if two ChangeSpec names refer to the same logical ChangeSpec.

    Returns True if names match exactly, or if stripping the _<N> suffix
    from either name yields the other. Handles the case where a ChangeSpec
    is renamed (e.g., suffix stripped on status change to Ready).
    """
    if name_a == name_b:
        return True
    return (
        strip_reverted_suffix(name_a) == name_b
        or name_a == strip_reverted_suffix(name_b)
    )


def changespec_name_to_branch(name: str, project_basename: str) -> str:
    """Derive the git branch name from a ChangeSpec NAME.

    Strips project prefix and _<N> / __<N> suffix, converts underscores to hyphens.
    Example: changespec_name_to_branch("sase_dull_basin_1", "sase") -> "dull-basin"
    """
    name = strip_reverted_suffix(name)
    prefix = f"{project_basename}_"
    if name.startswith(prefix):
        name = name[len(prefix) :]
    return name.replace("_", "-")


def changespec_name_to_branch_with_suffix(name: str, project_basename: str) -> str:
    """Derive git branch name from a ChangeSpec name, preserving the _<N> suffix.

    Like ``changespec_name_to_branch`` but keeps the uniqueness suffix.
    Underscores in the body are converted to hyphens, but the ``_<N>``
    suffix delimiter stays as an underscore.

    Example::

        >>> changespec_name_to_branch_with_suffix("sase_dull_basin_1", "sase")
        'dull-basin_1'
    """
    prefix = f"{project_basename}_"
    if name.startswith(prefix):
        name = name[len(prefix) :]
    # Try legacy __<N> first to avoid partial matches
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
    """Check if a ChangeSpec name has a _<N> or legacy __<N> suffix.

    Args:
        name: ChangeSpec name to check

    Returns:
        True if name has a suffix, False otherwise
    """
    return bool(re.match(r"^.+__\d+$", name) or re.match(r"^.+_\d+$", name))


def get_next_suffix_number(base_name: str, existing_names: set[str]) -> int:
    """Find the lowest positive integer N such that `<base_name>_<N>` doesn't exist.

    Also checks legacy ``__<N>`` names to avoid slot collisions.

    Args:
        base_name: The base name to append suffix to
        existing_names: Set of existing names to check for conflicts

    Returns:
        The lowest available suffix number
    """
    n = 1
    while f"{base_name}_{n}" in existing_names or f"{base_name}__{n}" in existing_names:
        n += 1
    return n


def get_workspace_directory_for_changespec(changespec: "ChangeSpec") -> str | None:
    """Get the workspace directory for a ChangeSpec.

    Args:
        changespec: The ChangeSpec to get workspace directory for

    Returns:
        The workspace directory path, or None if not found
    """
    from sase.running_field import get_workspace_directory as get_workspace_dir

    try:
        return get_workspace_dir(changespec.project_basename)
    except RuntimeError:
        return None

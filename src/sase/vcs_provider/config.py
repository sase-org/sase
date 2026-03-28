"""Configuration reader for the VCS provider layer."""

import os
import re
from typing import Any

from sase.config import load_merged_config


def get_vcs_provider_config() -> dict[str, Any]:
    """Read the ``vcs_provider`` section from ``sase.yml``.

    Looks for ``~/.config/sase/sase.yml`` and returns the ``vcs_provider``
    section, or an empty dict if not found.

    Returns:
        The vcs_provider configuration dict.
    """
    try:
        data = load_merged_config()

        if not isinstance(data, dict):
            return {}

        return data.get("vcs_provider", {}) or {}
    except Exception:
        return {}


def get_pr_tags() -> dict[str, str]:
    """Read ``vcs_provider.pr_tags`` from the merged config.

    Returns:
        A dict of TAG → VALUE pairs (empty if unset).
    """
    config = get_vcs_provider_config()
    tags = config.get("pr_tags")
    if not isinstance(tags, dict):
        return {}
    return {str(k): str(v) for k, v in tags.items()}


def get_workspace_root() -> str | None:
    """Get the workspace root directory.

    Checks ``SASE_WORKSPACE_ROOT`` env var first, then falls back to
    ``vcs_provider.workspace_root`` in ``sase.yml``.

    Returns:
        The workspace root path, or None if neither is set.
    """
    env_root = os.environ.get("SASE_WORKSPACE_ROOT")
    if env_root:
        return env_root

    config = get_vcs_provider_config()
    return config.get("workspace_root") or None


_TAG_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]*=")


def strip_pr_tags(description: str) -> str:
    """Remove the trailing contiguous block of ``KEY=value`` PR tag lines.

    Strips any blank trailing lines first, then removes the contiguous run
    of lines matching ``^[A-Z][A-Z0-9_]*=`` from the end.  Any blank lines
    left at the end after removal are also stripped.

    Returns the cleaned description, or the original if no tags are found.
    """
    lines = description.split("\n")

    # Skip trailing blank lines
    last_non_blank = len(lines) - 1
    while last_non_blank >= 0 and lines[last_non_blank].strip() == "":
        last_non_blank -= 1

    # Scan upward to find contiguous tag block
    tags_start_idx = last_non_blank + 1
    for idx in range(last_non_blank, -1, -1):
        if _TAG_PATTERN.match(lines[idx].strip()):
            tags_start_idx = idx
        else:
            break

    if tags_start_idx > last_non_blank:
        return description

    # Remove tags and strip trailing blank lines
    result = "\n".join(lines[:tags_start_idx]).rstrip()
    return result

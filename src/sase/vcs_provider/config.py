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


def get_use_project_pr_prefix() -> bool:
    """Read ``vcs_provider.use_project_pr_prefix`` from the merged config.

    Returns:
        True if the project PR prefix feature is enabled.
    """
    config = get_vcs_provider_config()
    return bool(config.get("use_project_pr_prefix", False))


def strip_project_pr_prefix(description: str) -> str:
    """Remove a leading ``[...] `` prefix from the first line of *description*.

    Only strips when ``use_project_pr_prefix`` is enabled in the config.
    Returns the description unchanged otherwise.
    """
    if not get_use_project_pr_prefix():
        return description
    lines = description.split("\n", 1)
    first_line = _PREFIX_PATTERN.sub("", lines[0])
    if len(lines) == 1:
        return first_line
    return first_line + "\n" + lines[1]


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


_PREFIX_PATTERN = re.compile(r"^\[.+?\] ")


def extract_pr_tags(description: str) -> dict[str, object]:
    """Extract the trailing contiguous block of ``KEY=value`` PR tag lines.

    This is the read counterpart of :func:`strip_pr_tags`.  It scans the
    trailing contiguous run of lines matching ``^[A-Z][A-Z0-9_]*=`` (skipping
    blank lines within the block) and returns them as a dict. Keys are returned
    in canonical (unprefixed) form so legacy ``TEAM=`` and new ``SASE_TEAM=``
    parent-PR tags inherit identically without double-prefixing on child PRs.

    Returns:
        A dict mapping canonical tag names to values (empty if no tags found).
    """
    from sase.workflows.commit.runtime_tags import parse_trailing_commit_tag_values

    return dict(parse_trailing_commit_tag_values(description))


def strip_pr_tags(description: str) -> str:
    """Remove the trailing contiguous block of ``KEY=value`` PR tag lines.

    Strips any blank trailing lines first, then removes the contiguous run
    of lines matching ``^[A-Z][A-Z0-9_]*=`` from the end.  Any blank lines
    left at the end after removal are also stripped.

    Returns the cleaned description, or the original if no tags are found.
    """
    from sase.core.commit_footer_facade import parse_commit_footer

    footer = parse_commit_footer(description)
    if not footer.tags:
        return description
    return footer.body

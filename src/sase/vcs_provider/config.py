"""Configuration reader for the VCS provider layer."""

import os
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

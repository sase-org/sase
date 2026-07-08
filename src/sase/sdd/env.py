"""Environment helpers for agent-facing SDD path discovery."""

from __future__ import annotations

import logging
from collections.abc import MutableMapping
from pathlib import Path

log = logging.getLogger(__name__)

SASE_SDD_DIR_ENV = "SASE_SDD_DIR"


def set_sdd_dir_env(
    env: MutableMapping[str, str],
    *,
    workspace_dir: str,
    workspace_num: int,
) -> None:
    """Expose the effective SDD root for a workspace in *env*."""
    try:
        from sase.sdd.store import resolve_sdd_dir

        sdd_dir = resolve_sdd_dir(workspace_dir, workspace_num)
    except Exception:
        log.debug("Failed to resolve SDD dir for env", exc_info=True)
        sdd_dir = Path(workspace_dir) / ".sase" / "sdd"
    env[SASE_SDD_DIR_ENV] = str(sdd_dir)

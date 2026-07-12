"""Environment helpers for agent-facing SDD path discovery."""

from __future__ import annotations

import logging
from collections.abc import MutableMapping
from pathlib import Path

log = logging.getLogger(__name__)

SASE_SDD_DIR_ENV = "SASE_SDD_DIR"
SASE_SDD_BEADS_DIR_ENV = "SASE_SDD_BEADS_DIR"
SASE_SDD_PLANS_DIR_ENV = "SASE_SDD_PLANS_DIR"
SASE_SDD_RESEARCH_DIR_ENV = "SASE_SDD_RESEARCH_DIR"


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

    try:
        from sase.sdd.store import resolve_sdd_store

        store = resolve_sdd_store(workspace_dir, workspace_num)
        beads_dir = store.kind_root("beads")
        plans_dir = store.kind_root("plans")
        research_dir = store.kind_root("research")
    except Exception:
        log.debug("Failed to resolve SDD kind dirs for env", exc_info=True)
        beads_dir = sdd_dir / "beads"
        plans_dir = sdd_dir / "plans"
        research_dir = sdd_dir / "research"
    env[SASE_SDD_DIR_ENV] = str(sdd_dir)
    env[SASE_SDD_BEADS_DIR_ENV] = str(beads_dir)
    env[SASE_SDD_PLANS_DIR_ENV] = str(plans_dir)
    env[SASE_SDD_RESEARCH_DIR_ENV] = str(research_dir)

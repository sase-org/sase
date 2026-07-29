"""Environment helpers for agent-facing SDD path discovery."""

from __future__ import annotations

import logging
from collections.abc import MutableMapping
from pathlib import Path
import re

log = logging.getLogger(__name__)

SASE_SDD_DIR_ENV = "SASE_SDD_DIR"
SASE_SDD_BEADS_DIR_ENV = "SASE_SDD_BEADS_DIR"
SASE_SDD_PLANS_DIR_ENV = "SASE_SDD_PLANS_DIR"
SASE_SDD_RESEARCH_DIR_ENV = "SASE_SDD_RESEARCH_DIR"
_ENV_ROLE_INVALID_CHARS = re.compile(r"[^A-Za-z0-9]")


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

    configured_roles = _configured_document_roles(workspace_dir)
    role_dirs: dict[str, Path] = {}
    try:
        from sase.sdd.store import resolve_sdd_store
        from sase.sdd.store import document_sidecar_roles

        store = resolve_sdd_store(workspace_dir, workspace_num)
        beads_dir = store.kind_root("beads")
        plans_dir = store.kind_root("plans")
        roles = document_sidecar_roles(
            (*store.split_sidecar_roles(), *configured_roles),
            include_plans=True,
        )
        for role in roles:
            try:
                role_dirs[role] = store.kind_root(role)
            except ValueError:
                role_dirs[role] = sdd_dir / role
    except Exception:
        log.debug("Failed to resolve SDD kind dirs for env", exc_info=True)
        beads_dir = sdd_dir / "beads"
        plans_dir = sdd_dir / "plans"
        role_dirs = {role: sdd_dir / role for role in configured_roles}
    role_dirs["plans"] = plans_dir
    env[SASE_SDD_DIR_ENV] = str(sdd_dir)
    env[SASE_SDD_BEADS_DIR_ENV] = str(beads_dir)
    for role, role_dir in role_dirs.items():
        env[_document_role_env_name(role)] = str(role_dir)


def _configured_document_roles(workspace_dir: str) -> tuple[str, ...]:
    try:
        from sase._linked_repo_config import (
            configured_sidecar_roles,
            resolution_config,
        )
        from sase.sdd.store import document_sidecar_roles

        config = resolution_config(workspace_dir, None)
        roles = configured_sidecar_roles(
            config,
            primary_workspace_dir=workspace_dir,
        )
        return document_sidecar_roles(roles, include_plans=True)
    except (OSError, RuntimeError, ValueError):
        return ()


def _document_role_env_name(role: str) -> str:
    token = _ENV_ROLE_INVALID_CHARS.sub("_", role).upper()
    return f"SASE_SDD_{token}_DIR"

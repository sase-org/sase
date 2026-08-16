"""Dependency resolution predicates for the run agent wait barrier.

The ``wait_checks`` lumberjack chop normally resolves dependencies and writes
``ready.json``. These helpers let the runner resolve the very same dependency
set directly, both as an up-front fast path and as a periodic fallback so a chop
outage cannot strand a waiting agent forever.
"""

import json
import os
from collections.abc import Iterable
from pathlib import Path

from sase.axe.run_agent_wait_markers import read_json_dict
from sase.core.wait_dependency_resolution import (
    build_wait_dependency_index,
    dependency_resolution_status,
)


def mark_bead_wait_sync_hint(project_name: str | None) -> None:
    """Best-effort hint that this project's beads sidecar should sync soon.

    The runner no longer integrates the canonical primary bead sidecar
    directly; it marks the same durable sync hint a workspace-sidecar
    publication would, so the generic ``sidecar_auto_sync`` chop converges
    the beads role on its next tick instead of the project waiting out that
    chop's five-minute backstop.
    """
    if not project_name:
        return
    try:
        from sase._sidecar_sync_hints import mark_sidecar_sync_hint
        from sase.bead.sync import bead_refresh_mode
        from sase.sdd._store_types import BEADS_SIDECAR_ROLE

        if bead_refresh_mode() == "off":
            return
        mark_sidecar_sync_hint(project_name, BEADS_SIDECAR_ROLE)
    except Exception:  # noqa: BLE001 - runner waits must survive hint failures.
        pass


def initial_dependencies_resolved(
    wait_names: Iterable[object],
    wait_identity_deps: Iterable[object],
    *,
    wait_beads: Iterable[object] = (),
    resolved_deps: Iterable[object] = (),
    project_name: str | None,
    artifacts_dir: str,
) -> bool:
    """Resolve a dependency set directly, without consulting ``ready.json``."""
    if not project_name:
        return False

    try:
        dependency_index = build_wait_dependency_index(project_name)
    except Exception:
        return False
    wait_bead_items = tuple(wait_beads)
    closed_bead_ids = None
    if wait_bead_items:
        from sase.bead.store_locator import closed_bead_ids_for_project

        closed_bead_ids = closed_bead_ids_for_project(project_name)

    status = dependency_resolution_status(
        dependency_index,
        wait_names,
        wait_identity_deps,
        resolved_deps,
        wait_beads=wait_bead_items,
        closed_bead_ids=closed_bead_ids,
        self_artifact_dir=artifacts_dir,
    )
    return status.resolved


def read_ready_result(ready_path: str) -> bool:
    """Return whether a ready marker resolves the wait.

    Cancellation markers written by older SASE versions are stale state. Remove
    them and keep waiting for an actual successful resolution marker.
    """
    try:
        with open(ready_path, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return True
    if not isinstance(data, dict) or not data.get("cancelled"):
        return True
    try:
        os.unlink(ready_path)
    except OSError:
        pass
    return False


def waiting_marker_dependencies_resolved(
    waiting_path: Path,
    *,
    project_name: str | None,
    artifacts_dir: str,
) -> bool:
    """Re-resolve the dependencies currently recorded in ``waiting.json``."""
    waiting_data = read_json_dict(waiting_path)
    if waiting_data is None:
        return False

    wait_names = waiting_data.get("waiting_for", [])
    wait_identity_deps = waiting_data.get("wait_for_artifacts", [])
    wait_beads = waiting_data.get("wait_for_beads", [])
    resolved_deps = waiting_data.get("resolved_deps", [])
    if not isinstance(wait_names, list):
        return False
    if not isinstance(wait_identity_deps, list):
        wait_identity_deps = []
    if not isinstance(wait_beads, list):
        wait_beads = []
    if not isinstance(resolved_deps, list):
        resolved_deps = []
    if not wait_names and not wait_identity_deps and not wait_beads:
        return False

    return initial_dependencies_resolved(
        wait_names,
        wait_identity_deps,
        wait_beads=wait_beads,
        resolved_deps=resolved_deps,
        project_name=project_name,
        artifacts_dir=artifacts_dir,
    )

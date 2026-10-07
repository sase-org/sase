"""Dependency resolution predicates for the run agent wait barrier.

The ``wait_checks`` lumberjack chop normally resolves dependencies and writes
``ready.json``. These helpers let the runner resolve the very same dependency
set directly, both as an up-front fast path and as a periodic fallback so a chop
outage cannot strand a waiting agent forever.
"""

import json
import os
import time
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from sase.axe.run_agent_wait_markers import read_json_dict
from sase.bead.wait_status import closed_bead_ids_for_waits
from sase.core.wait_dependency_resolution import (
    WaitDependencyIndex,
    WaitReleaseDecision,
    apply_wait_epic_follow_patch,
    build_wait_dependency_index,
    resolve_wait_release,
)
from sase.core.agent_tribe_evidence import stored_tribe_names_for_resolution
from sase.core.wait_dependency_resolution._types import WaitDependencyStatus


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


def _parked_release_decision(
    status: WaitDependencyStatus,
    *,
    confirmation_failed: bool = False,
) -> WaitReleaseDecision:
    return WaitReleaseDecision(
        status,
        (),
        None,
        False,
        confirmation_failed,
    )


def resolve_initial_wait_release(
    wait_names: Iterable[object],
    wait_identity_deps: Iterable[object],
    *,
    wait_fork_sources: Iterable[object] = (),
    wait_beads: Iterable[object] = (),
    wait_hoods: Iterable[object] = (),
    resolved_deps: Iterable[object] = (),
    wait_for_epics_of: Iterable[object] = (),
    wait_epic_follows: Iterable[object] = (),
    project_name: str | None,
    artifacts_dir: str,
) -> WaitReleaseDecision:
    """Resolve a dependency set through the shared epic-follow release.

    Builds the synthetic marker from the launch arguments and decides one
    release pass with the same ``build_index`` closure as the fresh index.
    Callers that need the promotion patch read it off the decision; the
    ``initial_dependencies_resolved`` bool wrapper reads ``.releasable``.
    """
    marker: dict[str, Any] = {
        "waiting_for": list(wait_names),
        "wait_for_artifacts": list(wait_identity_deps),
        "wait_for_fork_sources": list(wait_fork_sources),
        "wait_for_beads": list(wait_beads),
        "wait_for_hoods": list(wait_hoods),
        "resolved_deps": list(resolved_deps),
        "wait_for_epics_of": list(wait_for_epics_of),
        "wait_epic_follows": list(wait_epic_follows),
    }
    return _resolve_marker_release(
        marker,
        project_name=project_name,
        artifacts_dir=artifacts_dir,
    )


def _resolve_marker_release(
    marker: dict[str, Any],
    *,
    project_name: str | None,
    artifacts_dir: str,
) -> WaitReleaseDecision:
    """Decide one release pass for a marker with a freshly built index."""
    if not project_name:
        return _parked_release_decision(WaitDependencyStatus("waiting", ("<unknown>",)))

    try:
        global_stored_tribes = stored_tribe_names_for_resolution()

        def build_index() -> WaitDependencyIndex:
            index = build_wait_dependency_index(project_name)
            index.global_stored_tribes = global_stored_tribes
            return index

        dependency_index = build_index()
    except Exception as exc:
        print(
            f"Wait dependency check failed (index): {type(exc).__name__}: "
            f"{exc}; staying parked"
        )
        return _parked_release_decision(WaitDependencyStatus("waiting", ("<unknown>",)))
    wait_bead_items = tuple(marker.get("wait_for_beads", []))
    closed_bead_ids = None
    if wait_bead_items:
        try:
            closed_bead_ids = closed_bead_ids_for_waits(
                project_name,
                wait_bead_items,
                sync_hint=mark_bead_wait_sync_hint,
            ).closed_ids
        except Exception as exc:
            print(
                f"Wait dependency check failed (index): {type(exc).__name__}: "
                f"{exc}; staying parked"
            )
            return _parked_release_decision(
                WaitDependencyStatus("waiting", tuple(wait_bead_items))
            )
    try:
        decision = resolve_wait_release(
            dependency_index,
            marker,
            waiter_dir=artifacts_dir,
            closed_bead_ids=closed_bead_ids,
            now=time.time(),
            fresh_index=build_index,
        )
    except Exception as exc:
        print(
            f"Wait dependency check failed (confirmation): {type(exc).__name__}: "
            f"{exc}; staying parked"
        )
        return _parked_release_decision(
            WaitDependencyStatus("waiting", tuple(marker.get("waiting_for", [])))
        )
    if decision.confirmation_failed:
        print("Wait dependency check failed (confirmation): staying parked")
    return decision


def initial_dependencies_resolved(
    wait_names: Iterable[object],
    wait_identity_deps: Iterable[object],
    *,
    wait_fork_sources: Iterable[object] = (),
    wait_beads: Iterable[object] = (),
    wait_hoods: Iterable[object] = (),
    resolved_deps: Iterable[object] = (),
    wait_for_epics_of: Iterable[object] = (),
    project_name: str | None,
    artifacts_dir: str,
) -> bool:
    """Resolve a dependency set directly, without consulting ``ready.json``."""
    return resolve_initial_wait_release(
        wait_names,
        wait_identity_deps,
        wait_fork_sources=wait_fork_sources,
        wait_beads=wait_beads,
        wait_hoods=wait_hoods,
        resolved_deps=resolved_deps,
        wait_for_epics_of=wait_for_epics_of,
        project_name=project_name,
        artifacts_dir=artifacts_dir,
    ).releasable


def read_ready_result(ready_path: str) -> bool:
    """Return whether a ready marker resolves the wait.

    A torn or otherwise unreadable marker is treated as not ready; the
    runner retries on its next poll (and the periodic fallback, which
    never reads ``ready.json``, still bounds the wait). Cancellation
    markers written by older SASE versions are stale state. Remove them
    and keep waiting for an actual successful resolution marker.
    """
    try:
        with open(ready_path, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return False
    if not isinstance(data, dict):
        return False
    if not data.get("cancelled"):
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
    wait_fork_sources = waiting_data.get("wait_for_fork_sources", [])
    wait_beads = waiting_data.get("wait_for_beads", [])
    wait_hoods = waiting_data.get("wait_for_hoods", [])
    resolved_deps = waiting_data.get("resolved_deps", [])
    if not isinstance(wait_names, list):
        return False
    if not isinstance(wait_identity_deps, list):
        wait_identity_deps = []
    if not isinstance(wait_fork_sources, list):
        wait_fork_sources = []
    if not isinstance(wait_beads, list):
        wait_beads = []
    if not isinstance(wait_hoods, list):
        wait_hoods = []
    if not isinstance(resolved_deps, list):
        resolved_deps = []
    if not (
        wait_names
        or wait_identity_deps
        or wait_fork_sources
        or wait_beads
        or wait_hoods
    ):
        return False

    decision = _resolve_marker_release(
        waiting_data,
        project_name=project_name,
        artifacts_dir=artifacts_dir,
    )
    if decision.patch is not None:
        if not apply_wait_epic_follow_patch(artifacts_dir, decision.patch):
            return False
        return False
    return decision.releasable

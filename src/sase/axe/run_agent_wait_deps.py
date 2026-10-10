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
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sase.axe.run_agent_wait_markers import read_json_dict
from sase.bead.wait_status import closed_bead_ids_for_waits
from sase.core.wait_dependency_resolution import (
    WaitDependencyIndex,
    WaitReleaseDecision,
    apply_wait_epic_follow_patch,
    build_wait_dependency_index,
    latest_member_finished_at,
    resolve_wait_release,
)
from sase.core.agent_tribe_evidence import stored_tribe_names_for_resolution
from sase.core.wait_dependency_resolution._types import WaitDependencyStatus


@dataclass(frozen=True)
class _DependencyResolution:
    """Runner-side dependency resolution outcome plus telemetry.

    ``resolved`` keeps the old boolean contract: the instance is truthy
    exactly when the wait is released, so existing ``if ...`` call sites and
    ``patch(..., return_value=True)`` stubs keep working (stubbed plain
    bools simply carry no telemetry; readers must use ``getattr`` with a
    default). ``satisfied_at`` is the epoch instant the last relevant
    dependency member finished, or ``None`` when unknown or when bead
    dependencies are present.
    """

    resolved: bool = False
    satisfied_at: float | None = None

    def __bool__(self) -> bool:
        return self.resolved


@dataclass(frozen=True)
class _ReadyResult:
    """Runner-side ``ready.json`` read outcome plus telemetry.

    Truthy exactly when the marker releases the wait. ``released_by`` and
    ``dependencies_satisfied_at`` come straight from the marker payload;
    ``unwait`` marks a manual (TUI run-now) release.
    """

    resolved: bool = False
    released_by: str | None = None
    unwait: bool = False
    dependencies_satisfied_at: float | None = None

    def __bool__(self) -> bool:
        return self.resolved


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
    Callers read ``.releasable`` and, when present, the promotion patch.
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


def _forward_identity_deps(
    wait_identity_deps: Iterable[object],
) -> list[object]:
    """Remap wiped identity deps to their auto-restart replacement.

    Identity- (or ref-) based waits pin the old artifacts dir, which the
    healer's forced-reuse wipe removes. When the ledger names a launched
    replacement for a dir that no longer exists, resolve against the
    replacement instead so the waiter follows the new row.
    """
    try:
        from sase.agent.auto_restart.forward import find_replacement_artifacts_dir
    except Exception:
        return list(wait_identity_deps)
    mapped: list[object] = []
    for dependency in wait_identity_deps:
        if isinstance(dependency, dict):
            old = dependency.get("artifact_dir")
            if isinstance(old, str) and old and not os.path.exists(old):
                try:
                    replacement = find_replacement_artifacts_dir(old)
                except Exception:
                    replacement = None
                if (
                    isinstance(replacement, str)
                    and replacement
                    and os.path.exists(replacement)
                ):
                    remapped = dict(dependency)
                    remapped["artifact_dir"] = replacement
                    mapped.append(remapped)
                    continue
        mapped.append(dependency)
    return mapped


def _resolve_marker_release(
    marker: dict[str, Any],
    *,
    project_name: str | None,
    artifacts_dir: str,
) -> WaitReleaseDecision:
    """Decide one release pass for a marker with a freshly built index."""
    try:
        identity_deps = marker.get("wait_for_artifacts", [])
        if isinstance(identity_deps, list) and identity_deps:
            marker = {
                **marker,
                "wait_for_artifacts": _forward_identity_deps(identity_deps),
            }
    except Exception:
        pass
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


def _release_satisfied_at(
    wait_names: Iterable[object],
    wait_identity_deps: Iterable[object],
    *,
    wait_fork_sources: Iterable[object] = (),
    wait_beads: Iterable[object] = (),
    wait_hoods: Iterable[object] = (),
    resolved_deps: Iterable[object] = (),
    project_name: str | None,
    artifacts_dir: str,
) -> float | None:
    """Best-effort instant the last dependency member finished.

    Bead-close times are not observable, so bead waits report ``None``.
    Telemetry must never un-release a wait the decision already released,
    so any failure here yields ``None`` instead of raising.
    """
    if project_name is None:
        return None
    if tuple(wait_beads):
        return None
    try:
        index = build_wait_dependency_index(project_name)
        index.global_stored_tribes = stored_tribe_names_for_resolution()
        return latest_member_finished_at(
            index.dependency_member_dirs(
                tuple(wait_names),
                tuple(wait_identity_deps),
                tuple(resolved_deps),
                wait_fork_sources=tuple(wait_fork_sources),
                wait_hoods=tuple(wait_hoods),
                self_artifact_dir=artifacts_dir,
            )
        )
    except Exception:  # noqa: BLE001 - telemetry must never un-release.
        return None


def _ready_float(value: object) -> float | None:
    """Return a numeric epoch from a marker payload value, else None."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def read_ready_result(ready_path: str) -> _ReadyResult:
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
        return _ReadyResult(False)
    if not isinstance(data, dict):
        return _ReadyResult(False)
    if not data.get("cancelled"):
        released_by = data.get("released_by")
        return _ReadyResult(
            True,
            released_by if isinstance(released_by, str) else None,
            bool(data.get("unwait", False)),
            _ready_float(data.get("dependencies_satisfied_at")),
        )
    try:
        os.unlink(ready_path)
    except OSError:
        pass
    return _ReadyResult(False)


def waiting_marker_dependencies_resolved(
    waiting_path: Path,
    *,
    project_name: str | None,
    artifacts_dir: str,
) -> _DependencyResolution:
    """Re-resolve the dependencies currently recorded in ``waiting.json``."""
    waiting_data = read_json_dict(waiting_path)
    if waiting_data is None:
        return _DependencyResolution(False)

    wait_names = waiting_data.get("waiting_for", [])
    wait_identity_deps = waiting_data.get("wait_for_artifacts", [])
    wait_fork_sources = waiting_data.get("wait_for_fork_sources", [])
    wait_beads = waiting_data.get("wait_for_beads", [])
    wait_hoods = waiting_data.get("wait_for_hoods", [])
    resolved_deps = waiting_data.get("resolved_deps", [])
    if not isinstance(wait_names, list):
        return _DependencyResolution(False)
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
        return _DependencyResolution(False)

    decision = _resolve_marker_release(
        waiting_data,
        project_name=project_name,
        artifacts_dir=artifacts_dir,
    )
    if decision.patch is not None:
        if not apply_wait_epic_follow_patch(artifacts_dir, decision.patch):
            return _DependencyResolution(False)
        return _DependencyResolution(False)
    if not decision.releasable:
        return _DependencyResolution(False)
    return _DependencyResolution(
        True,
        _release_satisfied_at(
            wait_names,
            wait_identity_deps,
            wait_fork_sources=wait_fork_sources,
            wait_beads=wait_beads,
            wait_hoods=wait_hoods,
            resolved_deps=resolved_deps,
            project_name=project_name,
            artifacts_dir=artifacts_dir,
        ),
    )

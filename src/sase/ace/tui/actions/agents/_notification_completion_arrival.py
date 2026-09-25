"""Same-tick arrival status overlay for completed agents.

A finished agent's terminal status is on disk (``done.json``) at toast time,
but the Agents-tab roster only learns it through the serialized artifact-delta
lane. This module resolves the notified node's terminal status authoritatively
on the notification-poll worker hop and installs it as a short-lived in-memory
overlay so the unread marker appears on the same tick as the toast. The exact
delta still runs and remains the authoritative apply.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class CompletionArrivalPrep:
    """Worker-side result for one notification-poll tick."""

    overlays: tuple[tuple[Any, str], ...] = ()
    artifact_dirs: tuple[Path, ...] = ()


@dataclass(slots=True)
class _ArrivalOverlay:
    """Live overlay for one identity until the authoritative load lands."""

    status: str
    survives_stale_apply: bool


def prepare_completion_arrival_overlays(
    app: Any,
    notifications: Any,
) -> CompletionArrivalPrep:
    """Probe exact terminal status for newly completed nodes (worker thread).

    Reads the roster plus ``agent_artifact_dir`` and runs one batched
    read-only ``load_artifact_delta_agents`` scan. Never touches the event
    loop. Returns an empty result without touching disk when nothing
    mismatches (the common case).
    """
    from ...util.trace import tui_trace
    from ...models.agent_status import is_unread_completed_status
    from ...models.agent_nodes import agent_node_projection_index
    from ._notification_agent_targeting import (
        agent_artifact_dir,
        loaded_real_agent_roster,
    )
    from ._notification_matching import (
        is_active_agent_completion_notification,
        normalized_suffix,
        notification_raw_suffix,
    )

    with tui_trace("notification.completion_arrival") as extra:
        result = _prepare_overlays_inner(
            app,
            notifications,
            agent_artifact_dir=agent_artifact_dir,
            loaded_real_agent_roster=loaded_real_agent_roster,
            agent_node_projection_index=agent_node_projection_index,
            is_active_agent_completion_notification=(
                is_active_agent_completion_notification
            ),
            normalized_suffix=normalized_suffix,
            notification_raw_suffix=notification_raw_suffix,
            is_unread_completed_status=is_unread_completed_status,
        )
        extra["candidates"] = result[1]
        extra["overlays"] = len(result[0].overlays)
        extra["dirs"] = len(result[0].artifact_dirs)
        return result[0]


def _prepare_overlays_inner(
    app: Any,
    notifications: Any,
    *,
    agent_artifact_dir: Any,
    loaded_real_agent_roster: Any,
    agent_node_projection_index: Any,
    is_active_agent_completion_notification: Any,
    normalized_suffix: Any,
    notification_raw_suffix: Any,
    is_unread_completed_status: Any,
) -> tuple[CompletionArrivalPrep, int]:
    notification_list = list(notifications or [])
    if not notification_list:
        return CompletionArrivalPrep(), 0

    roster = loaded_real_agent_roster(app)
    if not roster:
        return CompletionArrivalPrep(), 0

    # Exact (cl_name, raw_suffix) keys for active completions. Skip
    # cl_name-only rows: the runner always stamps raw_suffix.
    wanted: dict[tuple[str, str], list[Any]] = {}
    for notification in notification_list:
        try:
            if not is_active_agent_completion_notification(notification):
                continue
        except Exception:
            continue
        action_data = getattr(notification, "action_data", None) or {}
        cl_name = action_data.get("cl_name")
        if not cl_name:
            continue
        try:
            raw_suffix = notification_raw_suffix(notification)
        except Exception:
            raw_suffix = None
        if not raw_suffix:
            continue
        wanted.setdefault((str(cl_name), str(raw_suffix)), []).append(notification)
    if not wanted:
        return CompletionArrivalPrep(), 0

    try:
        node_index = agent_node_projection_index(roster)
    except Exception:
        log.debug("completion arrival projection failed", exc_info=True)
        return CompletionArrivalPrep(), 0

    roster_by_key: dict[tuple[str, str], list[Any]] = {}
    for row in roster:
        try:
            raw = normalized_suffix(getattr(row, "raw_suffix", None))
        except Exception:
            raw = None
        if not raw:
            continue
        cl_name = getattr(row, "cl_name", None)
        if not cl_name:
            continue
        roster_by_key.setdefault((str(cl_name), str(raw)), []).append(row)

    # Resolve each wanted key to loaded rows, then to owning nodes.
    # Local rows only: skip rows with no local artifact dir.
    candidates: dict[Any, dict[str, Any]] = {}
    for key in wanted:
        rows = roster_by_key.get(key, [])
        for row in rows:
            try:
                if agent_artifact_dir(row) is None:
                    continue
            except Exception:
                continue
            try:
                projection = node_index.owner_for_identity(row.identity)
            except Exception:
                continue
            if projection is None:
                continue
            node = projection.node
            try:
                if is_unread_completed_status(node.status):
                    continue
            except Exception:
                continue
            entry = candidates.get(node.identity)
            if entry is None:
                candidates[node.identity] = {
                    "node": node,
                    "row": row,
                    "projection": projection,
                }
    if not candidates:
        return CompletionArrivalPrep(), 0

    # Collect the node plus every loaded session member (excluding
    # workflow-step children) so normalization mirrors the session root the
    # same way a full load would.
    dirs: list[Path] = []
    seen_dirs: set[str] = set()

    def _add_dir(path: Path | None) -> None:
        if path is None:
            return
        key = str(path)
        if key in seen_dirs:
            return
        seen_dirs.add(key)
        dirs.append(path)

    for entry in candidates.values():
        node = entry["node"]
        projection = entry["projection"]
        try:
            _add_dir(agent_artifact_dir(node))
        except Exception:
            continue
        for owned in getattr(projection, "owned_rows", ()):
            try:
                if getattr(owned, "is_workflow_step_child", False):
                    continue
                _add_dir(agent_artifact_dir(owned))
            except Exception:
                continue
    if not dirs:
        return CompletionArrivalPrep(), 0

    try:
        from ...models.agent_loader import load_artifact_delta_agents
    except Exception:
        log.debug("completion arrival loader unavailable", exc_info=True)
        return CompletionArrivalPrep(), len(candidates)
    try:
        scanned, _state = load_artifact_delta_agents(
            dirs,
            update_index=False,
            patch_snapshot=[],
        )
    except Exception:
        log.debug("completion arrival scan failed", exc_info=True)
        return CompletionArrivalPrep(), len(candidates)

    scanned_by_identity: dict[Any, Any] = {}
    scanned_by_key: dict[tuple[str, str], Any] = {}
    for agent in scanned:
        try:
            scanned_by_identity[agent.identity] = agent
        except Exception:
            continue
        try:
            raw = normalized_suffix(getattr(agent, "raw_suffix", None))
        except Exception:
            raw = None
        cl_name = getattr(agent, "cl_name", None)
        if raw and cl_name:
            scanned_by_key.setdefault((str(cl_name), str(raw)), agent)

    overlays: list[tuple[Any, str]] = []
    seen_identities: set[Any] = set()

    def _emit(loaded_identity: Any, loaded_row: Any) -> None:
        if loaded_identity in seen_identities:
            return
        scanned_row = scanned_by_identity.get(loaded_identity)
        if scanned_row is None:
            try:
                raw = normalized_suffix(getattr(loaded_row, "raw_suffix", None))
            except Exception:
                raw = None
            cl_name = getattr(loaded_row, "cl_name", None)
            if raw and cl_name:
                scanned_row = scanned_by_key.get((str(cl_name), str(raw)))
        if scanned_row is None:
            return
        try:
            status = scanned_row.status
            if not is_unread_completed_status(status):
                return
        except Exception:
            return
        seen_identities.add(loaded_identity)
        overlays.append((loaded_identity, str(status)))

    for entry in candidates.values():
        _emit(entry["node"].identity, entry["node"])
        _emit(entry["row"].identity, entry["row"])

    return (
        CompletionArrivalPrep(
            overlays=tuple(overlays),
            artifact_dirs=tuple(dirs),
        ),
        len(candidates),
    )


def install_completion_arrival_overlays(
    app: Any,
    prep: CompletionArrivalPrep,
) -> set[Any]:
    """Install worker-prepared overlays onto live rows (event-loop thread).

    Re-captures the live roster because the worker await may have interleaved
    with an apply. Sets ``row.status`` in place, records the overlay for the
    load-apply seam, and schedules the paired authoritative exact delta.
    Returns the identities whose status changed for selective repaint.
    """
    from ...models.agent_status import is_unread_completed_status
    from ._notification_agent_targeting import loaded_real_agent_roster

    if prep is None or not prep.overlays:
        return set()
    roster = loaded_real_agent_roster(app)
    roster_by_identity = {agent.identity: agent for agent in roster}
    overlays = getattr(app, "_agents_arrival_status_overlays", None)
    if overlays is None:
        overlays = {}
        app._agents_arrival_status_overlays = overlays
    changed: set[Any] = set()
    survives = bool(getattr(app, "_agents_loading", False))
    for identity, status in prep.overlays:
        live = roster_by_identity.get(identity)
        if live is None:
            continue
        try:
            if is_unread_completed_status(live.status):
                continue
        except Exception:
            continue
        try:
            live.status = status
        except Exception:
            continue
        overlays[identity] = _ArrivalOverlay(
            status=status,
            survives_stale_apply=survives,
        )
        changed.add(identity)
    if prep.artifact_dirs:
        schedule_delta = getattr(app, "_schedule_agent_artifact_delta_refresh", None)
        if callable(schedule_delta):
            try:
                schedule_delta(list(prep.artifact_dirs), source="notification")
            except Exception:
                log.debug("completion arrival delta schedule failed", exc_info=True)
    return changed


def reconcile_arrival_status_overlays(app: Any) -> None:
    """Reconcile overlays against a newly installed roster (UI-thread seam).

    Must run after the new roster is installed and before
    ``_finalize_agent_list`` runs ``_sync_unread_completed_agents``. A stale
    in-flight load (``survives_stale_apply``) re-applies the overlay once so
    the marker cannot flicker; the next authoritative load drops it.
    """
    from ...models.agent_status import is_unread_completed_status
    from ._notification_agent_targeting import loaded_real_agent_roster

    overlays = getattr(app, "_agents_arrival_status_overlays", None)
    if not overlays:
        return
    roster = loaded_real_agent_roster(app)
    roster_by_identity = {agent.identity: agent for agent in roster}
    for identity in list(overlays.keys()):
        overlay = overlays.get(identity)
        if overlay is None:
            continue
        live = roster_by_identity.get(identity)
        if live is None:
            overlays.pop(identity, None)
            continue
        if getattr(overlay, "survives_stale_apply", False):
            try:
                if not is_unread_completed_status(live.status):
                    live.status = overlay.status
            except Exception:
                pass
            try:
                overlay.survives_stale_apply = False
            except Exception:
                pass
        else:
            overlays.pop(identity, None)


__all__ = [
    "CompletionArrivalPrep",
    "install_completion_arrival_overlays",
    "prepare_completion_arrival_overlays",
    "reconcile_arrival_status_overlays",
]

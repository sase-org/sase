"""Shared waiting-marker walk plus tri-state runner liveness.

``wait_checks`` and ``sidecar_auto_sync`` both need the same answer: which
artifact directories hold a pending (``waiting.json`` present, ``ready.json``
absent) waiter, and is that waiter's runner provably dead. The walk is a
cheap filesystem pass over every project's ``ace-run`` directories; runner
liveness is tri-state so unprovable cases fail open to live.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from sase.agent.names import is_process_alive
from sase.core.agent_artifact_paths import iter_agent_artifact_dirs
from sase.scripts._chop_wait_checks_common import WaitingMarker

WaiterLiveness = Literal["alive", "dead", "unknown"]


@dataclass
class _WaitMarkerScan:
    """One shared walk over every project's ``ace-run`` artifact dirs."""

    projects: int = 0
    artifacts: int = 0
    waiting: int = 0
    already_ready: int = 0
    pending: list[WaitingMarker] = field(default_factory=list)
    already_ready_markers: list[WaitingMarker] = field(default_factory=list)
    walked_dirs: set[Path] = field(default_factory=set)


def scan_waiting_markers(projects_dir: Path) -> _WaitMarkerScan:
    """Walk ``ace-run`` dirs and collect waiting markers without meta reads.

    Returns the project/artifact/waiting counts, the pending markers
    (``waiting.json`` present, ``ready.json`` absent), the already-released
    markers, and every walked artifact directory. Reads no ``agent_meta.json``
    file: callers load pending-waiter metadata into their own cache and
    classify it with :func:`waiting_runner_liveness`.
    """

    scan = _WaitMarkerScan()
    for project_dir in projects_dir.iterdir():
        if not project_dir.is_dir():
            continue
        scan.projects += 1
        for artifact_dir in iter_agent_artifact_dirs(
            project_dir.name,
            "ace-run",
            projects_root=projects_dir,
        ):
            scan.artifacts += 1
            scan.walked_dirs.add(artifact_dir)
            waiting_path = artifact_dir / "waiting.json"
            if not waiting_path.exists():
                continue
            scan.waiting += 1
            marker = WaitingMarker(
                project_name=project_dir.name,
                ready_path=artifact_dir / "ready.json",
                waiting_path=waiting_path,
            )
            if marker.ready_path.exists():
                scan.already_ready += 1
                scan.already_ready_markers.append(marker)
            else:
                scan.pending.append(marker)
    return scan


def _recorded_pid(meta: dict[str, Any], artifact_dir: Path) -> int | None:
    """Return the integer pid recorded for a waiter, or ``None`` when unknown."""

    pid = meta.get("pid")
    if isinstance(pid, int) and not isinstance(pid, bool):
        return pid
    try:
        with open(artifact_dir / "running.json", encoding="utf-8") as stream:
            running = json.load(stream)
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(running, dict):
        return None
    fallback = running.get("pid")
    if isinstance(fallback, int) and not isinstance(fallback, bool):
        return fallback
    return None


def waiting_runner_liveness(
    artifact_dir: Path,
    meta: dict[str, Any] | None,
) -> WaiterLiveness:
    """Classify a waiter's runner as ``"alive"``, ``"dead"``, or ``"unknown"``.

    ``"unknown"`` covers a missing or unreadable ``agent_meta.json`` and a
    marker with no integer pid in either ``agent_meta.json`` or
    ``running.json``; callers treat ``"unknown"`` as live. ``"dead"`` needs
    proof: an explicit ``stopped_at`` stamp or a recorded pid that
    :func:`sase.agent.names.is_process_alive` (which guards PID reuse with
    ``process_identity`` and boot time) reports as gone. Any unexpected
    failure fails open to ``"unknown"``.
    """

    try:
        if not isinstance(meta, dict):
            return "unknown"
        if meta.get("stopped_at"):
            return "dead"
        if _recorded_pid(meta, artifact_dir) is None:
            return "unknown"
        return "alive" if is_process_alive(meta, artifact_dir) else "dead"
    except Exception:  # noqa: BLE001 - uncertain liveness must fail open.
        return "unknown"


__all__ = [
    "WaiterLiveness",
    "scan_waiting_markers",
    "waiting_runner_liveness",
]

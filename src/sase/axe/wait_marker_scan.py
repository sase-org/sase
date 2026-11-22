"""Shared waiting-marker scan plus tri-state runner liveness.

``wait_checks`` and ``sidecar_auto_sync`` both need the same answer: which
artifact directories hold a pending (``waiting.json`` present, ``ready.json``
absent) waiter, and is that waiter's runner provably dead. Runner liveness is
tri-state so unprovable cases fail open to live.

The scan has two sources. The filesystem walk lists every project's
``ace-run`` directories and checks each one for ``waiting.json``. The index
source lists the same directories from the persistent agent artifact index's
scalar columns and reads ``waiting.json`` only where the index records one,
so a tick no longer pays one ``exists`` per artifact directory. Both sources
read every marker they report from disk, so the index only decides which
directories are looked at, never what a marker says. A missing or failing
index falls back to the walk.

``wait_checks`` prefers the index but still walks at least every
:data:`WAIT_SCAN_FULL_WALK_INTERVAL_SECONDS`, which matches its trigger's
``max_quiet`` backstop, so a ``waiting.json`` the index never heard about
waits at most one backstop period. ``SASE_CHOP_SCAN_FULL_WALK=1`` walks on
every tick.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from sase.agent.names import is_process_alive
from sase.core.agent_artifact_paths import iter_agent_artifact_dirs
from sase.core.paths import sase_subdir
from sase.scripts._chop_wait_checks_common import WaitingMarker

if TYPE_CHECKING:
    from sase.core.agent_artifact_index_recent import AceRunIndexListing

WaiterLiveness = Literal["alive", "dead", "unknown"]
WaitScanSource = Literal["index", "walk"]

#: Longest gap between ``wait_checks`` filesystem walks while the index
#: source is healthy. Matches the job trigger's ``max_quiet: "120s"``.
WAIT_SCAN_FULL_WALK_INTERVAL_SECONDS = 120.0


@dataclass
class _WaitMarkerScan:
    """One shared scan over every project's ``ace-run`` artifact dirs."""

    projects: int = 0
    artifacts: int = 0
    waiting: int = 0
    already_ready: int = 0
    pending: list[WaitingMarker] = field(default_factory=list)
    already_ready_markers: list[WaitingMarker] = field(default_factory=list)
    dirs_by_project: dict[str, list[Path]] = field(default_factory=dict)
    source: WaitScanSource = "walk"
    #: Why an index-preferring scan walked instead (``None`` otherwise).
    fallback_reason: str | None = None

    @property
    def walked_dirs(self) -> set[Path]:
        """Every listed artifact dir, built on demand because hashing is not free."""
        return {path for dirs in self.dirs_by_project.values() for path in dirs}


def scan_waiting_markers(
    projects_dir: Path,
    *,
    prefer_index: bool = False,
    index_path: Path | None = None,
) -> _WaitMarkerScan:
    """Collect waiting markers without meta reads.

    Returns the project/artifact/waiting counts, the pending markers
    (``waiting.json`` present, ``ready.json`` absent), the already-released
    markers, and every listed artifact directory grouped by project in
    listing order for the resolving view. Reads no ``agent_meta.json``
    file: callers load pending-waiter metadata into their own cache and
    classify it with :func:`waiting_runner_liveness`.

    With *prefer_index* the listing comes from the agent artifact index at
    *index_path* (default: this SASE home's index); a missing, unreadable,
    or failing index walks the filesystem instead and records why in
    ``fallback_reason``.
    """

    if prefer_index:
        listing = _load_index_listing(projects_dir, index_path)
        if listing is not None:
            return _scan_from_index(projects_dir, listing)
        scan = _walk_waiting_markers(projects_dir)
        scan.fallback_reason = "index_unavailable"
        return scan
    return _walk_waiting_markers(projects_dir)


def _walk_waiting_markers(projects_dir: Path) -> _WaitMarkerScan:
    scan = _WaitMarkerScan(source="walk")
    for project_dir in projects_dir.iterdir():
        if not project_dir.is_dir():
            continue
        scan.projects += 1
        project_dirs = scan.dirs_by_project.setdefault(project_dir.name, [])
        for artifact_dir in iter_agent_artifact_dirs(
            project_dir.name,
            "ace-run",
            projects_root=projects_dir,
        ):
            scan.artifacts += 1
            project_dirs.append(artifact_dir)
            _record_waiting_marker(scan, project_dir.name, artifact_dir)
    return scan


def _load_index_listing(
    projects_dir: Path, index_path: Path | None
) -> AceRunIndexListing | None:
    """Return the index's ace-run listing, or ``None`` when it cannot be used."""

    try:
        from sase.core.agent_artifact_index_recent import load_ace_run_index_listing
        from sase.core.agent_scan_facade import default_agent_artifact_index_path

        path = default_agent_artifact_index_path() if index_path is None else index_path
        if not path.is_file():
            return None
        return load_ace_run_index_listing(path, projects_dir)
    except Exception:  # noqa: BLE001 - any index problem falls back to the walk.
        return None


def _scan_from_index(
    projects_dir: Path, listing: AceRunIndexListing
) -> _WaitMarkerScan:
    scan = _WaitMarkerScan(source="index")
    for project_dir in projects_dir.iterdir():
        if not project_dir.is_dir():
            continue
        project_name = project_dir.name
        scan.projects += 1
        project_dirs = [
            Path(artifact_dir)
            for artifact_dir in listing.dirs_by_project.get(project_name, ())
        ]
        scan.dirs_by_project[project_name] = project_dirs
        scan.artifacts += len(project_dirs)
        for artifact_dir in listing.waiting_dirs_by_project.get(project_name, ()):
            _record_waiting_marker(scan, project_name, Path(artifact_dir))
    return scan


def _record_waiting_marker(
    scan: _WaitMarkerScan, project_name: str, artifact_dir: Path
) -> None:
    """Classify one artifact dir's ``waiting.json`` into *scan*."""

    waiting_path = os.path.join(str(artifact_dir), "waiting.json")
    if not os.path.exists(waiting_path):
        return
    try:
        with open(waiting_path, encoding="utf-8") as stream:
            waiting_data = json.load(stream)
    except (json.JSONDecodeError, OSError):
        waiting_data = None
    if (
        isinstance(waiting_data, dict)
        and waiting_data.get("cancelled_by_hijack") is True
    ):
        return
    scan.waiting += 1
    marker = WaitingMarker(
        project_name=project_name,
        ready_path=artifact_dir / "ready.json",
        waiting_path=Path(waiting_path),
    )
    if marker.ready_path.exists():
        scan.already_ready += 1
        scan.already_ready_markers.append(marker)
    else:
        scan.pending.append(marker)


def _full_walk_stamp_path() -> Path:
    return sase_subdir("axe") / "wait_checks_last_full_walk"


def wait_scan_full_walk_due(now: float) -> bool:
    """Return whether ``wait_checks`` should walk the filesystem this tick."""

    try:
        stamp = float(_full_walk_stamp_path().read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return True
    # A stamp from the future (clock step) must not suppress walks forever.
    return not 0 <= now - stamp < WAIT_SCAN_FULL_WALK_INTERVAL_SECONDS


def record_wait_scan_full_walk(now: float) -> None:
    """Persist that a filesystem walk completed at *now* (best effort)."""

    path = _full_walk_stamp_path()
    tmp_path = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path.write_text(f"{now}\n", encoding="utf-8")
        tmp_path.replace(path)
    except OSError:
        pass


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
    "WAIT_SCAN_FULL_WALK_INTERVAL_SECONDS",
    "WaitScanSource",
    "WaiterLiveness",
    "record_wait_scan_full_walk",
    "scan_waiting_markers",
    "wait_scan_full_walk_due",
    "waiting_runner_liveness",
]

"""Fail-open Python runtime adapter for durable agent holds."""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import asdict, is_dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from sase.agent.names import is_process_alive
from sase.core.agent_scan_wire import AgentArtifactRecordWire
from sase.core.paths import sase_home, sase_projects_dir
from sase.core.rust import require_rust_binding
from sase.procs.models import TERMINAL_PROC_STATUSES, Proc

if TYPE_CHECKING:
    from sase.core.wait_dependency_resolution import WaitDependencyIndex

LOGGER = logging.getLogger(__name__)


def active_agent_hold_records(
    records: Sequence[AgentArtifactRecordWire] | None = None,
    *,
    now: datetime | float | None = None,
) -> list[dict[str, Any]]:
    """Return validated active holds, or an empty list on hold-store failures."""
    try:
        snapshot = _list_holds({}, now=now)
        holds = _validated_holds(snapshot)
        if not holds:
            return []
        liveness = _liveness_facts_for_holds(
            holds,
            records or (),
            allow_index_scan=records is None,
            now=now,
        )
        snapshot = _list_holds(liveness, now=now)
        return _validated_holds(snapshot)
    except Exception as exc:  # noqa: BLE001 - holds fail open by design.
        LOGGER.warning("agent hold snapshot failed open: %s", exc)
        return []


def _release_agent_hold_key(
    armer_key: str, *, now: datetime | float | None = None
) -> bool:
    """Best-effort idempotent release for one armer key."""
    try:
        release = require_rust_binding("agent_hold_release")
        return bool(release(str(sase_home()), armer_key, {}, _epoch_seconds(now)))
    except Exception as exc:  # noqa: BLE001 - release is cleanup, not settlement.
        LOGGER.warning("agent hold release failed for %s: %s", armer_key, exc)
        return False


def release_proc_agent_holds(
    proc: Proc | Mapping[str, Any] | str,
    *,
    now: datetime | float | None = None,
) -> int:
    """Release every hold armed by a terminal proc identity."""
    proc_id, terminal = _proc_identity_and_terminal(proc)
    if not proc_id or not terminal:
        return 0
    released = 0
    try:
        for hold in _validated_holds(_list_holds({}, now=now)):
            armer = _mapping(hold.get("armer"))
            if armer.get("kind") == "proc" and armer.get("proc_id") == proc_id:
                released += int(_release_agent_hold_key(str(armer.get("key")), now=now))
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning("proc agent-hold reconciliation failed for %s: %s", proc_id, exc)
    return released


def reconcile_agent_holds_for_artifact(
    artifacts_dir: str | Path,
    *,
    records: Sequence[AgentArtifactRecordWire] | None = None,
    now: datetime | float | None = None,
) -> int:
    """Release agent-authored holds whose recorded family generation settled."""
    target_dir = str(Path(artifacts_dir))
    released = 0
    try:
        holds = _validated_holds(_list_holds({}, now=now))
        index_cache = _FamilyIndexCache(records or (), allow_scans=records is None)
        for hold in holds:
            armer = _mapping(hold.get("armer"))
            if armer.get("kind") != "agent":
                continue
            marker_path = armer.get("done_marker_path")
            if not isinstance(marker_path, str) or not marker_path:
                continue
            root_dir = str(Path(marker_path).parent)
            if root_dir != target_dir:
                continue
            project = armer.get("project")
            if isinstance(project, str) and _agent_family_settled(
                root_dir,
                project,
                index_cache,
            ):
                released += int(_release_agent_hold_key(str(armer.get("key")), now=now))
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning(
            "agent hold reconciliation failed for %s: %s",
            target_dir,
            exc,
        )
    return released


def _list_holds(
    liveness: Mapping[str, Any],
    *,
    now: datetime | float | None,
) -> Mapping[str, Any]:
    list_holds = require_rust_binding("agent_hold_list")
    value = list_holds(str(sase_home()), dict(liveness), _epoch_seconds(now))
    if not isinstance(value, Mapping):
        raise RuntimeError("agent_hold_list returned a non-object snapshot")
    return value


def _validated_holds(snapshot: Mapping[str, Any]) -> list[dict[str, Any]]:
    if type(snapshot.get("schema_version")) is not int:
        raise RuntimeError("agent hold snapshot has no integer schema_version")
    raw_holds = snapshot.get("holds")
    if not isinstance(raw_holds, list):
        raise RuntimeError("agent hold snapshot has no holds list")
    holds: list[dict[str, Any]] = []
    for hold in raw_holds:
        if not isinstance(hold, Mapping):
            raise RuntimeError("agent hold record is not an object")
        _validate_hold_record(hold)
        holds.append(dict(hold))
    return holds


def _validate_hold_record(hold: Mapping[str, Any]) -> None:
    armer = _mapping(hold.get("armer"))
    scope = _mapping(hold.get("scope"))
    selectors = _mapping(hold.get("selectors"))
    if type(hold.get("schema_version")) is not int:
        raise RuntimeError("agent hold record has no integer schema_version")
    if armer.get("kind") not in {"agent", "proc", "cli"}:
        raise RuntimeError("agent hold armer kind is invalid")
    for key in ("key", "display", "project"):
        if not isinstance(armer.get(key), str) or not armer.get(key):
            raise RuntimeError(f"agent hold armer {key} is invalid")
    if scope.get("kind") not in {"project", "host"}:
        raise RuntimeError("agent hold scope kind is invalid")
    if not isinstance(selectors, Mapping):
        raise RuntimeError("agent hold selectors are invalid")
    for key in ("created_at", "expires_at"):
        value = hold.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise RuntimeError(f"agent hold {key} is invalid")


def _liveness_facts_for_holds(
    holds: Sequence[Mapping[str, Any]],
    records: Sequence[AgentArtifactRecordWire],
    *,
    allow_index_scan: bool,
    now: datetime | float | None,
) -> dict[str, Any]:
    proc_statuses = _proc_statuses()
    family_indexes = _FamilyIndexCache(records, allow_scans=allow_index_scan)
    facts: dict[str, Any] = {}
    for hold in holds:
        armer = _mapping(hold.get("armer"))
        key = armer.get("key")
        kind = armer.get("kind")
        if not isinstance(key, str):
            continue
        if kind == "proc":
            proc_id = armer.get("proc_id")
            terminal = (
                isinstance(proc_id, str)
                and proc_statuses.get(proc_id) in TERMINAL_PROC_STATUSES
            )
            if isinstance(proc_id, str) and proc_id not in proc_statuses:
                terminal = True
            facts[key] = {"kind": "proc", "terminal": terminal}
        elif kind == "agent":
            facts[key] = _agent_liveness_fact(armer, family_indexes)
        elif kind == "cli":
            facts[key] = _cli_liveness_fact(armer)
    return {"armers": facts}


def _agent_liveness_fact(
    armer: Mapping[str, Any],
    family_indexes: _FamilyIndexCache,
) -> dict[str, Any]:
    marker_path = armer.get("done_marker_path")
    if isinstance(marker_path, str) and marker_path:
        done_present = Path(marker_path).exists()
        if done_present:
            project = armer.get("project")
            settled = isinstance(project, str) and _agent_family_settled(
                str(Path(marker_path).parent),
                project,
                family_indexes,
            )
            return {
                "kind": "agent",
                "pid_alive": not settled,
                "done_marker_present": settled,
            }
    return {
        "kind": "agent",
        "pid_alive": _pid_alive(armer),
        "done_marker_present": False,
    }


def _cli_liveness_fact(armer: Mapping[str, Any]) -> dict[str, Any]:
    marker_path = armer.get("done_marker_path")
    done_present = (
        isinstance(marker_path, str) and marker_path and Path(marker_path).exists()
    )
    return {
        "kind": "cli",
        "pid_alive": _pid_alive(armer),
        "done_marker_present": bool(done_present),
    }


def _pid_alive(armer: Mapping[str, Any]) -> bool:
    pid = armer.get("pid")
    if type(pid) is not int:
        return False
    marker_path = armer.get("done_marker_path")
    artifact_dir = (
        Path(marker_path).parent if isinstance(marker_path, str) else Path(".")
    )
    return is_process_alive({"pid": pid}, artifact_dir)


def _proc_statuses() -> dict[str, str]:
    try:
        from sase.procs.store import read_proc_snapshot

        return {proc.proc_id: proc.status for proc in read_proc_snapshot().procs}
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"proc liveness collection failed: {exc}") from exc


def _proc_identity_and_terminal(
    proc: Proc | Mapping[str, Any] | str,
) -> tuple[str, bool]:
    if isinstance(proc, Proc):
        return proc.proc_id, proc.status in TERMINAL_PROC_STATUSES
    if isinstance(proc, Mapping):
        proc_id = proc.get("proc_id")
        status = proc.get("status")
        return (
            proc_id if isinstance(proc_id, str) else "",
            status in TERMINAL_PROC_STATUSES,
        )
    try:
        from sase.procs.store import get_proc

        current = get_proc(proc)
    except Exception:  # noqa: BLE001
        current = None
    return (
        proc,
        current is not None and current.status in TERMINAL_PROC_STATUSES,
    )


def _agent_family_settled(
    artifact_dir: str,
    project: str,
    family_indexes: _FamilyIndexCache,
) -> bool:
    index = family_indexes.for_project(project)
    if index is None:
        return True
    root = index.artifacts_by_dir.get(str(Path(artifact_dir)))
    if root is None:
        return True
    family = index.family_candidate_for_root(root)
    return family is not None and family.is_resolved


class _FamilyIndexCache:
    def __init__(
        self,
        records: Sequence[AgentArtifactRecordWire],
        *,
        allow_scans: bool,
    ) -> None:
        self._records = records
        self._allow_scans = allow_scans
        self._by_project: dict[str, WaitDependencyIndex] = {}

    def for_project(self, project: str) -> WaitDependencyIndex | None:
        from sase.core.wait_dependency_resolution import WaitDependencyIndex

        cached = self._by_project.get(project)
        if cached is not None:
            return cached
        index = self._index_from_records(project)
        if index is None and self._allow_scans:
            index = WaitDependencyIndex.build(
                project, projects_root=sase_projects_dir()
            )
        if index is None:
            return None
        self._by_project[project] = index
        return index

    def _index_from_records(self, project: str) -> WaitDependencyIndex | None:
        from sase.core.wait_dependency_resolution import WaitDependencyIndex

        project_records = [
            record for record in self._records if record.project_name == project
        ]
        if not project_records:
            return None
        index = WaitDependencyIndex.empty()
        for record in project_records:
            meta = _dataclass_dict(record.agent_meta)
            if meta is None:
                continue
            index.add_scan_record(
                Path(record.artifact_dir),
                meta,
                project_name=record.project_name,
                done_data=_dataclass_dict(record.done),
            )
        return index


def _dataclass_dict(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if is_dataclass(value):
        return asdict(cast(Any, value))
    if isinstance(value, Mapping):
        return dict(value)
    return None


def _mapping(value: Any) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise RuntimeError("agent hold payload is not an object")
    return value


def _epoch_seconds(value: datetime | float | None) -> float | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        normalized = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return normalized.timestamp()
    return float(value)


def candidate_created_at_from_timestamp(timestamp: str | None) -> float | None:
    """Return a configured-timezone epoch for a 14-digit artifact timestamp."""
    if not timestamp or len(timestamp) != 14 or not timestamp.isdigit():
        return None
    try:
        from sase.core.time import get_timezone

        parsed = datetime.strptime(timestamp, "%Y%m%d%H%M%S")
        return parsed.replace(tzinfo=get_timezone()).timestamp()
    except (OSError, OverflowError, ValueError):
        return None


__all__ = [
    "active_agent_hold_records",
    "candidate_created_at_from_timestamp",
    "reconcile_agent_holds_for_artifact",
    "release_proc_agent_holds",
]

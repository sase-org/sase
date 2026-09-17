"""Armer-liveness helpers for durable agent holds."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, is_dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from sase.core.agent_hold_store import mapping_payload, read_json_mapping
from sase.core.agent_scan_wire import AgentArtifactRecordWire
from sase.core.paths import sase_projects_dir
from sase.procs.models import TERMINAL_PROC_STATUSES, Proc

if TYPE_CHECKING:
    from sase.core.wait_dependency_resolution import WaitDependencyIndex


def liveness_facts_for_holds(
    holds: Sequence[Mapping[str, Any]],
    records: Sequence[AgentArtifactRecordWire],
    *,
    allow_index_scan: bool,
    now: datetime | float | None,
) -> dict[str, Any]:
    proc_statuses = _proc_status_records()
    family_indexes = FamilyIndexCache(records, allow_scans=allow_index_scan)
    facts: dict[str, Any] = {}
    for hold in holds:
        armer = mapping_payload(hold.get("armer"))
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
        elif kind == "launch":
            facts[key] = _launch_liveness_fact(armer)
    return {"armers": facts}


def _agent_liveness_fact(
    armer: Mapping[str, Any],
    family_indexes: FamilyIndexCache,
) -> dict[str, Any]:
    marker_path = armer.get("done_marker_path")
    if isinstance(marker_path, str) and marker_path:
        done_present = Path(marker_path).exists()
        if done_present:
            project = armer.get("project")
            settled = isinstance(project, str) and agent_family_settled(
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


def _launch_liveness_fact(armer: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "kind": "launch",
        "pid_alive": _launch_pid_alive(armer),
        "done_marker_present": _launch_done_marker_present(armer),
    }


def _launch_pid_alive(armer: Mapping[str, Any]) -> bool:
    if _pid_alive(armer):
        return True
    marker_path = armer.get("done_marker_path")
    if not isinstance(marker_path, str) or not marker_path:
        return False
    # Deferred: see the comment in `_pid_alive` -- `sase.agent` submodules
    # reach back into agent_hold_facade at package-init time.
    from sase.agent.launch_admission_store import STARTED_FILENAME

    started = read_json_mapping(Path(marker_path).parent / STARTED_FILENAME)
    pid = started.get("pid")
    if type(pid) is not int:
        return False
    from sase.ace.hooks.processes import is_process_running

    return is_process_running(pid)


def _launch_done_marker_present(armer: Mapping[str, Any]) -> bool:
    marker_path = armer.get("done_marker_path")
    if not isinstance(marker_path, str) or not marker_path:
        return False
    from sase.agent.launch_admission_store import RECEIPT_FILENAME

    path = Path(marker_path)
    if path.name == RECEIPT_FILENAME:
        return read_json_mapping(path).get("complete") is True
    return path.exists()


def _pid_alive(armer: Mapping[str, Any]) -> bool:
    # Deferred: sase.agent's own init chain reaches back into agent_hold_facade
    # (via runner_slots -> _admission_capacity_records) for the unrelated
    # candidate_created_at_from_timestamp helper, so a module-level import here
    # would make hold liveness a circular-import root whenever it is loaded first.
    from sase.agent.names import is_process_alive

    pid = armer.get("pid")
    if type(pid) is not int:
        return False
    marker_path = armer.get("done_marker_path")
    artifact_dir = (
        Path(marker_path).parent if isinstance(marker_path, str) else Path(".")
    )
    return is_process_alive({"pid": pid}, artifact_dir)


def _proc_status_records() -> dict[str, str]:
    try:
        from sase.procs.store import read_proc_snapshot

        return {proc.proc_id: proc.status for proc in read_proc_snapshot().procs}
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"proc liveness collection failed: {exc}") from exc


def proc_identity_and_terminal(
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


def agent_family_settled(
    artifact_dir: str,
    project: str,
    family_indexes: FamilyIndexCache,
) -> bool:
    index = family_indexes.for_project(project)
    if index is None:
        return True
    root = index.artifacts_by_dir.get(str(Path(artifact_dir)))
    if root is None:
        return True
    family = index.family_candidate_for_root(root)
    return family is not None and family.is_resolved


class FamilyIndexCache:
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

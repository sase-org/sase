"""Python runtime adapter for durable agent holds.

Admission-path readers (:func:`active_agent_hold_records` and friends) stay
fail-open by design: a broken hold store must never strand a waiter. The
CLI/directive-facing service functions below it -- :func:`arm_agent_hold`,
:func:`release_agent_hold`, :func:`list_current_agent_holds` -- are the
opposite: they are direct user actions, so Rust validation and lock-timeout
errors propagate instead of being swallowed.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, is_dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from sase.core.agent_scan_wire import AgentArtifactRecordWire
from sase.core.paths import sase_home, sase_projects_dir
from sase.core.rust import require_rust_binding
from sase.procs.models import TERMINAL_PROC_STATUSES, Proc

if TYPE_CHECKING:
    from sase.core.wait_dependency_resolution import WaitDependencyIndex

LOGGER = logging.getLogger(__name__)

_AGENT_HOLD_SENDER = "agent_hold"


def active_agent_hold_records(
    records: Sequence[AgentArtifactRecordWire] | None = None,
    *,
    now: datetime | float | None = None,
) -> list[dict[str, Any]]:
    """Return validated active holds, or an empty list on hold-store failures."""
    try:
        before, after = _list_and_reconcile_holds(
            records or (), allow_index_scan=records is None, now=now
        )
    except Exception as exc:  # noqa: BLE001 - holds fail open by design.
        LOGGER.warning("agent hold snapshot failed open: %s", exc)
        return []
    _notify_liveness_dropped_holds(before, after, now=now)
    return after


def list_current_agent_holds(
    records: Sequence[AgentArtifactRecordWire] | None = None,
    *,
    now: datetime | float | None = None,
) -> list[dict[str, Any]]:
    """Return validated active holds for CLI/directive-facing callers.

    Unlike :func:`active_agent_hold_records`, failures propagate: a CLI
    command should report a broken hold store clearly instead of silently
    showing an empty list.
    """
    before, after = _list_and_reconcile_holds(
        records or (), allow_index_scan=records is None, now=now
    )
    _notify_liveness_dropped_holds(before, after, now=now)
    return after


def find_agent_hold(
    armer_key: str,
    *,
    now: datetime | float | None = None,
) -> dict[str, Any] | None:
    """Return the one active hold armed by *armer_key*, if any."""
    for hold in list_current_agent_holds(now=now):
        if _mapping(hold.get("armer")).get("key") == armer_key:
            return hold
    return None


def _list_and_reconcile_holds(
    records: Sequence[AgentArtifactRecordWire],
    *,
    allow_index_scan: bool,
    now: datetime | float | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return ``(before, after)`` validated holds across a liveness pass.

    ``before`` has expired/malformed rows pruned but no per-armer liveness
    facts applied; ``after`` additionally prunes armers the current
    liveness facts say are dead. Both raise on genuine store failures --
    callers decide whether to fail open.
    """
    snapshot = _list_holds({}, now=now)
    before = _validated_holds(snapshot)
    if not before:
        return [], []
    liveness = _liveness_facts_for_holds(
        before, records, allow_index_scan=allow_index_scan, now=now
    )
    snapshot = _list_holds(liveness, now=now)
    return before, _validated_holds(snapshot)


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


class _AgentHoldServiceError(RuntimeError):
    """Raised when a CLI/directive-facing hold action can't resolve its context."""


@dataclass(frozen=True)
class _PendingCapture:
    """WAITING/QUEUED artifact dirs frozen as a ``pending`` selector at arm time."""

    artifact_dirs: tuple[str, ...]
    waiting_count: int
    queued_count: int
    skipped_running_count: int


@dataclass(frozen=True)
class AgentHoldArmResult:
    """The armed record plus the pending snapshot that produced its selectors."""

    record: dict[str, Any]
    capture: _PendingCapture | None


def current_armer_wire(
    *,
    pid_override: int | None = None,
    env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Build the armer wire payload for the process invoking a hold action.

    Uses the current agent's metadata when ``SASE_ARTIFACTS_DIR`` is set,
    and a standalone ``cli``-kind armer otherwise.
    """
    current_env = env if env is not None else os.environ
    artifacts_dir = (current_env.get("SASE_ARTIFACTS_DIR") or "").strip()
    if artifacts_dir:
        return _agent_armer_wire(artifacts_dir)
    return _cli_armer_wire(pid_override=pid_override)


def _agent_armer_wire(artifacts_dir: str) -> dict[str, Any]:
    meta = _read_json_mapping(Path(artifacts_dir) / "agent_meta.json")
    name = meta.get("name")
    if not isinstance(name, str) or not name.strip():
        raise _AgentHoldServiceError(
            f"cannot determine agent identity from {artifacts_dir}/agent_meta.json"
        )
    name = name.strip()
    pid = meta.get("pid")
    family = meta.get("agent_family")
    clan = meta.get("agent_clan")
    return {
        "kind": "agent",
        "key": f"agent:{name}",
        "display": name,
        "project": _project_for_artifacts_dir(artifacts_dir),
        "agent_name": name,
        "family": family if isinstance(family, str) and family else None,
        "clan": clan if isinstance(clan, str) and clan else None,
        "pid": pid if isinstance(pid, int) else None,
        "done_marker_path": str(Path(artifacts_dir) / "done.json"),
    }


def _cli_armer_wire(*, pid_override: int | None) -> dict[str, Any]:
    import getpass
    import socket

    # A bare CLI invocation exits the moment `create` returns, so anchoring
    # liveness to its own pid would prune the hold before the caller's next
    # command runs. `run` passes the wrapped command's pid explicitly; a
    # bare `create`/`release` pair anchors to the parent shell instead, so
    # the hold survives for the invoking terminal session (and self-cleans
    # once that session ends), matching the durable-until-TTL-or-release
    # contract manual arm/release scripting depends on.
    pid = pid_override if pid_override is not None else os.getppid()
    from sase.config.core import get_machine_name

    host = get_machine_name() or socket.gethostname() or "local"
    try:
        user = getpass.getuser()
    except (KeyError, OSError):
        user = "unknown"
    return {
        "kind": "cli",
        "key": f"cli:{host}:{pid}",
        "display": f"{user}@{host} (pid {pid})",
        "project": _project_for_cwd(),
        "pid": pid,
    }


def _project_for_artifacts_dir(artifacts_dir: str) -> str:
    from sase.core.agent_artifact_paths import parse_agent_artifact_path

    try:
        parsed = parse_agent_artifact_path(artifacts_dir)
    except (OSError, RuntimeError, ValueError):
        parsed = None
    if parsed is not None and parsed.project_name:
        return parsed.project_name
    return _project_for_cwd()


def _project_for_cwd() -> str:
    from sase.bead.project_name import infer_project_name_from_cwd

    project = infer_project_name_from_cwd()
    if not project:
        raise _AgentHoldServiceError(
            "cannot determine the current project; run from inside a SASE "
            "project checkout, or from an agent shell with SASE_ARTIFACTS_DIR set"
        )
    return project


def _read_json_mapping(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _hold_scope_wire(scope: str, *, project: str) -> dict[str, Any]:
    """Build the scope wire payload for ``--scope project|host``."""
    if scope == "host":
        return {"kind": "host"}
    return {"kind": "project", "project": project}


def _hold_selectors_wire(
    *,
    names: Sequence[str] = (),
    tribes: Sequence[str] = (),
    hoods: Sequence[str] = (),
    future: bool = False,
    artifact_dirs: Sequence[str] = (),
) -> dict[str, Any]:
    """Build the selectors wire payload from CLI-facing selector inputs."""
    return {
        "artifact_dirs": list(artifact_dirs),
        "names": list(names),
        "hoods": list(hoods),
        "tribes": [_normalize_tribe(tribe) for tribe in tribes],
        "future": bool(future),
    }


def _normalize_tribe(value: str) -> str:
    stripped = value.strip()
    return stripped[1:] if stripped.startswith("@") else stripped


def _capture_pending_targets(*, project: str | None) -> _PendingCapture:
    """Snapshot WAITING/QUEUED artifact dirs to freeze as a ``pending`` selector.

    ``project`` scopes the snapshot the same way the hold's own scope will:
    a project-scoped hold only freezes that project's pending agents, while
    a host-scoped hold (``project=None``) freezes every project's.
    """
    from sase.agent.status_buckets import QUEUED_STATUS
    from sase.integrations.agent_list_entries import agent_list_entries

    artifact_dirs: list[str] = []
    waiting_count = 0
    queued_count = 0
    skipped_running_count = 0
    for entry in agent_list_entries(project=project):
        if entry.status == "WAITING":
            waiting_count += 1
            if entry.artifacts_dir:
                artifact_dirs.append(entry.artifacts_dir)
        elif entry.status == QUEUED_STATUS:
            queued_count += 1
            if entry.artifacts_dir:
                artifact_dirs.append(entry.artifacts_dir)
        else:
            skipped_running_count += 1
    return _PendingCapture(
        artifact_dirs=tuple(artifact_dirs),
        waiting_count=waiting_count,
        queued_count=queued_count,
        skipped_running_count=skipped_running_count,
    )


def arm_agent_hold(
    *,
    names: Sequence[str] = (),
    tribes: Sequence[str] = (),
    hoods: Sequence[str] = (),
    future: bool = False,
    pending: bool = False,
    scope: str = "project",
    ttl_seconds: float,
    pid_override: int | None = None,
    now: datetime | float | None = None,
) -> AgentHoldArmResult:
    """Arm a durable hold and upsert its "armed" lifecycle notification.

    Errors propagate: this is a direct CLI/directive action, not an
    admission-path read, so Rust validation and lock-timeout failures must
    reach the caller instead of being swallowed.
    """
    armer = current_armer_wire(pid_override=pid_override)
    scope_wire = _hold_scope_wire(scope, project=armer["project"])
    capture: _PendingCapture | None = None
    artifact_dirs: tuple[str, ...] = ()
    if pending:
        capture = _capture_pending_targets(
            project=armer["project"] if scope == "project" else None
        )
        artifact_dirs = capture.artifact_dirs
    selectors = _hold_selectors_wire(
        names=names,
        tribes=tribes,
        hoods=hoods,
        future=future,
        artifact_dirs=artifact_dirs,
    )
    arm = require_rust_binding("agent_hold_arm_relative")
    record = dict(
        arm(
            str(sase_home()),
            armer,
            scope_wire,
            selectors,
            float(ttl_seconds),
            {},
            _epoch_seconds(now),
        )
    )
    _upsert_hold_armed_notification(record, capture, now=now)
    return AgentHoldArmResult(record=record, capture=capture)


def release_agent_hold(
    armer_key: str,
    *,
    now: datetime | float | None = None,
    display: str | None = None,
    reason: str = "Released explicitly",
) -> bool:
    """Release one hold by armer key, surfacing failures to the caller.

    This is the CLI/service counterpart to the fail-open
    :func:`_release_agent_hold_key` used by background reconciliation.
    """
    release = require_rust_binding("agent_hold_release")
    removed = bool(release(str(sase_home()), armer_key, {}, _epoch_seconds(now)))
    if removed:
        _upsert_hold_released_notification(
            {"key": armer_key, "display": display or armer_key},
            reason=reason,
            now=now,
        )
    return removed


def _upsert_hold_armed_notification(
    record: Mapping[str, Any],
    capture: _PendingCapture | None,
    *,
    now: datetime | float | None,
) -> None:
    from uuid import uuid4

    from sase.notifications.models import Notification, normalize_notification_tags
    from sase.notifications.store import upsert_notification

    armer = _mapping(record.get("armer"))
    key = armer.get("key")
    if not isinstance(key, str) or not key:
        return
    display = armer.get("display") or key
    timestamp = _iso_timestamp(now)
    notes = [
        f"Armed by {display}",
        f"Expires: {_format_epoch(record.get('expires_at'))}",
    ]
    if capture is not None:
        notes.append(
            f"Captured {len(capture.artifact_dirs)} pending "
            f"({capture.waiting_count} waiting, {capture.queued_count} queued); "
            f"skipped {capture.skipped_running_count} running"
        )
    try:
        upsert_notification(
            Notification(
                id=str(uuid4()),
                timestamp=timestamp,
                sender=_AGENT_HOLD_SENDER,
                icon="⏸",
                color="#5F87FF",
                notes=notes,
                tags=normalize_notification_tags(["agent-hold", "armed"]),
                action_data={
                    "armer_key": key,
                    "expires_at": str(record.get("expires_at")),
                },
                dedup_key=f"agent_hold:armed:{key}",
            ),
            plus_one_note="Re-armed",
            plus_one_timestamp=timestamp,
        )
    except Exception as exc:  # noqa: BLE001 - notification is best-effort.
        LOGGER.warning("agent hold armed notification failed for %s: %s", key, exc)


def _upsert_hold_released_notification(
    armer: Mapping[str, Any],
    *,
    reason: str,
    now: datetime | float | None,
) -> None:
    from uuid import uuid4

    from sase.notifications.models import Notification, normalize_notification_tags
    from sase.notifications.store import upsert_notification

    key = armer.get("key")
    if not isinstance(key, str) or not key:
        return
    display = armer.get("display") or key
    timestamp = _iso_timestamp(now)
    try:
        upsert_notification(
            Notification(
                id=str(uuid4()),
                timestamp=timestamp,
                sender=_AGENT_HOLD_SENDER,
                icon="▶",
                color="#5FAF5F",
                notes=[f"Released: {display}", reason],
                tags=normalize_notification_tags(["agent-hold", "released"]),
                action_data={"armer_key": key},
                dedup_key=f"agent_hold:released:{key}",
            ),
            plus_one_note=f"Released again: {reason}",
            plus_one_timestamp=timestamp,
        )
    except Exception as exc:  # noqa: BLE001 - notification is best-effort.
        LOGGER.warning("agent hold released notification failed for %s: %s", key, exc)


def _notify_liveness_dropped_holds(
    before: Sequence[Mapping[str, Any]],
    after: Sequence[Mapping[str, Any]],
    *,
    now: datetime | float | None,
) -> None:
    """Notify for holds present in *before* but pruned by liveness in *after*.

    A hold missing from *before* too (pruned by TTL expiry on the very
    first read) never reaches here, so a routine expiry stays silent while
    an early, armer-death-triggered release still surfaces.
    """
    dropped_keys = {_mapping(hold.get("armer")).get("key") for hold in before} - {
        _mapping(hold.get("armer")).get("key") for hold in after
    }
    if not dropped_keys:
        return
    for hold in before:
        armer = _mapping(hold.get("armer"))
        key = armer.get("key")
        if key not in dropped_keys:
            continue
        _upsert_hold_released_notification(
            armer,
            reason="Released automatically: armer no longer alive",
            now=now,
        )


def _iso_timestamp(value: datetime | float | None) -> str:
    from sase.core.time import get_timezone

    if isinstance(value, datetime):
        normalized = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return normalized.isoformat()
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return datetime.fromtimestamp(value, tz=UTC).isoformat()
    return datetime.now(get_timezone()).isoformat()


def _format_epoch(value: Any) -> str:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return "unknown"
    return datetime.fromtimestamp(float(value), tz=UTC).isoformat()


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
    # Deferred: sase.agent's own init chain reaches back into this module
    # (via runner_slots -> _admission_capacity_records) for the unrelated
    # candidate_created_at_from_timestamp helper below, so a module-level
    # import here would make this module a circular-import root whenever
    # it -- rather than sase.agent -- is the first thing a process touches.
    from sase.agent.names import is_process_alive

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
    "AgentHoldArmResult",
    "active_agent_hold_records",
    "arm_agent_hold",
    "candidate_created_at_from_timestamp",
    "current_armer_wire",
    "find_agent_hold",
    "list_current_agent_holds",
    "reconcile_agent_holds_for_artifact",
    "release_agent_hold",
    "release_proc_agent_holds",
]

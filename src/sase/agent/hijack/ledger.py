"""Durable Agent Hijack records under ``~/.sase/agent_hijacks/``.

Active records live in the ledger root; terminal records move to
``settled/`` so hot reads stay O(unresolved). Exclusive create uses
``O_EXCL`` (via ``atomic_write_json(..., exclusive=True)``). Later
transitions re-read under an ``fcntl`` lock and CAS on ``revision``
through the Rust ``advance_agent_hijack_record`` state machine.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from sase.agent.hijack.core import (
    advance_agent_hijack_record,
    agent_hijack_wire_schema_version,
)
from sase.core.paths import sase_subdir
from sase.core.time import get_timezone
from sase.notification_gates.durability import atomic_write_json, file_lock

LEDGER_DIRNAME = "agent_hijacks"
SETTLED_DIRNAME = "settled"

TERMINAL_STATES = frozenset(
    {
        "resolved",
        "dismissed",
        "expired",
        "stop_failed",
        "finished_first",
    }
)

HIJACK_EVENT_BEGIN_STOP = "begin_stop"


class HijackLedgerConflict(RuntimeError):
    """Raised when a CAS transition loses to a concurrent writer."""


def _hijack_ledger_root() -> Path:
    """Return the hijack ledger root (never inside an artifacts directory)."""
    return sase_subdir(LEDGER_DIRNAME)


def _hijack_settled_dir() -> Path:
    """Return the directory that holds terminal hijack records."""
    return _hijack_ledger_root() / SETTLED_DIRNAME


def _safe_hijack_id(hijack_id: str) -> str:
    cleaned = "".join(
        ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in hijack_id
    ).strip("_")
    return cleaned or "hijack"


def hijack_record_path(hijack_id: str, *, settled: bool = False) -> Path:
    """Return the JSON path for one hijack id."""
    name = f"{_safe_hijack_id(hijack_id)}.json"
    directory = _hijack_settled_dir() if settled else _hijack_ledger_root()
    return directory / name


def hijack_record_lock_path(hijack_id: str) -> Path:
    return hijack_record_path(hijack_id).with_suffix(".lock")


def timestamp_for(at: float | None = None) -> str:
    """Format an epoch timestamp as ISO-8601 in the configured timezone."""
    import time

    stamp = time.time() if at is None else at
    return datetime.fromtimestamp(stamp, tz=get_timezone()).isoformat()


def new_requested_record(
    *,
    hijack_id: str,
    agent_name: str,
    artifacts_dir: str,
    pid: int | None = None,
    process_identity_token: str | None = None,
    project_file: str | None = None,
    workspace_num: int | None = None,
    workspace_dir: str | None = None,
    expected_claim_owner_pid: int | None = None,
    session: str | None = None,
    host: str | None = None,
    model_alias: str | None = None,
    model_alias_trail: list[str] | None = None,
    model_origin: str | None = None,
    provider: str | None = None,
    model: str | None = None,
    effort: str | None = None,
    at: str | None = None,
) -> dict[str, Any]:
    """Return a v1 wire dict in ``requested`` ready for exclusive create."""
    stamp = at or timestamp_for()
    return {
        "schema_version": agent_hijack_wire_schema_version(),
        "hijack_id": hijack_id,
        "agent_name": agent_name,
        "artifacts_dir": artifacts_dir,
        "session": session,
        "host": host,
        "pid": pid,
        "process_identity_token": process_identity_token,
        "project_file": project_file,
        "workspace_num": workspace_num,
        "workspace_dir": workspace_dir,
        "expected_claim_owner_pid": expected_claim_owner_pid,
        "prior_pin_state": None,
        "model_alias": model_alias,
        "model_alias_trail": list(model_alias_trail or ()),
        "model_origin": model_origin,
        "provider": provider,
        "model": model,
        "effort": effort,
        "run_duration_seconds": None,
        "last_tool": None,
        "last_tool_age_seconds": None,
        "repo_diffs": [],
        "snapshots": [],
        "stale_lock_files": [],
        "survivor_pids": [],
        "state": "requested",
        "revision": 0,
        "hijacked_at": stamp,
        "updated_at": stamp,
        "resolution_action": None,
        "resolution_origin_state": None,
        "reserved_successor_name": None,
        "concrete_target_model": None,
        "model_changed": None,
        "resolver_pid": None,
        "resolver_process_identity_token": None,
        "launch_identity": None,
        "admission_request_id": None,
        "admission_identity": None,
        "launch_stage": None,
        "successor_pid": None,
        "successor_process_identity_token": None,
        "successor_artifacts_dir": None,
        "inheritance_acknowledged": None,
        "error": None,
        "acknowledged": False,
    }


def read_hijack_record_payload(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, NotADirectoryError):
        return None
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    hijack_id = payload.get("hijack_id")
    if not isinstance(hijack_id, str) or not hijack_id:
        return None
    return payload


def load_record(hijack_id: str) -> dict[str, Any] | None:
    """Load one record from the active dir, then ``settled/``."""
    payload = read_hijack_record_payload(hijack_record_path(hijack_id))
    if payload is not None:
        return payload
    return read_hijack_record_payload(hijack_record_path(hijack_id, settled=True))


def create_record(record: dict[str, Any]) -> dict[str, Any]:
    """Exclusively create one hijack record. Raises ``FileExistsError``."""
    hijack_id = str(record["hijack_id"])
    path = hijack_record_path(hijack_id)
    atomic_write_json(path, record, exclusive=True)
    return dict(record)


def _move_to_settled(hijack_id: str) -> None:
    active = hijack_record_path(hijack_id)
    settled = hijack_record_path(hijack_id, settled=True)
    settled.parent.mkdir(parents=True, exist_ok=True)
    try:
        os_replace = active.replace
        os_replace(settled)
    except FileNotFoundError:
        return
    try:
        hijack_record_lock_path(hijack_id).unlink(missing_ok=True)
    except OSError:
        pass


def cas_advance_record(
    record: dict[str, Any],
    event: dict[str, Any],
) -> dict[str, Any]:
    """CAS-advance *record* through the core state machine under a file lock.

    Re-reads the on-disk payload and refuses when ``revision`` no longer
    matches, so concurrent writers yield exactly one winner.
    """
    hijack_id = str(record["hijack_id"])
    expected_revision = int(record["revision"])
    path = hijack_record_path(hijack_id)
    event_payload = dict(event)
    event_payload.setdefault("at", timestamp_for())
    try:
        with file_lock(hijack_record_lock_path(hijack_id), timeout=10.0):
            current = read_hijack_record_payload(path)
            if current is None:
                raise HijackLedgerConflict(
                    f"hijack record {hijack_id} disappeared during CAS"
                )
            if int(current.get("revision", -1)) != expected_revision:
                raise HijackLedgerConflict(
                    f"hijack record {hijack_id} revision "
                    f"{current.get('revision')} != {expected_revision}"
                )
            advanced = advance_agent_hijack_record(current, event_payload)
            atomic_write_json(path, advanced)
            if advanced.get("state") in TERMINAL_STATES:
                _move_to_settled(hijack_id)
            return dict(advanced)
    except HijackLedgerConflict:
        raise
    except FileNotFoundError as exc:
        raise HijackLedgerConflict(
            f"hijack record {hijack_id} disappeared during CAS"
        ) from exc


def list_active_records() -> list[dict[str, Any]]:
    """Load every active (unsettled) record, newest mtime first."""
    directory = _hijack_ledger_root()
    try:
        paths = sorted(
            directory.glob("*.json"),
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        )
    except OSError:
        return []
    records: list[dict[str, Any]] = []
    for path in paths:
        if path.name.endswith(".lock"):
            continue
        payload = read_hijack_record_payload(path)
        if payload is not None:
            records.append(payload)
    return records


def list_recoverable_records() -> list[dict[str, Any]]:
    """Load every record whose hijacked run can still be recovered.

    That is every active record plus settled ``expired`` holds: an expired
    hold has released its workspace claim but still offers Restart, Edit,
    View, and Dismiss, which read the hijacked run's artifacts directory.
    """
    records = list_active_records()
    try:
        settled_paths = tuple(_hijack_settled_dir().glob("*.json"))
    except OSError:
        return records
    for path in settled_paths:
        payload = read_hijack_record_payload(path)
        if payload is not None and payload.get("state") == "expired":
            records.append(payload)
    return records


def load_record_by_artifacts_dir(artifacts_dir: str) -> dict[str, Any] | None:
    """Return the active record whose ``artifacts_dir`` matches, if any."""
    wanted = str(artifacts_dir)
    for record in list_active_records():
        if str(record.get("artifacts_dir") or "") == wanted:
            return record
    return None


def load_record_by_agent_name(agent_name: str) -> dict[str, Any] | None:
    """Return the newest active record for *agent_name*, if any."""
    wanted = str(agent_name)
    for record in list_active_records():
        if str(record.get("agent_name") or "") == wanted:
            return record
    return None


def load_record_by_workspace(
    project_file: str, workspace_num: int
) -> dict[str, Any] | None:
    """Return the active record for ``(project_file, workspace_num)``."""
    wanted_project = str(project_file)
    wanted_workspace = int(workspace_num)
    for record in list_active_records():
        if str(record.get("project_file") or "") != wanted_project:
            continue
        raw_workspace = record.get("workspace_num")
        try:
            record_workspace = int(raw_workspace)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            continue
        if record_workspace == wanted_workspace:
            return record
    return None


def mark_stopping_if_requested(artifacts_dir: str | None) -> dict[str, Any] | None:
    """Move the matching record from ``requested`` to ``stopping``.

    The runner never writes ``held``; evidence is the orchestrator's job.
    Missing records and already-advanced states are no-ops.
    """
    if not artifacts_dir:
        return None
    record = load_record_by_artifacts_dir(artifacts_dir)
    if record is None or record.get("state") != "requested":
        return record
    try:
        return cas_advance_record(record, {"event": HIJACK_EVENT_BEGIN_STOP})
    except HijackLedgerConflict:
        return load_record_by_artifacts_dir(artifacts_dir)


__all__ = [
    "HIJACK_EVENT_BEGIN_STOP",
    "HijackLedgerConflict",
    "TERMINAL_STATES",
    "cas_advance_record",
    "create_record",
    "hijack_record_lock_path",
    "hijack_record_path",
    "list_active_records",
    "load_record",
    "load_record_by_agent_name",
    "load_record_by_artifacts_dir",
    "load_record_by_workspace",
    "mark_stopping_if_requested",
    "new_requested_record",
    "read_hijack_record_payload",
    "timestamp_for",
]

"""At-most-once restart ledger under ``~/.sase/agent_auto_restart/``.

One record per lineage, claimed with ``atomic_write_json(..., exclusive=True)``
before any mutation. Later transitions go through the sase-core state machine
under a file lock. Python-owned context the wire does not carry (claimer
liveness, the verdict, witnesses, the plan digest) rides alongside the wire
dict under ``python_*`` keys, which are stripped before any core call.

Nothing here may live inside an artifacts directory: a forced-reuse wipe could
remove it.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sase.core.agent_auto_restart_wire import (
    AGENT_AUTO_RESTART_WIRE_SCHEMA_VERSION,
    AutoRestartLedgerRecordWire,
    ledger_record_from_dict,
    ledger_record_to_dict,
)

SCHEMA_VERSION = AGENT_AUTO_RESTART_WIRE_SCHEMA_VERSION

LEDGER_DIRNAME = "ledger"
DOORBELL_DIRNAME = "doorbell"

_EXTRA_KEYS = (
    "python_claimer_pid",
    "python_claimer_identity",
    "python_verdict",
    "python_witnesses",
    "python_plan_digest",
    "python_last_note",
    "python_updated_at",
)


def auto_restart_root() -> Path:
    """Return the ledger root (never inside an artifacts directory)."""
    from sase.core.paths import sase_subdir

    return sase_subdir("agent_auto_restart")


def _ledger_dir() -> Path:
    """Return the directory holding one JSON record per lineage."""
    return auto_restart_root() / LEDGER_DIRNAME


def ledger_key(project: str, lineage_root: str) -> str:
    """Return the ledger key (and filename stem) for a lineage."""
    safe_project = (
        "".join(
            ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in project
        ).strip("_")
        or "project"
    )
    safe_lineage = (
        "".join(
            ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in lineage_root
        ).strip("_")
        or "lineage"
    )
    return f"{safe_project}__{safe_lineage}"


def _ledger_record_path(key: str) -> Path:
    """Return the JSON path for one ledger key."""
    return _ledger_dir() / f"{key}.json"


@dataclass(frozen=True)
class StoredLedgerRecord:
    """A wire record plus the Python-owned context stored alongside it."""

    record: AutoRestartLedgerRecordWire
    extra: dict[str, Any]


def _split_stored(payload: dict[str, Any]) -> StoredLedgerRecord:
    extra = {k: payload[k] for k in _EXTRA_KEYS if k in payload}
    wire_payload = {k: v for k, v in payload.items() if k not in _EXTRA_KEYS}
    return StoredLedgerRecord(record=ledger_record_from_dict(wire_payload), extra=extra)


def _join_stored(record: AutoRestartLedgerRecordWire, extra: dict[str, Any]) -> dict:
    payload = ledger_record_to_dict(record)
    for key in _EXTRA_KEYS:
        if key in extra:
            payload[key] = extra[key]
    payload["python_updated_at"] = time.time()
    return payload


def timestamp_for(at: float | None = None) -> str:
    """Format an epoch timestamp as ISO-8601 in the configured timezone."""
    from datetime import datetime

    from sase.core.time import get_timezone

    stamp = time.time() if at is None else at
    return datetime.fromtimestamp(stamp, tz=get_timezone()).isoformat()


def load_ledger_record(key: str) -> StoredLedgerRecord | None:
    """Load one ledger record, or ``None`` when no claim exists."""
    import json

    path = _ledger_record_path(key)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, NotADirectoryError):
        return None
    except (OSError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    try:
        return _split_stored(payload)
    except (ValueError, KeyError, TypeError):
        return None


def claim_ledger_record(
    *,
    key: str,
    lineage_root: str,
    agent_name: str | None = None,
    project: str | None = None,
    failed_artifacts_dir: str | None = None,
    at: str | None = None,
) -> StoredLedgerRecord | None:
    """Claim a lineage exactly once; ``None`` when another claim owns it.

    The claim is recorded before any mutation. Any uncertainty resolves to
    "attempt spent": a pre-existing record is returned untouched, never
    overwritten.
    """
    from sase.core.agent_auto_restart_facade import claim_auto_restart_ledger
    from sase.core.process_identity import process_identity_token
    from sase.notification_gates.durability import atomic_write_json

    existing = load_ledger_record(key)
    if existing is not None:
        return existing
    record = claim_auto_restart_ledger(key, lineage_root, at=at or timestamp_for())
    pid = os.getpid()
    try:
        identity: str | None = process_identity_token(pid)
    except Exception:
        identity = None
    stored = StoredLedgerRecord(
        record=record,
        extra={
            "python_claimer_pid": pid,
            "python_claimer_identity": identity,
            "python_updated_at": time.time(),
        },
    )
    payload = _join_stored(record, stored.extra)
    if agent_name is not None:
        payload["agent_name"] = agent_name
    if project is not None:
        payload["project"] = project
    if failed_artifacts_dir is not None:
        payload["failed_artifacts_dir"] = failed_artifacts_dir
    try:
        atomic_write_json(_ledger_record_path(key), payload, exclusive=True)
    except FileExistsError:
        return load_ledger_record(key)
    stored = _split_stored(payload)
    return StoredLedgerRecord(record=stored.record, extra=dict(stored.extra))


def store_ledger_record(
    stored: StoredLedgerRecord, *, extra: dict[str, Any] | None = None
) -> StoredLedgerRecord:
    """Atomically replace one ledger record under a file lock."""
    from sase.notification_gates.durability import atomic_write_json, file_lock

    merged = dict(stored.extra)
    if extra:
        for key in _EXTRA_KEYS:
            if key in extra:
                merged[key] = extra[key]
    payload = _join_stored(stored.record, merged)
    path = _ledger_record_path(stored.record.key)
    try:
        with file_lock(path.with_suffix(".lock"), timeout=10.0):
            atomic_write_json(path, payload)
    except Exception:
        atomic_write_json(path, payload)
    return StoredLedgerRecord(record=stored.record, extra=merged)


def advance_ledger_record(
    stored: StoredLedgerRecord,
    event: str,
    *,
    note: str | None = None,
    extra: dict[str, Any] | None = None,
    at: str | None = None,
) -> StoredLedgerRecord:
    """Advance one record through the core state machine and persist it."""
    from sase.core.agent_auto_restart_facade import advance_auto_restart_ledger

    advanced = advance_auto_restart_ledger(
        stored.record, event, at=at or timestamp_for()
    )
    merged = dict(stored.extra)
    if extra:
        for key in _EXTRA_KEYS:
            if key in extra:
                merged[key] = extra[key]
    if note is not None:
        merged["python_last_note"] = {"event": event, "note": note}
    return store_ledger_record(StoredLedgerRecord(record=advanced, extra=merged))


def take_over_ledger_claim(
    stored: StoredLedgerRecord, *, at: str | None = None
) -> StoredLedgerRecord:
    """Assign a stale claimed/deferred row to this healer process."""
    if stored.record.state == "deferred":
        stored = advance_ledger_record(stored, "reclaim", at=at)
    elif stored.record.state != "claimed":
        return stored

    from sase.core.process_identity import process_identity_token

    pid = os.getpid()
    try:
        identity = process_identity_token(pid)
    except Exception:
        identity = None
    extra = dict(stored.extra)
    extra["python_claimer_pid"] = pid
    extra["python_claimer_identity"] = identity
    return store_ledger_record(StoredLedgerRecord(record=stored.record, extra=extra))


def claimer_is_live(stored: StoredLedgerRecord) -> bool:
    """Return whether the claiming process is still alive (PID-reuse safe).

    A pid that no longer exists is definitively dead, even though
    :func:`process_identity_matches` stays fail-open for unreadable pids
    (legacy behavior). A live pid still needs its identity token to match,
    so PID reuse never reads as the original claimer.
    """
    from sase.core.process_identity import process_identity_matches

    pid = stored.extra.get("python_claimer_pid")
    identity = stored.extra.get("python_claimer_identity")
    if not isinstance(pid, int) or pid <= 0:
        return False
    if pid == os.getpid():
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        pass
    except OSError:
        return False
    try:
        return bool(process_identity_matches(pid, identity))
    except Exception:
        return False


def iter_ledger_records() -> list[StoredLedgerRecord]:
    """Load every ledger record, newest claim first; corrupt rows are skipped."""
    directory = _ledger_dir()
    try:
        paths = sorted(
            directory.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True
        )
    except OSError:
        return []
    records: list[StoredLedgerRecord] = []
    for path in paths:
        if path.suffix != ".json" or path.name.endswith(".lock"):
            continue
        stored = load_ledger_record(path.stem)
        if stored is not None:
            records.append(stored)
    return records


def list_doorbells() -> list[dict[str, Any]]:
    """List unclaimed doorbell payloads, oldest first."""
    import json

    directory = auto_restart_root() / DOORBELL_DIRNAME
    try:
        paths = sorted(directory.glob("*.json"), key=lambda p: p.stat().st_mtime)
    except OSError:
        return []
    payloads: list[dict[str, Any]] = []
    for path in paths:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(payload, dict):
            payloads.append({"doorbell_path": str(path), **payload})
    return payloads


def delete_doorbell(path: str | Path) -> None:
    """Remove a doorbell once a ledger record owns the failure."""
    try:
        Path(path).unlink(missing_ok=True)
    except OSError:
        pass


def delete_doorbells_for(artifacts_dir: str | Path) -> None:
    """Remove every doorbell naming *artifacts_dir*.

    Called once a ledger record owns the failure (at claim) and when the
    target is skipped or declined, so the job's ``actionable`` turns false
    after one healer pass over a handled doorbell.
    """
    wanted = str(artifacts_dir)
    try:
        doorbells = list_doorbells()
    except Exception:
        return
    for doorbell in doorbells:
        try:
            if str(doorbell.get("artifacts_dir")) == wanted:
                delete_doorbell(str(doorbell.get("doorbell_path", "")))
        except Exception:
            continue


_records_cache: dict[str, Any] = {"dir": None, "mtime_ns": None, "records": []}


def iter_ledger_records_cached() -> list[StoredLedgerRecord]:
    """Load every ledger record, reusing the last read while quiet.

    Idle job ticks must stay at a handful of ``stat()`` calls: the ledger
    directory's mtime gates the parse, so an unchanged ledger costs one
    ``stat()`` instead of one read per record. Callers that mutate the
    ledger must go through this module's writers (which change the
    directory mtime) or out-of-band mutation (tests use
    :func:`_clear_ledger_records_cache`).
    """
    directory = _ledger_dir()
    try:
        mtime_ns: int | None = directory.stat().st_mtime_ns
    except OSError:
        mtime_ns = None
    key = str(directory)
    if _records_cache.get("dir") == key and _records_cache.get("mtime_ns") == mtime_ns:
        return list(_records_cache["records"])
    records = iter_ledger_records()
    _records_cache.update({"dir": key, "mtime_ns": mtime_ns, "records": records})
    return list(records)


def _clear_ledger_records_cache() -> None:
    """Forget the cached ledger read (tests, or out-of-band mutation)."""
    _records_cache.update({"dir": None, "mtime_ns": None, "records": []})


__all__ = [
    "StoredLedgerRecord",
    "advance_ledger_record",
    "auto_restart_root",
    "claim_ledger_record",
    "claimer_is_live",
    "delete_doorbell",
    "delete_doorbells_for",
    "iter_ledger_records",
    "iter_ledger_records_cached",
    "ledger_key",
    "list_doorbells",
    "load_ledger_record",
    "store_ledger_record",
]

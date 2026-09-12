"""Launch-admission journal for ordinary continuation successor reservation.

Lock order is documented on :mod:`sase.monitor.delivery`. This module never
waits on spawn, provider invocation, or child acknowledgment while holding
the admission lock.
"""

from __future__ import annotations

from collections.abc import Mapping
import fcntl
import hashlib
import json
from pathlib import Path
from typing import Any

from sase.agent.launch_admission_store import (
    ADMISSION_DIRNAME,
    LOCK_FILENAME,
    append_journal,
    next_journal_seq,
    write_unit_receipt,
)
from sase.core.agent_launch_facade import reconcile_admission_journal
from sase.core.agent_launch_wire import LAUNCH_ADMISSION_JOURNAL_SCHEMA_VERSION
from sase.memory.locks import locked_file
from sase.monitor.delivery import DELIVERY_LOCK_TIMEOUT_SECONDS


def _continuation_admission_dir(artifacts_dir: str | Path) -> Path:
    """Return the continuation admission journal root."""

    return Path(artifacts_dir) / "continuation" / ADMISSION_DIRNAME


def _continuation_logical_id(key: Mapping[str, str]) -> str:
    """Return the stable admission logical id for a delivery key."""

    return f"{key['monitor_id']}/{key['result_id']}/{key['branch']}"


def journal_continuation_reservation(
    artifacts_dir: str | Path,
    *,
    key: Mapping[str, str],
    identity: str,
    fingerprint: str | None = None,
    extra: Mapping[str, Any] | None = None,
    phase: str = "reserved",
) -> dict[str, Any]:
    """Journal one reserved successor identity for *key*.

    Repeated calls discover the existing identity instead of allocating a
    second one. Identity is recorded at reservation time so a crash after
    spawn can find the receiver without launching another model turn.
    """

    root = _continuation_admission_dir(artifacts_dir)
    root.mkdir(parents=True, exist_ok=True)
    logical_id = _continuation_logical_id(key)
    digest = fingerprint or _reservation_fingerprint(key, identity, extra)
    with locked_file(
        root / LOCK_FILENAME,
        fcntl.LOCK_EX,
        timeout=DELIVERY_LOCK_TIMEOUT_SECONDS,
    ):
        states = reconcile_admission_journal(_read_journal_entries(root))
        existing = states.get(logical_id) or {}
        existing_identity = existing.get("identity")
        if isinstance(existing_identity, str) and existing_identity:
            if existing_identity != identity:
                raise ValueError(
                    f"delivery {logical_id} already reserved as "
                    f"{existing_identity}; cannot allocate {identity}"
                )
            identity = existing_identity
            existing_phase = str(existing.get("phase") or "")
            if existing_phase in {"dispatching", "launched", "reserved"}:
                return {
                    "logical_id": logical_id,
                    "identity": identity,
                    "phase": existing_phase,
                    "fingerprint": existing.get("fingerprint") or digest,
                }
        seq = next_journal_seq(root)
        payload: dict[str, Any] = {
            "schema_version": LAUNCH_ADMISSION_JOURNAL_SCHEMA_VERSION,
            "seq": seq,
            "logical_id": logical_id,
            "phase": phase,
            "fingerprint": digest,
            "identity": identity,
            "recorded_at_unix": _now(),
        }
        if extra:
            for field in (
                "workspace_reference",
                "dispatch_target",
                "operation_key",
                "locator",
                "receipt_state",
                "uncertain",
            ):
                value = extra.get(field)
                if value is not None:
                    payload[field] = value
            if extra.get("queue_weight") is not None:
                payload["queue_weight"] = extra["queue_weight"]
            if extra.get("queue_weight_explicit") is not None:
                payload["queue_weight_explicit"] = extra["queue_weight_explicit"]
        append_journal(root, payload)
        write_unit_receipt(
            root,
            logical_id=logical_id,
            fingerprint=digest,
            identity=identity,
            extra=extra,
        )
        return {
            "logical_id": logical_id,
            "identity": identity,
            "phase": phase,
            "fingerprint": digest,
        }


def _reservation_fingerprint(
    key: Mapping[str, str],
    identity: str,
    extra: Mapping[str, Any] | None,
) -> str:
    payload = {
        "key": dict(key),
        "identity": identity,
        "extra": dict(extra or {}),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _read_journal_entries(root: Path) -> list[dict[str, Any]]:
    from sase.agent.launch_admission_store import read_journal

    return read_journal(root)


def _now() -> float:
    import time

    return time.time()


__all__ = [
    "journal_continuation_reservation",
]

"""Durable delivery records for monitor continuation and host completion."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
import fcntl
import json
from pathlib import Path
from typing import Any

from sase.core.continuation_facade import validate_continuation_delivery_record
from sase.core.continuation_wire import CONTINUATION_WIRE_SCHEMA_VERSION
from sase.finalizers.declaration_store import write_json_atomic
from sase.memory.locks import locked_file

DELIVERY_DIRNAME = "delivery"
DELIVERY_LOCK_FILENAME = "delivery.lock"
HOST_COMPLETION_RECEIPT_FILENAME = "host_completion_receipt.json"


def delivery_dir(artifacts_dir: str | Path) -> Path:
    """Return the continuation delivery directory for *artifacts_dir*."""

    return Path(artifacts_dir) / "continuation" / DELIVERY_DIRNAME


def delivery_key(
    *,
    monitor_id: str,
    result_id: str,
    branch: str = "complete",
) -> dict[str, str]:
    """Return one delivery key."""

    return {
        "monitor_id": monitor_id,
        "result_id": result_id,
        "branch": branch,
    }


def load_delivery_record(
    artifacts_dir: str | Path,
    key: Mapping[str, str],
) -> dict[str, Any] | None:
    """Load one delivery record if it exists."""

    path = _record_path(artifacts_dir, key)
    if not path.is_file():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"delivery record at {path} is not an object")
    return validate_continuation_delivery_record(payload)


def persist_delivery_record(
    artifacts_dir: str | Path,
    record: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate and atomically persist one delivery record."""

    validated = validate_continuation_delivery_record(dict(record))
    root = delivery_dir(artifacts_dir)
    root.mkdir(parents=True, exist_ok=True)
    path = _record_path(artifacts_dir, validated["key"])
    with locked_file(root / DELIVERY_LOCK_FILENAME, fcntl.LOCK_EX):
        write_json_atomic(path, validated)
    return validated


def new_delivery_record(
    key: Mapping[str, str],
    *,
    selected_action: str,
    reserved_identity: str | None = None,
) -> dict[str, Any]:
    """Return a pending delivery record for *key*."""

    now = _now_iso()
    return {
        "schema_version": CONTINUATION_WIRE_SCHEMA_VERSION,
        "key": dict(key),
        "selected_action": selected_action,
        "reserved_identity": reserved_identity,
        "attempt_history": [
            {
                "attempt_id": "attempt-1",
                "status": "pending",
                "recorded_at": now,
                "detail": None,
            }
        ],
        "acknowledged_by": None,
        "disposition": "pending",
        "disposition_reason": None,
    }


def transition_delivery(
    record: Mapping[str, Any],
    disposition: str,
    *,
    acknowledged_by: str | None = None,
    reason: str | None = None,
    reserved_identity: str | None = None,
) -> dict[str, Any]:
    """Append one attempt and move *record* to *disposition*."""

    updated = dict(record)
    history = list(updated.get("attempt_history") or [])
    attempt_id = f"attempt-{len(history) + 1}"
    history.append(
        {
            "attempt_id": attempt_id,
            "status": disposition,
            "recorded_at": _now_iso(),
            "detail": reason,
        }
    )
    updated["attempt_history"] = history
    updated["disposition"] = disposition
    if acknowledged_by is not None:
        updated["acknowledged_by"] = acknowledged_by
    if reason is not None:
        updated["disposition_reason"] = reason
    if reserved_identity is not None:
        updated["reserved_identity"] = reserved_identity
    return validate_continuation_delivery_record(updated)


def load_host_completion_receipt(artifacts_dir: str | Path) -> dict[str, Any] | None:
    """Load the durable host-completion receipt if present."""

    path = Path(artifacts_dir) / HOST_COMPLETION_RECEIPT_FILENAME
    if not path.is_file():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else None


def persist_host_completion_receipt(
    artifacts_dir: str | Path,
    receipt: Mapping[str, Any],
) -> dict[str, Any]:
    """Persist a durable host-completion receipt."""

    payload = dict(receipt)
    path = Path(artifacts_dir) / HOST_COMPLETION_RECEIPT_FILENAME
    write_json_atomic(path, payload)
    return payload


def _record_path(artifacts_dir: str | Path, key: Mapping[str, Any]) -> Path:
    name = (
        f"{_safe(key['monitor_id'])}__{_safe(key['result_id'])}__"
        f"{_safe(key['branch'])}.json"
    )
    return delivery_dir(artifacts_dir) / name


def _safe(value: object) -> str:
    return "".join(
        ch if str(ch).isalnum() or ch in "._:-" else "_" for ch in str(value)
    )


def _now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


__all__ = [
    "DELIVERY_DIRNAME",
    "HOST_COMPLETION_RECEIPT_FILENAME",
    "delivery_dir",
    "delivery_key",
    "load_delivery_record",
    "load_host_completion_receipt",
    "new_delivery_record",
    "persist_delivery_record",
    "persist_host_completion_receipt",
    "transition_delivery",
]

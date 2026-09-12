"""Durable delivery records for monitor continuation and host completion.

Lock order (never invert; never wait on a process, provider, user, or child
acknowledgment while holding either lock):

1. ``continuation/delivery/delivery.lock``
2. ``continuation/launch_admission/lock``
"""

from __future__ import annotations

from collections.abc import Mapping
from contextlib import contextmanager
from datetime import UTC, datetime
import fcntl
import json
from pathlib import Path
from typing import Any
from collections.abc import Iterator

from sase.core.continuation_facade import (
    new_continuation_delivery_record,
    transition_continuation_delivery,
    validate_continuation_delivery_record,
)
from sase.core.continuation_wire import CONTINUATION_WIRE_SCHEMA_VERSION
from sase.finalizers.declaration_store import write_json_atomic
from sase.memory.locks import locked_file

DELIVERY_DIRNAME = "delivery"
DELIVERY_LOCK_FILENAME = "delivery.lock"
DELIVERY_LOCK_TIMEOUT_SECONDS = 5.0
HOST_COMPLETION_RECEIPT_FILENAME = "host_completion_receipt.json"
_DISCOVERABLE_DISPOSITIONS = frozenset({"dispatching", "acknowledged", "settled"})


def _delivery_dir(artifacts_dir: str | Path) -> Path:
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


def load_delivery_records(
    artifacts_dir: str | Path,
    *,
    monitor_id: str | None = None,
    result_id: str | None = None,
) -> list[dict[str, Any]]:
    """Load delivery records, optionally filtered by key fields."""

    root = _delivery_dir(artifacts_dir)
    if not root.is_dir():
        return []
    records: list[dict[str, Any]] = []
    for path in sorted(root.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        try:
            record = validate_continuation_delivery_record(payload)
        except Exception:
            continue
        key = record.get("key")
        if not isinstance(key, Mapping):
            continue
        if monitor_id is not None and key.get("monitor_id") != monitor_id:
            continue
        if result_id is not None and key.get("result_id") != result_id:
            continue
        records.append(record)
    return records


def persist_delivery_record(
    artifacts_dir: str | Path,
    record: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate and atomically persist one delivery record."""

    validated = validate_continuation_delivery_record(dict(record))
    root = _delivery_dir(artifacts_dir)
    root.mkdir(parents=True, exist_ok=True)
    path = _record_path(artifacts_dir, validated["key"])
    with _delivery_lock(root):
        write_json_atomic(path, validated)
    return validated


def new_delivery_record(
    key: Mapping[str, str],
    *,
    selected_action: str,
    reserved_identity: str | None = None,
) -> dict[str, Any]:
    """Return a pending delivery record for *key*."""

    return new_continuation_delivery_record(
        {
            "key": dict(key),
            "selected_action": selected_action,
            "reserved_identity": reserved_identity,
            "recorded_at": _now_iso(),
        }
    )


def transition_delivery(
    record: Mapping[str, Any],
    disposition: str,
    *,
    acknowledged_by: str | None = None,
    reason: str | None = None,
    reserved_identity: str | None = None,
    workspace_identity: str | None = None,
    workspace_degraded: bool = False,
    retryable_pre_dispatch_failure: bool = False,
) -> dict[str, Any]:
    """Apply one Rust-owned delivery transition to *record*."""

    return transition_continuation_delivery(
        {
            "schema_version": CONTINUATION_WIRE_SCHEMA_VERSION,
            "record": dict(record),
            "target": disposition,
            "reserved_identity": reserved_identity,
            "acknowledged_by": acknowledged_by,
            "reason": reason,
            "recorded_at": _now_iso(),
            "workspace_identity": workspace_identity,
            "workspace_degraded": workspace_degraded,
            "retryable_pre_dispatch_failure": retryable_pre_dispatch_failure,
        }
    )


def claim_dispatch_slot(
    artifacts_dir: str | Path,
    key: Mapping[str, str],
    *,
    selected_action: str,
    reserved_identity: str,
    workspace_identity: str | None = None,
    workspace_degraded: bool = False,
    after_reserve: Any | None = None,
    retryable_pre_dispatch_failure: bool = False,
) -> tuple[dict[str, Any], bool]:
    """Reserve *reserved_identity* and claim the spawn slot under one lock.

    Returns ``(record, claimed)``. ``claimed`` is true only for the caller
    that moved the record into ``dispatching`` from ``pending`` or
    ``reserved``. Concurrent callers discover the existing receiver.
    """

    root = _delivery_dir(artifacts_dir)
    root.mkdir(parents=True, exist_ok=True)
    with _delivery_lock(root):
        record = load_delivery_record(artifacts_dir, key) or new_delivery_record(
            key,
            selected_action=selected_action,
            reserved_identity=reserved_identity,
        )
        previous = str(record.get("disposition") or "")
        if (
            previous in _DISCOVERABLE_DISPOSITIONS
            and not (previous == "dispatching" and retryable_pre_dispatch_failure)
        ) or previous in {
            "cancelled",
            "nonlaunchable",
            "needs_attention",
        }:
            return record, False
        if previous == "dispatching" and retryable_pre_dispatch_failure:
            record = transition_delivery(
                record,
                "reserved",
                reason="retryable pre-dispatch recovery",
                reserved_identity=reserved_identity,
                workspace_identity=workspace_identity,
                workspace_degraded=workspace_degraded,
                retryable_pre_dispatch_failure=True,
            )
            write_json_atomic(_record_path(artifacts_dir, record["key"]), record)
        if previous == "pending":
            record = transition_delivery(
                record,
                "reserved",
                reserved_identity=reserved_identity,
                workspace_identity=workspace_identity,
                workspace_degraded=workspace_degraded,
            )
            write_json_atomic(_record_path(artifacts_dir, record["key"]), record)
            if after_reserve is not None:
                after_reserve()
        if str(record.get("disposition")) == "reserved":
            record = transition_delivery(
                record,
                "dispatching",
                reserved_identity=reserved_identity,
                workspace_identity=workspace_identity,
                workspace_degraded=workspace_degraded,
            )
            write_json_atomic(_record_path(artifacts_dir, record["key"]), record)
            return record, True
        return record, False


def adopt_host_completion_delivery(
    artifacts_dir: str | Path,
    key: Mapping[str, str],
    *,
    reserved_identity: str,
    workspace_identity: str | None = None,
    workspace_degraded: bool = False,
) -> dict[str, Any]:
    """Atomically reserve and acknowledge host-completion delivery.

    Holds the delivery store lock for the full pending → reserved →
    acknowledged transition so concurrent host-completion workers discover
    the same receiver instead of racing two writes. Does not wait on
    finalizers, providers, or child processes while the lock is held.
    """

    root = _delivery_dir(artifacts_dir)
    root.mkdir(parents=True, exist_ok=True)
    with _delivery_lock(root):
        record = load_delivery_record(artifacts_dir, key) or new_delivery_record(
            key,
            selected_action="complete",
            reserved_identity=reserved_identity,
        )
        previous = str(record.get("disposition") or "")
        if previous in {"acknowledged", "settled"}:
            return record
        if previous in {"cancelled", "nonlaunchable", "needs_attention"}:
            return record
        if previous == "pending":
            record = transition_delivery(
                record,
                "reserved",
                reserved_identity=reserved_identity,
                workspace_identity=workspace_identity,
                workspace_degraded=workspace_degraded,
            )
            write_json_atomic(_record_path(artifacts_dir, record["key"]), record)
        if str(record.get("disposition")) == "reserved":
            record = transition_delivery(
                record,
                "acknowledged",
                reserved_identity=reserved_identity,
                acknowledged_by=reserved_identity,
                workspace_identity=workspace_identity,
                workspace_degraded=workspace_degraded,
            )
            write_json_atomic(_record_path(artifacts_dir, record["key"]), record)
        return record


def apply_delivery_transition(
    artifacts_dir: str | Path,
    key: Mapping[str, str],
    disposition: str,
    *,
    selected_action: str,
    acknowledged_by: str | None = None,
    reason: str | None = None,
    reserved_identity: str | None = None,
    workspace_identity: str | None = None,
    workspace_degraded: bool = False,
    retryable_pre_dispatch_failure: bool = False,
) -> dict[str, Any]:
    """Load, transition, and persist *key* under the delivery store lock."""

    root = _delivery_dir(artifacts_dir)
    root.mkdir(parents=True, exist_ok=True)
    with _delivery_lock(root):
        record = load_delivery_record(artifacts_dir, key) or new_delivery_record(
            key,
            selected_action=selected_action,
            reserved_identity=reserved_identity,
        )
        updated = transition_delivery(
            record,
            disposition,
            acknowledged_by=acknowledged_by,
            reason=reason,
            reserved_identity=reserved_identity,
            workspace_identity=workspace_identity,
            workspace_degraded=workspace_degraded,
            retryable_pre_dispatch_failure=retryable_pre_dispatch_failure,
        )
        write_json_atomic(_record_path(artifacts_dir, updated["key"]), updated)
        return updated


@contextmanager
def delivery_store_lock(artifacts_dir: str | Path) -> Iterator[None]:
    """Hold the delivery store lock for small recovery-side transactions."""

    root = _delivery_dir(artifacts_dir)
    root.mkdir(parents=True, exist_ok=True)
    with _delivery_lock(root):
        yield


def update_delivery_workspace(
    artifacts_dir: str | Path,
    key: Mapping[str, str],
    *,
    workspace_identity: str | None,
    workspace_degraded: bool = False,
) -> dict[str, Any] | None:
    """Record which workspace the reserved receiver actually used."""

    root = _delivery_dir(artifacts_dir)
    if not root.is_dir():
        return None
    with _delivery_lock(root):
        record = load_delivery_record(artifacts_dir, key)
        if record is None:
            return None
        if workspace_identity:
            record["workspace_identity"] = workspace_identity
        if workspace_degraded:
            record["workspace_degraded"] = True
        validated = validate_continuation_delivery_record(record)
        write_json_atomic(_record_path(artifacts_dir, validated["key"]), validated)
        return validated


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
    return _delivery_dir(artifacts_dir) / name


def _safe(value: object) -> str:
    return "".join(
        ch if str(ch).isalnum() or ch in "._:-" else "_" for ch in str(value)
    )


def _now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _delivery_lock(root: Path) -> Any:
    return locked_file(
        root / DELIVERY_LOCK_FILENAME,
        fcntl.LOCK_EX,
        timeout=DELIVERY_LOCK_TIMEOUT_SECONDS,
    )


__all__ = [
    "DELIVERY_DIRNAME",
    "DELIVERY_LOCK_TIMEOUT_SECONDS",
    "HOST_COMPLETION_RECEIPT_FILENAME",
    "adopt_host_completion_delivery",
    "apply_delivery_transition",
    "claim_dispatch_slot",
    "delivery_key",
    "delivery_store_lock",
    "load_delivery_record",
    "load_delivery_records",
    "load_host_completion_receipt",
    "new_delivery_record",
    "persist_delivery_record",
    "persist_host_completion_receipt",
    "transition_delivery",
    "update_delivery_workspace",
]

"""Durable source-side fleet attention answer intent records."""

from __future__ import annotations

import copy
import fcntl
import json
import os
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from sase.core.paths import sase_home
from sase.core.state_write_guard import assert_test_state_write_isolated
from sase.memory.locks import locked_file

DISPATCH_ATTENTION_INTENT_SCHEMA_VERSION = 1
DISPATCH_ATTENTION_INTENT_FILENAME = "dispatch_attention_intents.json"


class _DispatchAttentionIntentStoreError(RuntimeError):
    """Raised when source dispatch attention intent state cannot be persisted."""


def _dispatch_attention_intent_store_path() -> Path:
    return sase_home() / "fleet" / DISPATCH_ATTENTION_INTENT_FILENAME


def upsert_dispatch_attention_intent(
    record: Mapping[str, Any],
    *,
    path: Path | None = None,
) -> dict[str, Any]:
    """Insert or replace one source dispatch attention intent record."""
    store_path = path or _dispatch_attention_intent_store_path()
    normalized = _normalize_record(record)
    key = _record_key(normalized)
    with locked_file(_lock_path(store_path), fcntl.LOCK_EX, timeout=2.0):
        payload = _read_payload(store_path)
        records = [item for item in payload["records"] if _record_key(item) != key]
        records.append(normalized)
        records.sort(key=_record_key)
        _write_payload(store_path, {"schema_version": 1, "records": records})
    return normalized


def update_dispatch_attention_intent(
    operation_key: Mapping[str, Any],
    *,
    status: str,
    receipt: Mapping[str, Any] | None = None,
    error: str | None = None,
    path: Path | None = None,
) -> dict[str, Any]:
    """Update one existing source dispatch attention intent record."""
    store_path = path or _dispatch_attention_intent_store_path()
    wanted = _operation_key(operation_key)
    with locked_file(_lock_path(store_path), fcntl.LOCK_EX, timeout=2.0):
        payload = _read_payload(store_path)
        records: list[dict[str, Any]] = []
        updated: dict[str, Any] | None = None
        for record in payload["records"]:
            if _record_key(record) != wanted:
                records.append(record)
                continue
            updated = copy.deepcopy(record)
            updated["status"] = status
            updated["updated_at_unix"] = time.time()
            if receipt is not None:
                updated["receipt"] = copy.deepcopy(dict(receipt))
            if error is not None:
                updated["error"] = error
            records.append(updated)
        if updated is None:
            raise _DispatchAttentionIntentStoreError(
                "dispatch attention intent record is missing"
            )
        records.sort(key=_record_key)
        _write_payload(store_path, {"schema_version": 1, "records": records})
    return updated


def load_dispatch_attention_intent(
    operation_key: Mapping[str, Any],
    *,
    path: Path | None = None,
) -> dict[str, Any] | None:
    """Return one attention intent record, if present."""
    store_path = path or _dispatch_attention_intent_store_path()
    wanted = _operation_key(operation_key)
    payload = _read_payload(store_path)
    for record in payload["records"]:
        if _record_key(record) == wanted:
            return copy.deepcopy(record)
    return None


def _normalize_record(record: Mapping[str, Any]) -> dict[str, Any]:
    payload = copy.deepcopy(dict(record))
    payload.setdefault("schema_version", DISPATCH_ATTENTION_INTENT_SCHEMA_VERSION)
    payload.setdefault("created_at_unix", time.time())
    payload.setdefault("updated_at_unix", payload["created_at_unix"])
    payload.setdefault("status", "unsent")
    _record_key(payload)
    return payload


def _read_payload(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {
            "schema_version": DISPATCH_ATTENTION_INTENT_SCHEMA_VERSION,
            "records": [],
        }
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise _DispatchAttentionIntentStoreError(
            "could not read dispatch attention intent store"
        ) from exc
    if not isinstance(payload, dict):
        raise _DispatchAttentionIntentStoreError(
            "dispatch attention intent store root must be an object"
        )
    if payload.get("schema_version") != DISPATCH_ATTENTION_INTENT_SCHEMA_VERSION:
        raise _DispatchAttentionIntentStoreError(
            "dispatch attention intent store schema_version is unsupported"
        )
    records = payload.get("records")
    if not isinstance(records, list):
        raise _DispatchAttentionIntentStoreError(
            "dispatch attention intent records must be a list"
        )
    return {
        "schema_version": DISPATCH_ATTENTION_INTENT_SCHEMA_VERSION,
        "records": [
            copy.deepcopy(dict(item)) for item in records if isinstance(item, Mapping)
        ],
    }


def _write_payload(path: Path, payload: Mapping[str, Any]) -> None:
    assert_test_state_write_isolated(path, category="dispatch attention intent")
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(dict(payload), indent=2, sort_keys=True)
    tmp_path = path.with_name(f".{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
    try:
        tmp_path.write_text(f"{text}\n", encoding="utf-8")
        os.chmod(tmp_path, 0o600)
        os.replace(tmp_path, path)
        os.chmod(path, 0o600)
    except OSError as exc:
        try:
            tmp_path.unlink()
        except OSError:
            pass
        raise _DispatchAttentionIntentStoreError(
            "could not write dispatch attention intent store"
        ) from exc


def _lock_path(path: Path) -> Path:
    return path.with_name(f"{path.name}.lock")


def _record_key(record: Mapping[str, Any]) -> str:
    key = record.get("operation_key")
    if not isinstance(key, Mapping):
        raise _DispatchAttentionIntentStoreError("operation_key must be an object")
    return _operation_key(key)


def _operation_key(key: Mapping[str, Any]) -> str:
    controller_id = key.get("controller_id")
    operation_id = key.get("operation_id")
    if not isinstance(controller_id, str) or not controller_id:
        raise _DispatchAttentionIntentStoreError(
            "operation_key.controller_id is required"
        )
    if not isinstance(operation_id, str) or not operation_id:
        raise _DispatchAttentionIntentStoreError(
            "operation_key.operation_id is required"
        )
    return f"{controller_id}\0{operation_id}"


__all__ = [
    "DISPATCH_ATTENTION_INTENT_FILENAME",
    "DISPATCH_ATTENTION_INTENT_SCHEMA_VERSION",
    "load_dispatch_attention_intent",
    "update_dispatch_attention_intent",
    "upsert_dispatch_attention_intent",
]

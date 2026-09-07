"""Durable viewer-local ledger for remote attention toast deduplication."""

from __future__ import annotations

import copy
import fcntl
import json
import os
import time
from collections.abc import Mapping, Sequence
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Any

from sase.core.paths import sase_home
from sase.core.rust import require_rust_binding
from sase.core.state_write_guard import assert_test_state_write_isolated
from sase.memory.locks import locked_file

ATTENTION_NOTICES_SCHEMA_VERSION = 1
ATTENTION_NOTICES_FILENAME = "attention_notices.json"
ATTENTION_NOTICES_LOCK_TIMEOUT_SECONDS = 2.0
ATTENTION_NOTICES_RETENTION_SECONDS = 7 * 24 * 60 * 60.0

_STORE_FIELDS = frozenset({"schema_version", "entries"})


class _AttentionNoticesStoreError(RuntimeError):
    """Raised when the local attention-notices ledger cannot be read or written."""

    def __init__(self, message: str, *, path: Path | str | None = None) -> None:
        self.path = None if path is None else str(path)
        super().__init__(message if self.path is None else f"{message} ({self.path})")


def decide_and_persist_attention_notices(
    current_entries: Sequence[Mapping[str, Any]],
    *,
    retention_window_seconds: float = ATTENTION_NOTICES_RETENTION_SECONDS,
    now_unix: float | None = None,
    path: Path | None = None,
) -> list[dict[str, Any]]:
    """Decide which pending entries deserve a fresh toast and persist the ledger.

    Announcing is keyed by request key plus revision, so a reconnect that
    re-delivers the same request announces nothing while a new revision (a
    superseded and re-asked request) announces exactly once. With no
    current entries and no existing ledger, this performs no write: an idle
    host with nothing followed touches no new state.
    """
    store_path = path or _attention_notices_store_path()
    if not current_entries and not store_path.is_file():
        return []
    now = time.time() if now_unix is None else now_unix
    with _store_lock(store_path):
        payload = _read_payload(store_path)
        decision = require_rust_binding("fleet_decide_attention_notices")(
            [dict(entry) for entry in current_entries],
            payload["entries"],
            retention_window_seconds,
            now,
        )
        if not isinstance(decision, Mapping):
            raise _AttentionNoticesStoreError(
                "fleet_decide_attention_notices returned a non-object result",
                path=store_path,
            )
        ledger = decision.get("ledger")
        if not isinstance(ledger, list):
            raise _AttentionNoticesStoreError(
                "fleet_decide_attention_notices ledger must be a list",
                path=store_path,
            )
        after = {
            "schema_version": ATTENTION_NOTICES_SCHEMA_VERSION,
            "entries": copy.deepcopy(ledger),
        }
        if after != payload:
            _write_payload_atomic(store_path, after)
    to_announce = decision.get("to_announce")
    if not isinstance(to_announce, list):
        return []
    return [dict(entry) for entry in to_announce]


def _attention_notices_store_path() -> Path:
    return sase_home() / "fleet" / ATTENTION_NOTICES_FILENAME


def _store_lock(path: Path) -> AbstractContextManager[None]:
    return locked_file(
        path.with_name(f"{path.name}.lock"),
        fcntl.LOCK_EX,
        timeout=ATTENTION_NOTICES_LOCK_TIMEOUT_SECONDS,
    )


def _read_payload(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"schema_version": ATTENTION_NOTICES_SCHEMA_VERSION, "entries": []}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise _AttentionNoticesStoreError(
            "could not read attention notices ledger", path=path
        ) from exc
    if not isinstance(payload, dict):
        raise _AttentionNoticesStoreError(
            "attention notices ledger root must be an object", path=path
        )
    actual = set(payload)
    if actual != _STORE_FIELDS:
        missing = sorted(_STORE_FIELDS - actual)
        extra = sorted(actual - _STORE_FIELDS)
        details = []
        if missing:
            details.append(f"missing {', '.join(missing)}")
        if extra:
            details.append(f"unknown {', '.join(extra)}")
        raise _AttentionNoticesStoreError(
            f"invalid attention notices ledger fields: {'; '.join(details)}",
            path=path,
        )
    if payload.get("schema_version") != ATTENTION_NOTICES_SCHEMA_VERSION:
        raise _AttentionNoticesStoreError(
            "unsupported attention notices ledger schema_version: "
            f"{payload.get('schema_version')!r}",
            path=path,
        )
    entries = payload.get("entries")
    if not isinstance(entries, list):
        raise _AttentionNoticesStoreError(
            "attention notices ledger entries must be a list", path=path
        )
    return {
        "schema_version": ATTENTION_NOTICES_SCHEMA_VERSION,
        "entries": copy.deepcopy(entries),
    }


def _write_payload_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    assert_test_state_write_isolated(path, category="fleet attention notices")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
    try:
        with tmp_path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
        _fsync_parent(path.parent)
    except OSError as exc:
        try:
            tmp_path.unlink()
        except OSError:
            pass
        raise _AttentionNoticesStoreError(
            "could not write attention notices ledger", path=path
        ) from exc


def _fsync_parent(path: Path) -> None:
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


__all__ = [
    "ATTENTION_NOTICES_FILENAME",
    "ATTENTION_NOTICES_RETENTION_SECONDS",
    "ATTENTION_NOTICES_SCHEMA_VERSION",
    "decide_and_persist_attention_notices",
]

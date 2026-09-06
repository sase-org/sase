"""Durable viewer-local follow records for remote fleet rows."""

from __future__ import annotations

import copy
import fcntl
import json
import os
import time
from collections.abc import Iterable, Mapping
from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from sase.core.paths import sase_home
from sase.core.rust import require_rust_binding
from sase.core.state_write_guard import assert_test_state_write_isolated
from sase.memory.locks import locked_file

FOLLOW_STORE_SCHEMA_VERSION = 1
FOLLOW_STORE_DIRNAME = "fleet"
FOLLOW_STORE_FILENAME = "follows.json"
FOLLOW_STORE_LOCK_TIMEOUT_SECONDS = 2.0

FollowCreatedBy = Literal["explicit", "dispatch"]
FollowState = Literal["pending", "active"]

_STORE_FIELDS = frozenset({"schema_version", "records", "tombstones"})


class FollowStoreError(RuntimeError):
    """Raised when the local follow store cannot be read or written."""

    def __init__(self, message: str, *, path: Path | str | None = None) -> None:
        self.path = None if path is None else str(path)
        super().__init__(message if self.path is None else f"{message} ({self.path})")


@dataclass(frozen=True)
class FollowStoreSnapshot:
    """Normalized follow-store state."""

    schema_version: int
    records: tuple[dict[str, Any], ...]
    tombstones: tuple[dict[str, Any], ...]
    path: str
    diagnostics: tuple[dict[str, Any], ...] = ()

    @property
    def active_records(self) -> tuple[dict[str, Any], ...]:
        return tuple(
            record for record in self.records if record.get("state") == "active"
        )

    @property
    def active_logical_keys(self) -> frozenset[str]:
        return frozenset(
            str(record["logical_key"])
            for record in self.active_records
            if isinstance(record.get("logical_key"), str)
        )


@dataclass(frozen=True)
class FollowStoreMutationOutcome:
    """Result of a follow-store mutation."""

    changed: bool
    snapshot: FollowStoreSnapshot
    diagnostics: tuple[dict[str, Any], ...] = ()


def follow_store_path() -> Path:
    """Return the viewer-local follow store path for the current SASE home."""
    return sase_home() / FOLLOW_STORE_DIRNAME / FOLLOW_STORE_FILENAME


def load_follow_snapshot(path: Path | None = None) -> FollowStoreSnapshot:
    """Load and normalize the follow store without mutating it."""
    store_path = path or follow_store_path()
    payload = _read_store_unlocked(store_path)
    reconciled = _reconcile(
        payload["records"],
        payload["tombstones"],
        promotions=(),
        activations=(),
        now_unix=time.time(),
        path=store_path,
    )
    return _snapshot_from_reconciled(reconciled, path=store_path)


def record_follow(
    logical_locator: Mapping[str, Any],
    *,
    created_by: FollowCreatedBy = "explicit",
    state: FollowState = "active",
    operation_key: Mapping[str, Any] | None = None,
    now_unix: float | None = None,
    path: Path | None = None,
) -> FollowStoreMutationOutcome:
    """Persist an explicit or dispatch-created follow record."""
    if created_by not in {"explicit", "dispatch"}:
        raise FollowStoreError(f"invalid follow created_by: {created_by!r}")
    if state not in {"pending", "active"}:
        raise FollowStoreError(f"invalid follow state: {state!r}")
    if created_by == "dispatch" and operation_key is None:
        raise FollowStoreError("dispatch follow requires an operation_key")
    store_path = path or follow_store_path()
    now = _now(now_unix)
    locator = _copy_mapping(logical_locator)
    logical_key = _logical_locator_key(locator, path=store_path)

    with _store_lock(store_path):
        payload = _read_store_unlocked(store_path)
        records = list(payload["records"])
        tombstones = list(payload["tombstones"])
        if created_by == "explicit":
            tombstones = [
                tombstone
                for tombstone in tombstones
                if tombstone.get("logical_key") != logical_key
            ]

        new_record = _follow_record(
            locator,
            logical_key=logical_key,
            created_by=created_by,
            state=state,
            operation_key=operation_key,
            now_unix=now,
        )
        records = _upsert_follow_record(records, new_record, path=store_path)
        reconciled = _reconcile(
            records,
            tombstones,
            promotions=(),
            activations=(),
            now_unix=now,
            path=store_path,
        )
        return _finish_mutation(store_path, payload, reconciled)


def prewrite_dispatch_follow(
    logical_locator: Mapping[str, Any],
    operation_key: Mapping[str, Any],
    *,
    now_unix: float | None = None,
    path: Path | None = None,
) -> FollowStoreMutationOutcome:
    """Prewrite a pending dispatch follow before launch submission."""
    return record_follow(
        logical_locator,
        created_by="dispatch",
        state="pending",
        operation_key=operation_key,
        now_unix=now_unix,
        path=path,
    )


def activate_dispatch_follow(
    logical_locator: Mapping[str, Any],
    *,
    operation_key: Mapping[str, Any] | None = None,
    activated_at_unix: float | None = None,
    path: Path | None = None,
) -> FollowStoreMutationOutcome:
    """Activate a pending dispatch follow after receipt binding."""
    store_path = path or follow_store_path()
    now = _now(activated_at_unix)
    activation = {
        "schema_version": FOLLOW_STORE_SCHEMA_VERSION,
        "logical_locator": _copy_mapping(logical_locator),
        "operation_key": None
        if operation_key is None
        else _copy_mapping(operation_key),
        "activated_at_unix": now,
    }
    with _store_lock(store_path):
        payload = _read_store_unlocked(store_path)
        reconciled = _reconcile(
            payload["records"],
            payload["tombstones"],
            promotions=(),
            activations=(activation,),
            now_unix=now,
            path=store_path,
        )
        return _finish_mutation(store_path, payload, reconciled)


def unfollow(
    logical_locator: Mapping[str, Any],
    *,
    unfollowed_at_unix: float | None = None,
    path: Path | None = None,
) -> FollowStoreMutationOutcome:
    """Remove local follow records and add an explicit unfollow tombstone."""
    store_path = path or follow_store_path()
    now = _now(unfollowed_at_unix)
    locator = _copy_mapping(logical_locator)
    logical_key = _logical_locator_key(locator, path=store_path)
    tombstone = {
        "schema_version": FOLLOW_STORE_SCHEMA_VERSION,
        "logical_locator": locator,
        "logical_key": logical_key,
        "unfollowed_at_unix": now,
    }
    with _store_lock(store_path):
        payload = _read_store_unlocked(store_path)
        records = [
            record
            for record in payload["records"]
            if record.get("logical_key") != logical_key
        ]
        tombstones = [
            existing
            for existing in payload["tombstones"]
            if existing.get("logical_key") != logical_key
        ]
        tombstones.append(tombstone)
        reconciled = _reconcile(
            records,
            tombstones,
            promotions=(),
            activations=(),
            now_unix=now,
            path=store_path,
        )
        return _finish_mutation(store_path, payload, reconciled)


def promote_family_follow(
    singleton_locator: Mapping[str, Any],
    family_locator: Mapping[str, Any],
    *,
    now_unix: float | None = None,
    path: Path | None = None,
) -> FollowStoreMutationOutcome:
    """Promote a singleton follow to the durable family identity."""
    store_path = path or follow_store_path()
    now = _now(now_unix)
    promotion = {
        "schema_version": FOLLOW_STORE_SCHEMA_VERSION,
        "from": _copy_mapping(singleton_locator),
        "to": _copy_mapping(family_locator),
    }
    with _store_lock(store_path):
        payload = _read_store_unlocked(store_path)
        reconciled = _reconcile(
            payload["records"],
            payload["tombstones"],
            promotions=(promotion,),
            activations=(),
            now_unix=now,
            path=store_path,
        )
        return _finish_mutation(store_path, payload, reconciled)


def reconcile_follow_store(
    *,
    promotions: Iterable[Mapping[str, Any]] = (),
    activations: Iterable[Mapping[str, Any]] = (),
    now_unix: float | None = None,
    path: Path | None = None,
) -> FollowStoreMutationOutcome:
    """Normalize persisted state after remote reconciliation."""
    store_path = path or follow_store_path()
    now = _now(now_unix)
    with _store_lock(store_path):
        payload = _read_store_unlocked(store_path)
        reconciled = _reconcile(
            payload["records"],
            payload["tombstones"],
            promotions=tuple(copy.deepcopy(tuple(promotions))),
            activations=tuple(copy.deepcopy(tuple(activations))),
            now_unix=now,
            path=store_path,
        )
        return _finish_mutation(store_path, payload, reconciled)


def is_followed(
    snapshot: FollowStoreSnapshot,
    logical_locator: Mapping[str, Any],
) -> bool:
    """Return whether *logical_locator* is actively followed in *snapshot*."""
    logical_key = _logical_locator_key(logical_locator, path=snapshot.path)
    return logical_key in snapshot.active_logical_keys


def _store_lock(path: Path) -> AbstractContextManager[None]:
    return locked_file(
        path.with_name(f"{path.name}.lock"),
        fcntl.LOCK_EX,
        timeout=FOLLOW_STORE_LOCK_TIMEOUT_SECONDS,
    )


def _read_store_unlocked(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {
            "schema_version": FOLLOW_STORE_SCHEMA_VERSION,
            "records": [],
            "tombstones": [],
        }
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FollowStoreError("could not read follow store JSON", path=path) from exc
    if not isinstance(payload, dict):
        raise FollowStoreError("follow store root must be an object", path=path)
    actual = set(payload)
    if actual != _STORE_FIELDS:
        missing = sorted(_STORE_FIELDS - actual)
        extra = sorted(actual - _STORE_FIELDS)
        details = []
        if missing:
            details.append(f"missing {', '.join(missing)}")
        if extra:
            details.append(f"unknown {', '.join(extra)}")
        raise FollowStoreError(
            f"invalid follow store fields: {'; '.join(details)}", path=path
        )
    if payload.get("schema_version") != FOLLOW_STORE_SCHEMA_VERSION:
        raise FollowStoreError(
            f"unsupported follow store schema_version: {payload.get('schema_version')!r}",
            path=path,
        )
    records = payload.get("records")
    tombstones = payload.get("tombstones")
    if not isinstance(records, list) or not isinstance(tombstones, list):
        raise FollowStoreError(
            "follow store records and tombstones must be lists", path=path
        )
    return {
        "schema_version": FOLLOW_STORE_SCHEMA_VERSION,
        "records": copy.deepcopy(records),
        "tombstones": copy.deepcopy(tombstones),
    }


def _finish_mutation(
    path: Path,
    before: Mapping[str, Any],
    reconciled: Mapping[str, Any],
) -> FollowStoreMutationOutcome:
    snapshot = _snapshot_from_reconciled(reconciled, path=path)
    after = _payload_from_snapshot(snapshot)
    changed = after != {
        "schema_version": FOLLOW_STORE_SCHEMA_VERSION,
        "records": before["records"],
        "tombstones": before["tombstones"],
    }
    if changed:
        _write_store_atomic(path, after)
    return FollowStoreMutationOutcome(
        changed=changed,
        snapshot=snapshot,
        diagnostics=snapshot.diagnostics,
    )


def _write_store_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    assert_test_state_write_isolated(path, category="fleet follow-store")
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
        raise FollowStoreError("could not write follow store", path=path) from exc


def _fsync_parent(path: Path) -> None:
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _payload_from_snapshot(snapshot: FollowStoreSnapshot) -> dict[str, Any]:
    return {
        "schema_version": FOLLOW_STORE_SCHEMA_VERSION,
        "records": copy.deepcopy(list(snapshot.records)),
        "tombstones": copy.deepcopy(list(snapshot.tombstones)),
    }


def _snapshot_from_reconciled(
    payload: Mapping[str, Any],
    *,
    path: Path,
) -> FollowStoreSnapshot:
    records = payload.get("records")
    tombstones = payload.get("tombstones")
    diagnostics = payload.get("diagnostics", ())
    if not isinstance(records, list) or not isinstance(tombstones, list):
        raise FollowStoreError("reconciled follow store is missing records", path=path)
    if not isinstance(diagnostics, list):
        raise FollowStoreError(
            "reconciled follow diagnostics must be a list", path=path
        )
    return FollowStoreSnapshot(
        schema_version=FOLLOW_STORE_SCHEMA_VERSION,
        records=tuple(copy.deepcopy(records)),
        tombstones=tuple(copy.deepcopy(tombstones)),
        path=str(path),
        diagnostics=tuple(copy.deepcopy(diagnostics)),
    )


def _reconcile(
    records: Iterable[Mapping[str, Any]],
    tombstones: Iterable[Mapping[str, Any]],
    *,
    promotions: Iterable[Mapping[str, Any]],
    activations: Iterable[Mapping[str, Any]],
    now_unix: float,
    path: Path | str,
) -> dict[str, Any]:
    payload = {
        "schema_version": FOLLOW_STORE_SCHEMA_VERSION,
        "records": list(copy.deepcopy(tuple(records))),
        "tombstones": list(copy.deepcopy(tuple(tombstones))),
        "promotions": list(copy.deepcopy(tuple(promotions))),
        "activations": list(copy.deepcopy(tuple(activations))),
        "now_unix": now_unix,
    }
    result = _call_binding("fleet_reconcile_follow_records", payload, path=path)
    if not isinstance(result, dict):
        raise FollowStoreError(
            "fleet_reconcile_follow_records returned non-object", path=path
        )
    return result


def _upsert_follow_record(
    records: list[dict[str, Any]],
    new_record: dict[str, Any],
    *,
    path: Path,
) -> list[dict[str, Any]]:
    new_key = _follow_record_key(new_record, path=path)
    out: list[dict[str, Any]] = []
    replaced = False
    for existing in records:
        if _follow_record_key(existing, path=path) != new_key:
            out.append(existing)
            continue
        candidate = _merge_follow_record(existing, new_record)
        out.append(candidate)
        replaced = True
    if not replaced:
        out.append(new_record)
    return out


def _merge_follow_record(
    existing: Mapping[str, Any],
    new_record: Mapping[str, Any],
) -> dict[str, Any]:
    candidate = copy.deepcopy(dict(new_record))
    created_at = existing.get("created_at_unix")
    if isinstance(created_at, (int, float)) and not isinstance(created_at, bool):
        candidate["created_at_unix"] = float(created_at)
    if (
        existing.get("logical_locator") == candidate.get("logical_locator")
        and existing.get("operation_key") == candidate.get("operation_key")
        and existing.get("state") == candidate.get("state")
    ):
        return copy.deepcopy(dict(existing))
    return candidate


def _follow_record(
    logical_locator: Mapping[str, Any],
    *,
    logical_key: str,
    created_by: FollowCreatedBy,
    state: FollowState,
    operation_key: Mapping[str, Any] | None,
    now_unix: float,
) -> dict[str, Any]:
    return {
        "schema_version": FOLLOW_STORE_SCHEMA_VERSION,
        "logical_locator": _copy_mapping(logical_locator),
        "logical_key": logical_key,
        "created_by": created_by,
        "state": state,
        "created_at_unix": now_unix,
        "updated_at_unix": now_unix,
        "activated_at_unix": now_unix if state == "active" else None,
        "operation_key": None
        if operation_key is None
        else _copy_mapping(operation_key),
    }


def _copy_mapping(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise FollowStoreError(f"expected mapping, got {type(value).__name__}")
    return copy.deepcopy(dict(value))


def _logical_locator_key(
    logical_locator: Mapping[str, Any],
    *,
    path: Path | str,
) -> str:
    result = _call_binding(
        "fleet_logical_locator_key", _copy_mapping(logical_locator), path=path
    )
    if not isinstance(result, str) or not result:
        raise FollowStoreError(
            "fleet_logical_locator_key returned invalid key", path=path
        )
    return result


def _follow_record_key(record: Mapping[str, Any], *, path: Path | str) -> str:
    result = _call_binding("fleet_follow_record_key", _copy_mapping(record), path=path)
    if not isinstance(result, str) or not result:
        raise FollowStoreError(
            "fleet_follow_record_key returned invalid key", path=path
        )
    return result


def _call_binding(name: str, *args: Any, path: Path | str) -> Any:
    try:
        return require_rust_binding(name)(*args)
    except FollowStoreError:
        raise
    except Exception as exc:
        raise FollowStoreError(str(exc) or f"{name} failed", path=path) from exc


def _now(value: float | None) -> float:
    if value is None:
        return time.time()
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise FollowStoreError(f"timestamp must be numeric: {value!r}")
    timestamp = float(value)
    if timestamp < 0:
        raise FollowStoreError(f"timestamp must be non-negative: {value!r}")
    return timestamp


__all__ = [
    "FOLLOW_STORE_FILENAME",
    "FOLLOW_STORE_SCHEMA_VERSION",
    "FollowStoreError",
    "FollowStoreMutationOutcome",
    "FollowStoreSnapshot",
    "activate_dispatch_follow",
    "follow_store_path",
    "is_followed",
    "load_follow_snapshot",
    "prewrite_dispatch_follow",
    "promote_family_follow",
    "reconcile_follow_store",
    "record_follow",
    "unfollow",
]

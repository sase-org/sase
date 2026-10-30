"""Storage, locking, and shared local helpers for staged handoffs."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
import dataclasses
from datetime import UTC, datetime
import fcntl
import json
import os
from pathlib import Path
import threading
from typing import Any, Literal, overload

from sase.agent.gate_intent import atomic_write_json
from sase.core.staged_handoff import (
    StagedHandoffContractError,
    validate_staged_handoff,
)
from sase.feature_flags import current_flags
from sase.feature_flags.registry import FeatureFlag
from sase.memory.locks import locked_file

STAGED_HANDOFF_FILENAME = ".sase_handoff_staged.json"
STAGED_HANDOFF_RECEIPT_FILENAME = ".sase_handoff_adopted.json"
STAGED_HANDOFF_RESPONSE_FILENAME = ".sase_handoff_response.json"
STAGING_RESERVATION_FILENAME = ".sase_handoff_staging.json"
HANDOFF_LOCK_FILENAME = ".sase_handoff.lock"
_HANDOFF_THREAD_LOCK = threading.Lock()


class StagedHandoffError(RuntimeError):
    """Raised when a staged handoff cannot be admitted, read, or written."""


@dataclasses.dataclass(frozen=True)
class HostStageIdentity:
    """Explicit originating invocation/step identity for host staging.

    ``step_type`` is one of ``agent``, ``bash``, or ``python``. Host
    preparation admission requires all three fields; agent steps additionally
    require completed-provider evidence on the admission itself.
    """

    workflow: str
    step: str
    step_type: str


@dataclasses.dataclass(frozen=True)
class HostStageAdmission:
    """Host-owned workflow completion admission for one stage."""

    identity: HostStageIdentity
    provider_evidence: str | None = None


def staged_handoffs_enabled() -> bool:
    """Return whether the ``staged_handoffs`` beta flag is on.

    The CLI is the deciding process and reads the inherited snapshot. The
    runner dispatches on durable artifacts, never this helper.
    """
    return bool(current_flags().enabled(FeatureFlag.staged_handoffs))


def _handoff_sync_hook(_point: str) -> None:
    """Test seam for lock-order and stage-versus-submit races."""


@contextmanager
def acquire_handoff_locks(root: Path) -> Iterator[None]:
    """Acquire the in-process mutex and handoff flock for *root*."""
    _handoff_sync_hook("before_handoff_lock")
    root.mkdir(parents=True, exist_ok=True)
    with _HANDOFF_THREAD_LOCK:
        with locked_file(root / HANDOFF_LOCK_FILENAME, fcntl.LOCK_EX):
            _handoff_sync_hook("holding_handoff_lock")
            yield


@contextmanager
def acquire_stage_write_locks(root: Path) -> Iterator[None]:
    """Hold handoff then declaration locks for a staging mutation."""
    from sase.finalizers.declaration import hold_finalizer_declaration_lock

    with acquire_handoff_locks(root):
        with hold_finalizer_declaration_lock(root):
            yield


def read_staged_handoff(artifacts_dir: str | None = None) -> dict[str, Any] | None:
    """Return the staged record, or ``None`` when the file is absent.

    Malformed existing state is a refusal, not absence.
    """
    root = artifacts_root(artifacts_dir)
    path = root / STAGED_HANDOFF_FILENAME
    if not path_exists(path):
        return None
    payload = read_json_object(path, label="staged handoff")
    try:
        return validate_staged_handoff(payload)
    except StagedHandoffContractError as exc:
        raise StagedHandoffError(
            f"malformed staged handoff {path.name}: {exc}"
        ) from exc


def write_staged_handoff_response(
    staged_id: str,
    response: str,
    *,
    artifacts_dir: str | None = None,
) -> Path:
    """Persist the ordinary provider response for the active staged handoff.

    Finalizer declaration recovery may replace the invocation result. Keeping
    the ordinary response under the staged ID lets the planner chat retain the
    model's actual final answer without confusing it with recovery output.
    """
    root = artifacts_root(artifacts_dir)
    with acquire_handoff_locks(root):
        record = read_staged_handoff(str(root))
        if record is None or record.get("staged_id") != staged_id:
            raise StagedHandoffError(
                "cannot persist provider response for a different staged handoff"
            )
        path = root / STAGED_HANDOFF_RESPONSE_FILENAME
        atomic_write_json(
            path,
            {
                "schema_version": 1,
                "staged_id": staged_id,
                "response": response,
            },
        )
        return path


def read_staged_handoff_response(
    staged_id: str,
    *,
    artifacts_dir: str | None = None,
) -> str | None:
    """Read the ordinary provider response only for its matching staged ID."""
    root = artifacts_root(artifacts_dir)
    path = root / STAGED_HANDOFF_RESPONSE_FILENAME
    if not path_exists(path):
        return None
    payload = read_json_object(path, label="staged handoff provider response")
    if payload.get("schema_version") != 1 or payload.get("staged_id") != staged_id:
        raise StagedHandoffError(
            f"malformed staged handoff provider response {path.name}: identity mismatch"
        )
    response = payload.get("response")
    if not isinstance(response, str):
        raise StagedHandoffError(
            f"malformed staged handoff provider response {path.name}: response is not text"
        )
    return response


def discard_staged_handoff(artifacts_dir: str | None = None) -> None:
    """Remove the staged record and any crash leftover reservation."""
    root = artifacts_root(artifacts_dir, required=False)
    if root is None:
        return
    with acquire_handoff_locks(root):
        for name in (
            STAGED_HANDOFF_FILENAME,
            STAGED_HANDOFF_RESPONSE_FILENAME,
            STAGING_RESERVATION_FILENAME,
        ):
            path = root / name
            try:
                path.unlink()
            except FileNotFoundError:
                continue


def release_staging_reservation(
    reservation_id: str,
    *,
    artifacts_dir: str | None = None,
) -> None:
    """Drop a reservation that did not become a staged record."""
    root = artifacts_root(artifacts_dir, required=False)
    if root is None:
        return
    with acquire_handoff_locks(root):
        _release_reservation_locked(root, reservation_id)


@overload
def artifacts_root(
    artifacts_dir: str | None, *, required: Literal[True] = True
) -> Path: ...


@overload
def artifacts_root(
    artifacts_dir: str | None, *, required: Literal[False]
) -> Path | None: ...


def artifacts_root(artifacts_dir: str | None, *, required: bool = True) -> Path | None:
    raw = artifacts_dir or os.environ.get("SASE_ARTIFACTS_DIR")
    if not raw:
        if required:
            raise StagedHandoffError("SASE_ARTIFACTS_DIR is unset")
        return None
    return Path(raw)


def path_exists(path: Path) -> bool:
    try:
        return path.exists()
    except OSError:
        return False


def read_json_object(path: Path, *, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise StagedHandoffError(f"malformed {label}: {exc}") from exc
    if not isinstance(payload, dict):
        raise StagedHandoffError(f"malformed {label}: not a JSON object")
    return payload


def reservation_matches(path: Path, reservation_id: str | None) -> bool:
    if not reservation_id:
        return False
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return False
    return isinstance(payload, dict) and payload.get("reservation_id") == reservation_id


def _release_reservation_locked(root: Path, reservation_id: str) -> None:
    path = root / STAGING_RESERVATION_FILENAME
    if reservation_matches(path, reservation_id) or not path_exists(path):
        try:
            path.unlink()
        except FileNotFoundError:
            return


def release_staging_reservation_locked(root: Path, reservation_id: str) -> None:
    """Release a reservation while the caller holds ``acquire_handoff_locks``."""
    _release_reservation_locked(root, reservation_id)


def now_rfc3339() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")

"""Storage, locking, and shared local helpers for staged handoffs."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import ExitStack, contextmanager
import dataclasses
from datetime import UTC, datetime
import fcntl
import json
import os
from pathlib import Path
import threading
from typing import Any, Literal, overload

from sase.core.atomic_json import write_json_marker_atomic
from sase.core.staged_handoff import (
    StagedHandoffContractError,
    validate_staged_handoff,
)
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


def _handoff_sync_hook(_point: str) -> None:
    """Test seam for lock-order and stage-versus-submit races."""


@contextmanager
def acquire_handoff_locks(root: Path, *, blocking: bool = True) -> Iterator[bool]:
    """Acquire the mutex and flock, or yield false for a busy nonblocking probe."""
    _handoff_sync_hook("before_handoff_lock")
    root.mkdir(parents=True, exist_ok=True)
    if not _HANDOFF_THREAD_LOCK.acquire(blocking=blocking):
        yield False
        return
    try:
        with ExitStack() as stack:
            try:
                stack.enter_context(
                    locked_file(
                        root / HANDOFF_LOCK_FILENAME,
                        fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB),
                    )
                )
            except BlockingIOError:
                yield False
                return
            _handoff_sync_hook("holding_handoff_lock")
            yield True
    finally:
        _HANDOFF_THREAD_LOCK.release()


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
    partial: bool = False,
) -> Path:
    """Persist the ordinary provider response for the active staged handoff.

    Finalizer declaration recovery may replace the invocation result. Keeping
    the ordinary response under the staged ID lets the planner chat retain the
    model's actual final answer without confusing it with recovery output.

    ``partial`` marks a best-effort reply persisted after a provider failure:
    the starter's last reply is incomplete and the follow-up prompt must say
    so. Ordinary success paths leave it ``False``.
    """
    root = artifacts_root(artifacts_dir)
    with acquire_handoff_locks(root):
        record = read_staged_handoff(str(root))
        if record is None or record.get("staged_id") != staged_id:
            raise StagedHandoffError(
                "cannot persist provider response for a different staged handoff"
            )
        path = root / STAGED_HANDOFF_RESPONSE_FILENAME
        payload: dict[str, Any] = {
            "schema_version": 1,
            "staged_id": staged_id,
            "response": response,
        }
        if partial:
            payload["partial"] = True
        write_json_marker_atomic(path, payload)
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


PROVIDER_FAILURE_FILENAME = ".sase_provider_failure.json"


def read_provider_failure_record(
    artifacts_dir: str | None = None,
) -> dict[str, Any] | None:
    """Return the provider-failure record, or ``None`` when absent.

    Malformed state is a refusal, not absence: a corrupt failure record must
    not silently become an adoptable reply.
    """
    root = artifacts_root(artifacts_dir)
    path = root / PROVIDER_FAILURE_FILENAME
    if not path_exists(path):
        return None
    return read_json_object(path, label="provider failure record")


def staged_response_is_partial(
    staged_id: str,
    *,
    artifacts_dir: str | None = None,
) -> bool:
    """Return whether the persisted staged response is marked partial."""
    root = artifacts_root(artifacts_dir)
    path = root / STAGED_HANDOFF_RESPONSE_FILENAME
    if not path_exists(path):
        return False
    payload = read_json_object(path, label="staged handoff provider response")
    if payload.get("schema_version") != 1 or payload.get("staged_id") != staged_id:
        raise StagedHandoffError(
            f"malformed staged handoff provider response {path.name}: identity mismatch"
        )
    return payload.get("partial") is True


def build_provider_failure_fallback_response(
    failure: Mapping[str, Any],
) -> str:
    """Synthesize an adoptable reply from a provider-failure record.

    The text cites the failure record and states the starter's last reply is
    incomplete, so any follow-up prompt carrying it says so.
    """
    provider = failure.get("provider")
    provider_label = provider if isinstance(provider, str) and provider else "unknown"
    recorded_at = failure.get("recorded_at")
    when = (
        recorded_at if isinstance(recorded_at, str) and recorded_at else "unknown time"
    )
    error = failure.get("error")
    error_text = (
        error if isinstance(error, str) and error.strip() else "(no error detail)"
    )
    return (
        "[Staged reply recovered from the provider failure record: "
        f"provider {provider_label!r} failed after staging (recorded at {when}). "
        "The starter's last reply is incomplete; continue from the staged "
        f"state, not from a complete answer. Provider error: {error_text}]"
    )


def read_staged_response_or_failure_fallback(
    staged_id: str,
    *,
    artifacts_dir: str | None = None,
) -> str | None:
    """Return the staged response, falling back to the failure record.

    Stages stranded before the partial-response persistence existed carry only
    ``.sase_provider_failure.json``. Synthesizing a marked fallback from that
    record makes them re-adoptable without inventing a complete reply.
    """
    response = read_staged_handoff_response(staged_id, artifacts_dir=artifacts_dir)
    if response is not None:
        return response
    failure = read_provider_failure_record(artifacts_dir)
    if failure is None:
        return None
    return build_provider_failure_fallback_response(failure)


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

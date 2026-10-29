"""Host-facing staged-handoff storage, reservation, and admission.

Lock order with the declaration channel is:

1. in-process handoff mutex
2. ``.sase_handoff.lock`` flock
3. the declaration lock (when admission must observe an accepted submission)

Staged records are not members of ``PENDING_HANDOFF_MARKERS``. Callers that
need staged state use the explicit helpers here.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import UTC, datetime
import fcntl
import json
import os
from pathlib import Path
import threading
from typing import Any, Literal, overload
import uuid

from sase.agent.gate_intent import atomic_write_json
from sase.agent.pending_handoff import PENDING_HANDOFF_MARKERS
from sase.core.staged_handoff import (
    STAGED_HANDOFF_WIRE_SCHEMA_VERSION,
    StagedHandoffContractError,
    evaluate_stage_admission,
    receipt_authorizes as rust_receipt_authorizes,
    validate_staged_handoff,
    validate_staged_handoff_receipt,
)
from sase.feature_flags import current_flags
from sase.feature_flags.registry import FeatureFlag
from sase.memory.locks import locked_file

STAGED_HANDOFF_FILENAME = ".sase_handoff_staged.json"
STAGED_HANDOFF_RECEIPT_FILENAME = ".sase_handoff_adopted.json"
STAGING_RESERVATION_FILENAME = ".sase_handoff_staging.json"
HANDOFF_LOCK_FILENAME = ".sase_handoff.lock"

_HANDOFF_THREAD_LOCK = threading.Lock()


class StagedHandoffError(RuntimeError):
    """Raised when a staged handoff cannot be admitted, read, or written."""


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
def _acquire_stage_write_locks(root: Path) -> Iterator[None]:
    """Hold handoff then declaration locks for a staging mutation."""
    from sase.finalizers.declaration import hold_finalizer_declaration_lock

    with acquire_handoff_locks(root):
        with hold_finalizer_declaration_lock(root):
            yield


def occupying_handoff_names(
    artifacts_dir: str,
    *,
    ignore_reservation_id: str | None = None,
) -> tuple[str, ...]:
    """Return occupying legacy markers, staged records, and reservations."""
    root = Path(artifacts_dir)
    found: list[str] = []
    for name in PENDING_HANDOFF_MARKERS:
        if _exists(root / name):
            found.append(name)
    if _exists(root / STAGED_HANDOFF_FILENAME):
        found.append(STAGED_HANDOFF_FILENAME)
    reservation_path = root / STAGING_RESERVATION_FILENAME
    if _exists(reservation_path) and not _reservation_matches(
        reservation_path, ignore_reservation_id
    ):
        found.append(STAGING_RESERVATION_FILENAME)
    return tuple(found)


def admit_stage(
    *,
    command: str,
    artifacts_dir: str,
    ignore_reservation_id: str | None = None,
) -> None:
    """Run Rust admission against host observations for *artifacts_dir*."""
    request = {
        "schema_version": STAGED_HANDOFF_WIRE_SCHEMA_VERSION,
        "command": command,
        "is_agent": bool(os.environ.get("SASE_AGENT")),
        "artifacts_dir_present": bool(artifacts_dir),
        "is_finalizer_owned": _finalizer_owned_turn_is_active(),
        "is_native_helper": _native_helper_is_active(),
        "occupying": list(
            occupying_handoff_names(
                artifacts_dir, ignore_reservation_id=ignore_reservation_id
            )
        ),
        "has_accepted_current_submission": _has_accepted_current_final_submission(
            artifacts_dir
        ),
    }
    try:
        evaluate_stage_admission(request)
    except StagedHandoffContractError as exc:
        raise StagedHandoffError(str(exc)) from exc


def read_staged_handoff(artifacts_dir: str | None = None) -> dict[str, Any] | None:
    """Return the staged record, or ``None`` when the file is absent.

    Malformed existing state is a refusal, not absence.
    """
    root = _artifacts_root(artifacts_dir)
    path = root / STAGED_HANDOFF_FILENAME
    if not _exists(path):
        return None
    payload = _read_json_object(path, label="staged handoff")
    try:
        return validate_staged_handoff(payload)
    except StagedHandoffContractError as exc:
        raise StagedHandoffError(
            f"malformed staged handoff {path.name}: {exc}"
        ) from exc


def write_staged_handoff(
    record: Mapping[str, Any],
    *,
    artifacts_dir: str | None = None,
    command: str = "turn-ending handoffs",
    reservation_id: str | None = None,
) -> Path:
    """Validate and atomically persist a staged-handoff record."""
    root = _artifacts_root(artifacts_dir)
    with _acquire_stage_write_locks(root):
        admit_stage(
            command=command,
            artifacts_dir=str(root),
            ignore_reservation_id=reservation_id,
        )
        try:
            normalized = validate_staged_handoff(dict(record))
        except StagedHandoffContractError as exc:
            raise StagedHandoffError(str(exc)) from exc
        path = root / STAGED_HANDOFF_FILENAME
        atomic_write_json(path, normalized)
        if reservation_id is not None:
            _release_reservation_locked(root, reservation_id)
        return path


def discard_staged_handoff(artifacts_dir: str | None = None) -> None:
    """Remove the staged record and any crash leftover reservation."""
    root = _artifacts_root(artifacts_dir, required=False)
    if root is None:
        return
    with acquire_handoff_locks(root):
        for name in (STAGED_HANDOFF_FILENAME, STAGING_RESERVATION_FILENAME):
            path = root / name
            try:
                path.unlink()
            except FileNotFoundError:
                continue


def acquire_staging_reservation(
    *,
    artifacts_dir: str | None = None,
    command: str = "turn-ending handoffs",
) -> str:
    """Reserve the one-handoff slot before proposal side effects.

    The reservation file is not a valid staged record. Release it on
    pre-stage failure; committing a record replaces it.
    """
    root = _artifacts_root(artifacts_dir)
    reservation_id = str(uuid.uuid4())
    with _acquire_stage_write_locks(root):
        admit_stage(command=command, artifacts_dir=str(root))
        payload = {
            "reservation_id": reservation_id,
            "created_at": _now_rfc3339(),
            "pid": os.getpid(),
        }
        atomic_write_json(root / STAGING_RESERVATION_FILENAME, payload)
    return reservation_id


def release_staging_reservation(
    reservation_id: str,
    *,
    artifacts_dir: str | None = None,
) -> None:
    """Drop a reservation that did not become a staged record."""
    root = _artifacts_root(artifacts_dir, required=False)
    if root is None:
        return
    with acquire_handoff_locks(root):
        _release_reservation_locked(root, reservation_id)


def read_adoption_receipt(
    artifacts_dir: str | None = None,
) -> dict[str, Any] | None:
    """Return the adoption receipt, or ``None`` when absent.

    Malformed existing state is a refusal, not absence.
    """
    root = _artifacts_root(artifacts_dir)
    path = root / STAGED_HANDOFF_RECEIPT_FILENAME
    if not _exists(path):
        return None
    payload = _read_json_object(path, label="staged handoff receipt")
    try:
        return validate_staged_handoff_receipt(payload)
    except StagedHandoffContractError as exc:
        raise StagedHandoffError(
            f"malformed staged handoff receipt {path.name}: {exc}"
        ) from exc


def write_adoption_receipt(
    receipt: Mapping[str, Any],
    *,
    artifacts_dir: str | None = None,
) -> Path:
    """Validate and persist an adoption receipt."""
    root = _artifacts_root(artifacts_dir)
    try:
        normalized = validate_staged_handoff_receipt(dict(receipt))
    except StagedHandoffContractError as exc:
        raise StagedHandoffError(str(exc)) from exc
    with acquire_handoff_locks(root):
        path = root / STAGED_HANDOFF_RECEIPT_FILENAME
        atomic_write_json(path, normalized)
        return path


def receipt_authorizes(receipt: Mapping[str, Any], staged_id: str) -> bool:
    """Return whether *receipt* authorizes adoption of *staged_id*."""
    try:
        return rust_receipt_authorizes(dict(receipt), staged_id)
    except StagedHandoffContractError as exc:
        raise StagedHandoffError(str(exc)) from exc


def build_plan_staged_record(
    *,
    plan_file: str,
    original_file: str,
    dirty_obligations_at_stage: list[str] | None = None,
    extra_payload: Mapping[str, Any] | None = None,
    staged_id: str | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    """Build a plan staged-handoff record from host observations."""
    payload: dict[str, Any] = {
        "plan_file": plan_file,
        "original_file": original_file,
    }
    if extra_payload:
        payload.update(dict(extra_payload))
    obligations = (
        list(dirty_obligations_at_stage)
        if dirty_obligations_at_stage is not None
        else _measure_dirty_obligations_at_stage()
    )
    return {
        "schema_version": STAGED_HANDOFF_WIRE_SCHEMA_VERSION,
        "staged_id": staged_id or str(uuid.uuid4()),
        "kind": "plan",
        "created_at": created_at or _now_rfc3339(),
        "payload": payload,
        "successor_workspace": "none",
        "carry_allowed": False,
        "dirty_obligations_at_stage": obligations,
    }


def _measure_dirty_obligations_at_stage(
    artifacts_dir: str | None = None,
) -> list[str]:
    """Read-only snapshot of this turn's dirty-obligation ids.

    The list is evidence for the flag period, not permission to omit later
    obligations. A measurement failure yields an empty list.
    """
    raw = artifacts_dir or os.environ.get("SASE_ARTIFACTS_DIR")
    if not raw:
        return []
    try:
        from sase.finalizers.declaration import load_latest_finalizer_context

        context = load_latest_finalizer_context(Path(raw))
    except Exception:
        return []
    return [
        item.obligation_id
        for item in context.obligations
        if getattr(item, "obligation_id", "")
    ]


def _has_accepted_current_final_submission(artifacts_dir: str | None = None) -> bool:
    """Return whether an accepted, current final submission exists.

    Clean turns with no declaration required still return ``False`` when no
    submission file is present, so they can stage.
    """
    raw = artifacts_dir or os.environ.get("SASE_ARTIFACTS_DIR")
    if not raw:
        return False
    root = Path(raw)
    from sase.finalizers.declaration import FINAL_SUBMISSION_FILENAME

    if not (root / FINAL_SUBMISSION_FILENAME).is_file():
        return False
    try:
        from sase.finalizers.declaration import (
            adjudicate_commit_deferrals,
            load_accepted_host_repositories,
            load_finalizer_plan,
            load_latest_finalizer_context,
            load_latest_finalizer_submission,
            normalize_submission_envelope,
            validate_provider_payloads,
        )
        from sase.core.finalizer_facade import validate_finalizer_submission

        plan = load_finalizer_plan(root)
        context = load_latest_finalizer_context(root)
        submission = load_latest_finalizer_submission(root)
        envelope = normalize_submission_envelope(submission["submission"])
        validate_finalizer_submission(plan, context, envelope)
        host_records = load_accepted_host_repositories(root)
        validate_provider_payloads(plan, context, envelope, host_records=host_records)
        adjudicate_commit_deferrals(
            plan,
            context,
            envelope,
            root=root,
            host_records=host_records,
        )
    except Exception:
        return False
    return True


@overload
def _artifacts_root(
    artifacts_dir: str | None, *, required: Literal[True] = True
) -> Path: ...


@overload
def _artifacts_root(
    artifacts_dir: str | None, *, required: Literal[False]
) -> Path | None: ...


def _artifacts_root(artifacts_dir: str | None, *, required: bool = True) -> Path | None:
    raw = artifacts_dir or os.environ.get("SASE_ARTIFACTS_DIR")
    if not raw:
        if required:
            raise StagedHandoffError("SASE_ARTIFACTS_DIR is unset")
        return None
    return Path(raw)


def _exists(path: Path) -> bool:
    try:
        return path.exists()
    except OSError:
        return False


def _read_json_object(path: Path, *, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise StagedHandoffError(f"malformed {label}: {exc}") from exc
    if not isinstance(payload, dict):
        raise StagedHandoffError(f"malformed {label}: not a JSON object")
    return payload


def _reservation_matches(path: Path, reservation_id: str | None) -> bool:
    if not reservation_id:
        return False
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return False
    return isinstance(payload, dict) and payload.get("reservation_id") == reservation_id


def _release_reservation_locked(root: Path, reservation_id: str) -> None:
    path = root / STAGING_RESERVATION_FILENAME
    if _reservation_matches(path, reservation_id) or not _exists(path):
        try:
            path.unlink()
        except FileNotFoundError:
            return


def _now_rfc3339() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _finalizer_owned_turn_is_active() -> bool:
    from sase.finalizers.owned_turn import finalizer_owned_turn_is_active

    return finalizer_owned_turn_is_active()


def _native_helper_is_active() -> bool:
    """Return whether a host-visible native-helper marker is set.

    Claude native helpers are also denied by the PreToolUse guard. This
    observation is the CLI-side counterpart for admission policy.
    """
    value = (os.environ.get("SASE_NATIVE_HELPER") or "").strip().lower()
    return value in {"1", "true", "yes", "on"}


__all__ = [
    "HANDOFF_LOCK_FILENAME",
    "STAGED_HANDOFF_FILENAME",
    "STAGED_HANDOFF_RECEIPT_FILENAME",
    "STAGING_RESERVATION_FILENAME",
    "StagedHandoffError",
    "acquire_handoff_locks",
    "acquire_staging_reservation",
    "admit_stage",
    "build_plan_staged_record",
    "discard_staged_handoff",
    "occupying_handoff_names",
    "read_adoption_receipt",
    "read_staged_handoff",
    "receipt_authorizes",
    "release_staging_reservation",
    "staged_handoffs_enabled",
    "write_adoption_receipt",
    "write_staged_handoff",
]

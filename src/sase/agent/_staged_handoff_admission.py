"""Staged-handoff admission and reservation operations."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
import json
import logging
import os
from pathlib import Path
import uuid
from typing import Any

from sase.core.atomic_json import write_json_marker_atomic
from sase.agent.pending_handoff import PENDING_HANDOFF_MARKERS
from sase.agent._staged_handoff_store import (
    STAGED_HANDOFF_FILENAME,
    STAGING_RESERVATION_FILENAME,
    HostStageAdmission,
    StagedHandoffError,
    acquire_stage_write_locks,
    artifacts_root,
    now_rfc3339,
    path_exists,
    release_staging_reservation_locked,
    reservation_matches,
)
from sase.core.process_identity import (
    process_identity_matches,
    process_identity_token,
)
from sase.core.staged_handoff import (
    STAGED_HANDOFF_WIRE_SCHEMA_VERSION,
    StagedHandoffContractError,
    evaluate_host_stage_admission as rust_evaluate_host_stage_admission,
    evaluate_stage_admission,
    validate_staged_handoff,
)

logger = logging.getLogger(__name__)

_STALE_STAGING_RESERVATION_PREFIX = ".sase_handoff_staging.stale-"


def occupying_handoff_names(
    artifacts_dir: str,
    *,
    ignore_reservation_id: str | None = None,
) -> tuple[str, ...]:
    """Return occupying legacy markers, staged records, and reservations.

    Dead-owner staging reservations are reclaimed here so ``admit_stage``,
    ``acquire_staging_reservation``, and ``write_pending_handoff_marker``
    share one observation. Callers must hold the handoff lock.
    """
    root = Path(artifacts_dir)
    found: list[str] = []
    for name in PENDING_HANDOFF_MARKERS:
        if path_exists(root / name):
            found.append(name)
    if path_exists(root / STAGED_HANDOFF_FILENAME):
        found.append(STAGED_HANDOFF_FILENAME)
    occupying_reservation = _occupying_staging_reservation_name(
        root, ignore_reservation_id=ignore_reservation_id
    )
    if occupying_reservation is not None:
        found.append(occupying_reservation)
    return tuple(found)


def _occupying_staging_reservation_name(
    root: Path,
    *,
    ignore_reservation_id: str | None,
) -> str | None:
    path = root / STAGING_RESERVATION_FILENAME
    if not path_exists(path):
        return None
    if reservation_matches(path, ignore_reservation_id):
        return None
    payload, unreadable = _read_staging_reservation(path)
    if unreadable or payload is None:
        return f"{STAGING_RESERVATION_FILENAME} (unreadable)"
    pid = _reservation_pid(payload)
    if pid is None:
        return f"{STAGING_RESERVATION_FILENAME} (no owner pid)"
    if not _reservation_owner_is_gone(pid, payload.get("process_identity")):
        return f"{STAGING_RESERVATION_FILENAME} (owner pid {pid}, alive)"
    if _reclaim_stale_staging_reservation(root, payload):
        return None
    return f"{STAGING_RESERVATION_FILENAME} (owner pid {pid}, not alive)"


def _read_staging_reservation(
    path: Path,
) -> tuple[dict[str, Any] | None, bool]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None, True
    if not isinstance(payload, dict):
        return None, True
    return payload, False


def _reservation_pid(payload: Mapping[str, Any]) -> int | None:
    raw = payload.get("pid")
    if isinstance(raw, bool) or raw is None:
        return None
    try:
        pid = int(raw)
    except (TypeError, ValueError):
        return None
    if pid <= 0:
        return None
    return pid


def _reservation_owner_is_gone(pid: int, recorded_identity: object) -> bool:
    if not _pid_exists(pid):
        return True
    return not process_identity_matches(pid, recorded_identity)


def _pid_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        # PermissionError and other probe failures cannot prove the owner
        # is gone, so the reservation keeps occupying.
        return True
    return True


def _reclaim_stale_staging_reservation(root: Path, payload: Mapping[str, Any]) -> bool:
    path = root / STAGING_RESERVATION_FILENAME
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    evidence = root / f"{_STALE_STAGING_RESERVATION_PREFIX}{stamp}.json"
    if path_exists(evidence):
        evidence = (
            root
            / f"{_STALE_STAGING_RESERVATION_PREFIX}{stamp}-{uuid.uuid4().hex[:8]}.json"
        )
    try:
        os.replace(path, evidence)
    except FileNotFoundError:
        return True
    except OSError:
        logger.warning(
            "could not reclaim stale staging reservation %s", path, exc_info=True
        )
        return False
    logger.warning(
        "reclaimed stale staging reservation pid=%s identity=%s as %s",
        payload.get("pid"),
        payload.get("process_identity"),
        evidence.name,
    )
    return True


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


def _admit_host_stage(
    *,
    command: str,
    artifacts_dir: str,
    admission: HostStageAdmission,
    ignore_reservation_id: str | None = None,
) -> None:
    """Run Rust host-preparation admission for a workflow completion stage.

    Unlike CLI admission, an accepted current submission is not a refusal:
    the host seam re-runs the ordinary finalizer controller with the staged
    handoff bound, so the declaration is refreshed rather than reused stale.
    """
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
        "host_workflow": admission.identity.workflow,
        "host_step": admission.identity.step,
        "host_step_type": admission.identity.step_type,
        "host_provider_evidence": admission.provider_evidence,
    }
    try:
        rust_evaluate_host_stage_admission(request)
    except StagedHandoffContractError as exc:
        raise StagedHandoffError(str(exc)) from exc


def write_staged_handoff(
    record: Mapping[str, Any],
    *,
    artifacts_dir: str | None = None,
    command: str = "turn-ending handoffs",
    reservation_id: str | None = None,
    host: HostStageAdmission | None = None,
) -> Path:
    """Validate and atomically persist a staged-handoff record.

    Pass *host* for host-owned workflow completion staging instead of CLI
    staging.
    """
    root = artifacts_root(artifacts_dir)
    with acquire_stage_write_locks(root):
        if host is None:
            admit_stage(
                command=command,
                artifacts_dir=str(root),
                ignore_reservation_id=reservation_id,
            )
        else:
            _admit_host_stage(
                command=command,
                artifacts_dir=str(root),
                admission=host,
                ignore_reservation_id=reservation_id,
            )
        try:
            normalized = validate_staged_handoff(dict(record))
        except StagedHandoffContractError as exc:
            raise StagedHandoffError(str(exc)) from exc
        path = root / STAGED_HANDOFF_FILENAME
        write_json_marker_atomic(path, normalized)
        if reservation_id is not None:
            release_staging_reservation_locked(root, reservation_id)
        return path


def acquire_staging_reservation(
    *,
    artifacts_dir: str | None = None,
    command: str = "turn-ending handoffs",
    host: HostStageAdmission | None = None,
) -> str:
    """Reserve the one-handoff slot before proposal side effects.

    The reservation file is not a valid staged record. Release it on
    pre-stage failure; committing a record replaces it. Pass *host* for
    host-owned workflow completion staging instead of CLI staging.
    """
    root = artifacts_root(artifacts_dir)
    reservation_id = str(uuid.uuid4())
    with acquire_stage_write_locks(root):
        if host is None:
            admit_stage(command=command, artifacts_dir=str(root))
        else:
            _admit_host_stage(
                command=command,
                artifacts_dir=str(root),
                admission=host,
            )
        pid = os.getpid()
        payload = {
            "reservation_id": reservation_id,
            "created_at": now_rfc3339(),
            "pid": pid,
            "process_identity": process_identity_token(pid),
        }
        write_json_marker_atomic(root / STAGING_RESERVATION_FILENAME, payload)
    return reservation_id


def _has_accepted_current_final_submission(artifacts_dir: str | None = None) -> bool:
    """Return whether an accepted, current final submission exists.

    Clean turns with no declaration required still return ``False`` when no
    submission file is present, so they can stage.
    """
    raw = artifacts_dir or os.environ.get("SASE_ARTIFACTS_DIR")
    if not raw:
        return False
    root = Path(raw)
    from sase.finalizers.declaration import (
        FINAL_SUBMISSION_FILENAME,
        load_accepted_current_final_submission,
    )

    if not (root / FINAL_SUBMISSION_FILENAME).is_file():
        return False
    return load_accepted_current_final_submission(root) is not None


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

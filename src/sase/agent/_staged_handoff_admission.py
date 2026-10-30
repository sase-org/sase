"""Staged-handoff admission and reservation operations."""

from __future__ import annotations

from collections.abc import Mapping
import os
from pathlib import Path
import uuid
from typing import Any

from sase.agent.gate_intent import atomic_write_json
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
from sase.core.staged_handoff import (
    STAGED_HANDOFF_WIRE_SCHEMA_VERSION,
    StagedHandoffContractError,
    evaluate_host_stage_admission as rust_evaluate_host_stage_admission,
    evaluate_stage_admission,
    validate_staged_handoff,
)


def occupying_handoff_names(
    artifacts_dir: str,
    *,
    ignore_reservation_id: str | None = None,
) -> tuple[str, ...]:
    """Return occupying legacy markers, staged records, and reservations."""
    root = Path(artifacts_dir)
    found: list[str] = []
    for name in PENDING_HANDOFF_MARKERS:
        if path_exists(root / name):
            found.append(name)
    if path_exists(root / STAGED_HANDOFF_FILENAME):
        found.append(STAGED_HANDOFF_FILENAME)
    reservation_path = root / STAGING_RESERVATION_FILENAME
    if path_exists(reservation_path) and not reservation_matches(
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
        atomic_write_json(path, normalized)
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
        payload = {
            "reservation_id": reservation_id,
            "created_at": now_rfc3339(),
            "pid": os.getpid(),
        }
        atomic_write_json(root / STAGING_RESERVATION_FILENAME, payload)
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

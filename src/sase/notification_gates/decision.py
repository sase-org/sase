"""Durable, fast acceptance of one gate decision, ahead of slow execution.

Approving a tale or epic (or any other gate) must make its decision visible
-- and its human-review notification dismissed -- without waiting on the
slow work execution may still need: option commands, plan archive
publication (git commit, verified push), or successor launch. This module
is the bounded, fast half of that split, used by every surface through
:func:`sase.notification_gates.executor.execute_gate_selection` (CLI, ACE,
mobile, Telegram, and ``%auto``, since they all answer through it) -- so
none of them has to opt in separately.

It durably records one receipt (``decision_receipt.json``) under its own
short, bounded per-gate lock (``.acceptance.lock``), distinct from both the
gate's big ``.response.lock`` (held for the full duration of option
commands and adapter side effects) and from ``response.json`` (the
execution-complete record slow work still produces, unchanged). A
resubmission with the exact same selection, input, and feedback replays the
original receipt instead of re-accepting. A resubmission that names a
different decision is rejected promptly -- before any option command,
archive, or launch work runs -- while the existing receipt's owner is live
or unknown. A current failure outcome or proven-dead owner makes the stale
receipt supersedable.

The Rust core (``sase_core_rs.decide_gate_decision_acceptance``) owns the
accept/replay/conflict policy and the receipt's identity fingerprint; this
module owns reading and writing the receipt file, resolving the fields that
feed the policy, and dismissing the notification. It performs no option
command, archive, or launch work itself.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from sase.core.gate_decision_facade import (
    claim_gate_decision_execution,
    decide_gate_decision_acceptance,
)
from sase.notification_gates.command_runner import (
    recorded_rejection,
    validate_json_instance,
)
from sase.notification_gates.dismissal import settle_gate_notification
from sase.notification_gates.durability import (
    atomic_write_json,
    file_lock,
    read_json_object,
)
from sase.notification_gates.execution_owner import (
    collect_gate_execution_facts,
    current_execution_owner,
)
from sase.notification_gates.executor_inputs import resolve_option_inputs
from sase.notification_gates.feedback_input import apply_feedback_input
from sase.notification_gates.failure_notifications import (
    dismiss_gate_execution_failed,
)
from sase.notification_gates.hashing import load_and_verify_bundle
from sase.notification_gates.input_bounds import check_input_bounds
from sase.notification_gates.journal import value_digest
from sase.notification_gates.journal import append_journal_event_once
from sase.notification_gates.journal import current_execution_stage
from sase.notification_gates.models import GateError
from sase.notification_gates.paths import (
    CANCELLATION_FILENAME,
    RESPONSE_FILENAME,
    assert_owned_bundle,
)
from sase.notification_gates.selection import (
    normalize_feedback,
    options_from_envelope,
    resolve_selection,
)

log = logging.getLogger(__name__)

#: Written beside ``response.json``: the durable, fast acceptance record.
#: Independent of whether execution (option commands, archive, launch) has
#: even started -- never mutated once written, except to replace an
#: identical concurrent writer's copy with its own (a harmless no-op).
DECISION_RECEIPT_FILENAME = "decision_receipt.json"

#: A bounded, separate lock from ``.response.lock``. Acceptance must never
#: wait behind a slow option command, archive publication, or successor
#: launch still holding that lock.
ACCEPTANCE_LOCK_FILENAME = ".acceptance.lock"
ACCEPTANCE_LOCK_TIMEOUT_SECONDS = 5.0

GATE_DECISION_WIRE_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class _GateDecisionAcceptance:
    """The durable receipt for one gate, plus whether this call minted it."""

    receipt: Mapping[str, Any]
    already_accepted: bool


def accept_gate_decision(
    bundle_path: Path,
    selected_option_ids: Sequence[str],
    input_data: object | None = None,
    *,
    feedback: str | None = None,
    source: str = "host",
    option_inputs: Mapping[str, object] | None = None,
) -> _GateDecisionAcceptance | None:
    """Durably accept one gate decision and dismiss its notification, fast.

    Returns ``None`` when the gate already has a published ``response.json``:
    execution has already finished, so there is nothing left to accept, and
    :func:`~sase.notification_gates.executor.execute_gate_selection`'s own
    idempotent short-circuit handles that case. Raises :class:`GateError`
    (code ``gate_cancelled``) if the gate was already cancelled, or (code
    ``gate_decision_conflict``) if a durable receipt already exists for a
    different selection, input, or feedback while its owner is live or
    unknown. A current failure outcome or proven-dead owner is instead
    superseded by the Rust policy.
    """
    bundle_path = assert_owned_bundle(bundle_path)
    response_path = bundle_path / RESPONSE_FILENAME
    cancellation_path = bundle_path / CANCELLATION_FILENAME
    receipt_path = bundle_path / DECISION_RECEIPT_FILENAME

    with file_lock(
        bundle_path / ACCEPTANCE_LOCK_FILENAME,
        timeout=ACCEPTANCE_LOCK_TIMEOUT_SECONDS,
    ):
        if response_path.exists():
            return None
        if cancellation_path.exists():
            raise GateError(
                "gate_cancelled",
                str(cancellation_path),
                "gate is already cancelled",
            )

        envelope, _adapter = load_and_verify_bundle(bundle_path)
        options = options_from_envelope(envelope)
        selected = resolve_selection(envelope, options, selected_option_ids)
        with recorded_rejection(bundle_path, selected[0].id, source):
            normalized_feedback = normalize_feedback(selected, feedback)
        with recorded_rejection(bundle_path, selected[0].id, source):
            resolved_inputs = resolve_option_inputs(selected, input_data, option_inputs)
        resolved_inputs = apply_feedback_input(
            selected, resolved_inputs, normalized_feedback
        )
        for option in selected:
            target = f"option {option.id} input"
            with recorded_rejection(bundle_path, option.id, source):
                check_input_bounds(resolved_inputs[option.id], target)
                validate_json_instance(
                    resolved_inputs[option.id], option.input_schema, target
                )

        request_hash = str(envelope["hashes"]["request"])
        input_identity = value_digest(
            {option.id: resolved_inputs[option.id] for option in selected}
        )
        feedback_identity = (
            value_digest(normalized_feedback)
            if normalized_feedback is not None
            else None
        )
        existing_receipt = (
            read_json_object(receipt_path) if receipt_path.exists() else None
        )

        request: dict[str, Any] = {
            "schema_version": GATE_DECISION_WIRE_SCHEMA_VERSION,
            "gate_id": str(envelope["request_id"]),
            "request_hash": request_hash,
            "selected_option_ids": [option.id for option in selected],
            "input_identity": input_identity,
            "acceptance_id": uuid4().hex,
            "source": source,
            "accepted_at_unix": time.time(),
        }
        if feedback_identity is not None:
            request["feedback_identity"] = feedback_identity
        request["execution_owner"] = current_execution_owner()
        if existing_receipt is not None:
            request["existing_receipt"] = existing_receipt
            request["execution_facts"] = collect_gate_execution_facts(
                bundle_path,
                existing_receipt,
                response_exists=False,
            )

        try:
            outcome = decide_gate_decision_acceptance(request)
        except ValueError as exc:
            raise _policy_gate_error(exc, str(envelope["request_id"])) from exc

        receipt = outcome["receipt"]
        already_accepted = outcome["status"] == "replayed"
        if not already_accepted:
            if response_path.exists():
                return None
            if cancellation_path.exists():
                raise GateError(
                    "gate_cancelled",
                    str(cancellation_path),
                    "gate is already cancelled",
                )
            if outcome["status"] == "superseded":
                _journal_decision_superseded(
                    bundle_path,
                    existing_receipt=existing_receipt,
                    replacement_receipt=receipt,
                    outcome=outcome,
                    execution_facts=request.get("execution_facts"),
                )
                atomic_write_json(receipt_path, receipt, exclusive=False)
                dismiss_gate_execution_failed(
                    bundle_path=bundle_path,
                    envelope=envelope,
                )
            else:
                try:
                    atomic_write_json(receipt_path, receipt, exclusive=True)
                except FileExistsError:
                    receipt = read_json_object(receipt_path)
                    already_accepted = True

        settle_gate_notification(
            envelope,
            {"selected_option_ids": [option.id for option in selected]},
            source=source,
        )
        _project_accepted_decision(bundle_path, envelope, receipt)
        _touch_gate_shell_refresh_pulse(envelope, str(envelope["request_id"]))

        return _GateDecisionAcceptance(
            receipt=receipt, already_accepted=already_accepted
        )


def claim_gate_decision_execution_receipt(
    bundle_path: Path,
    *,
    gate_id: str,
    request_hash: str,
    acceptance_id: str | None,
) -> Mapping[str, Any]:
    """Re-own the still-current receipt immediately before execution."""
    bundle_path = assert_owned_bundle(bundle_path)
    receipt_path = bundle_path / DECISION_RECEIPT_FILENAME
    with file_lock(
        bundle_path / ACCEPTANCE_LOCK_FILENAME,
        timeout=ACCEPTANCE_LOCK_TIMEOUT_SECONDS,
    ):
        if not receipt_path.exists():
            raise GateError(
                "gate_decision_conflict",
                str(gate_id),
                "gate decision receipt disappeared before execution",
            )
        receipt = read_json_object(receipt_path)
        request: dict[str, Any] = {
            "schema_version": GATE_DECISION_WIRE_SCHEMA_VERSION,
            "gate_id": gate_id,
            "request_hash": request_hash,
            "receipt": receipt,
            "execution_owner": current_execution_owner(),
        }
        if acceptance_id is not None:
            request["acceptance_id"] = acceptance_id
        try:
            outcome = claim_gate_decision_execution(request)
        except ValueError as exc:
            raise _policy_gate_error(exc, str(gate_id)) from exc
        claimed = outcome["receipt"]
        atomic_write_json(receipt_path, claimed, exclusive=False)
        return claimed


def _project_accepted_decision(
    bundle_path: Path,
    envelope: Mapping[str, Any],
    receipt: Mapping[str, Any],
) -> None:
    """Best-effort: project TALE/EPIC APPROVED from the new receipt."""
    try:
        from sase.notification_gates.approval_projection import (
            project_accepted_decision,
        )

        project_accepted_decision(bundle_path, envelope, receipt)
    except Exception:
        log.warning(
            "Failed to project accepted decision into status metadata",
            extra={"bundle_path": str(bundle_path)},
            exc_info=True,
        )


def _touch_gate_shell_refresh_pulse(envelope: Mapping[str, Any], gate_id: str) -> None:
    """Best-effort: nudge ACE's watcher for shell-backed gates only.

    Non-shell gates (task/flag/bead triage, plain launches) have no shell
    row to refresh. A failure here must never turn a durably accepted
    decision into a raised error.
    """
    if not isinstance(envelope.get("shell"), dict):
        return
    try:
        from sase.gate_shell.store import find_gate_shell_by_gate_id
        from sase.shells.settlement import (
            touch_agent_refresh_pulse,
            touch_shell_refresh_pulse,
        )

        record = find_gate_shell_by_gate_id(None, gate_id)
        if record is not None:
            # The exact agent-dir pulse gives ACE a row delta; the project
            # pulse stays for watchers that only see project-level changes.
            touch_agent_refresh_pulse(getattr(record, "artifacts_dir", None))
            touch_shell_refresh_pulse(record.project_name)
    except Exception:
        log.warning(
            "Failed to touch refresh pulse after gate decision acceptance",
            exc_info=True,
        )


def read_current_receipt(bundle_path: Path) -> dict[str, Any] | None:
    """Return the durable receipt for *bundle_path*'s gate, or ``None``."""
    receipt_path = bundle_path / DECISION_RECEIPT_FILENAME
    return read_json_object(receipt_path) if receipt_path.exists() else None


def receipt_acceptance_id(receipt: Mapping[str, Any] | None) -> str | None:
    """Return *receipt*'s acceptance id, or ``None`` for a legacy receipt."""
    if receipt is None:
        return None
    value = receipt.get("acceptance_id")
    return value if isinstance(value, str) else None


def _journal_decision_superseded(
    bundle_path: Path,
    *,
    existing_receipt: Mapping[str, Any] | None,
    replacement_receipt: Mapping[str, Any],
    outcome: Mapping[str, Any],
    execution_facts: object,
) -> None:
    if existing_receipt is None:
        return
    superseded_receipt = outcome.get("superseded_receipt")
    if not isinstance(superseded_receipt, Mapping):
        superseded_receipt = existing_receipt
    old_acceptance_id = receipt_acceptance_id(superseded_receipt)
    new_acceptance_id = receipt_acceptance_id(replacement_receipt)
    if old_acceptance_id is None:
        return
    request_hash = str(superseded_receipt.get("request_hash") or "")
    owner_liveness = outcome.get("owner_liveness")
    owner_liveness_text = owner_liveness if isinstance(owner_liveness, str) else None
    owner_lost = bool(outcome.get("owner_lost"))
    superseded_attempt_id = _superseded_attempt_id(
        bundle_path,
        superseded_receipt=superseded_receipt,
        execution_facts=execution_facts,
        owner_lost=owner_lost,
    )
    append_journal_event_once(
        bundle_path,
        event="decision_superseded",
        acceptance_id=old_acceptance_id,
        attempt_id=superseded_attempt_id,
        request_hash=request_hash,
        superseded_by_acceptance_id=new_acceptance_id,
        owner_lost=owner_lost,
        owner_liveness=owner_liveness_text,
    )
    if owner_lost:
        append_journal_event_once(
            bundle_path,
            event="owner_lost",
            acceptance_id=old_acceptance_id,
            attempt_id=superseded_attempt_id,
            request_hash=request_hash,
            code="execution_owner_lost",
            stage="command",
            message="gate execution owner appears to have stopped",
            superseded_by_acceptance_id=new_acceptance_id,
            owner_lost=True,
            owner_liveness=owner_liveness_text or "dead",
        )
    append_journal_event_once(
        bundle_path,
        event="attempt_superseded",
        acceptance_id=old_acceptance_id,
        attempt_id=superseded_attempt_id,
        request_hash=request_hash,
        superseded_by_acceptance_id=new_acceptance_id,
        owner_lost=owner_lost,
        owner_liveness=owner_liveness_text,
    )


def _superseded_attempt_id(
    bundle_path: Path,
    *,
    superseded_receipt: Mapping[str, Any],
    execution_facts: object,
    owner_lost: bool,
) -> str:
    if isinstance(execution_facts, Mapping):
        for key in ("current_failure", "post_response_failure"):
            failure = execution_facts.get(key)
            if isinstance(failure, Mapping):
                attempt_id = failure.get("attempt_id")
                if isinstance(attempt_id, str) and attempt_id:
                    return attempt_id
    _stage, attempt_id = current_execution_stage(bundle_path, superseded_receipt)
    if attempt_id:
        return attempt_id
    return "owner_lost" if owner_lost else ""


def _policy_gate_error(exc: ValueError, target: str) -> GateError:
    message = str(exc)
    code, separator, detail = message.partition(":")
    if separator and code:
        return GateError(code.strip(), target, detail.strip() or message)
    return GateError("gate_decision_conflict", target, message)


__all__ = [
    "ACCEPTANCE_LOCK_FILENAME",
    "DECISION_RECEIPT_FILENAME",
    "accept_gate_decision",
    "claim_gate_decision_execution_receipt",
    "read_current_receipt",
    "receipt_acceptance_id",
]

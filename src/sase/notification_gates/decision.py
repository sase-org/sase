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
archive, or launch work runs -- so competing or racing submissions cannot
both proceed, *unless* the existing receipt's own attempt already failed
partway (an incomplete ``journal.jsonl`` attempt): that case is a legitimate
change of mind after a failure, not a race, and supersedes the stale
receipt exactly as ``executor._begin_attempt`` already supersedes a stale
incomplete attempt for changed input or selection.

The Rust core (``sase_core_rs.decide_gate_decision_acceptance``) owns the
accept/replay/conflict policy and the receipt's identity fingerprint; this
module owns reading and writing the receipt file, resolving the fields that
feed the policy, and dismissing the notification. It performs no option
command, archive, or launch work itself.
"""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sase.core.gate_decision_facade import decide_gate_decision_acceptance
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
from sase.notification_gates.executor_inputs import resolve_option_inputs
from sase.notification_gates.feedback_input import apply_feedback_input
from sase.notification_gates.hashing import load_and_verify_bundle
from sase.notification_gates.input_bounds import check_input_bounds
from sase.notification_gates.journal import incomplete_attempt, value_digest
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
    different selection, input, or feedback *and* that receipt's own
    attempt has not failed partway -- a failed/incomplete attempt's receipt
    is instead superseded, matching the pre-existing rule for resubmitting
    changed input or selection over an incomplete AND-branch attempt.
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
            "source": source,
            "accepted_at_unix": time.time(),
        }
        if feedback_identity is not None:
            request["feedback_identity"] = feedback_identity
        execution_owner = os.environ.get("SASE_PROC_ID", "").strip()
        if execution_owner:
            request["execution_owner"] = execution_owner
        if existing_receipt is not None:
            request["existing_receipt"] = existing_receipt

        superseding = False
        try:
            outcome = decide_gate_decision_acceptance(request)
        except ValueError as exc:
            if existing_receipt is None or incomplete_attempt(bundle_path) is None:
                raise GateError(
                    "gate_decision_conflict", str(envelope["request_id"]), str(exc)
                ) from exc
            # The existing receipt's own attempt failed partway (or was
            # otherwise left incomplete) and nothing has durably succeeded
            # for this gate yet -- response.json does not exist, checked
            # above. A differing resubmission here legitimately supersedes
            # it, mirroring ``_begin_attempt``'s own supersede rule for a
            # changed selection or input over an incomplete attempt: the
            # newest submission wins and replaces the stale receipt.
            superseding = True
            fresh_request = {
                key: value
                for key, value in request.items()
                if key != "existing_receipt"
            }
            outcome = decide_gate_decision_acceptance(fresh_request)

        receipt = outcome["receipt"]
        already_accepted = outcome["status"] == "replayed"
        if not already_accepted:
            if superseding:
                atomic_write_json(receipt_path, receipt, exclusive=False)
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
        _touch_gate_shell_refresh_pulse(envelope, str(envelope["request_id"]))

        return _GateDecisionAcceptance(
            receipt=receipt, already_accepted=already_accepted
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
        from sase.shells.settlement import touch_shell_refresh_pulse

        record = find_gate_shell_by_gate_id(None, gate_id)
        if record is not None:
            touch_shell_refresh_pulse(record.project_name)
    except Exception:
        log.warning(
            "Failed to touch refresh pulse after gate decision acceptance",
            exc_info=True,
        )


__all__ = [
    "ACCEPTANCE_LOCK_FILENAME",
    "DECISION_RECEIPT_FILENAME",
    "accept_gate_decision",
]

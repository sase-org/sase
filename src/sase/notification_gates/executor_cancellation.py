"""Cancellation lifecycle handling for notification gates."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from sase.gate_shell.lifecycle import (
    DISPOSITION_ACCEPTED_OWNER_LOST,
    classify_gate_lifecycle,
    collect_gate_lifecycle_facts,
)
from sase.notification_gates.decision import (
    ACCEPTANCE_LOCK_FILENAME,
    DECISION_RECEIPT_FILENAME,
)
from sase.notification_gates.dismissal import settle_gate_notification
from sase.notification_gates.durability import (
    atomic_write_json,
    file_lock,
    read_json_object,
)
from sase.notification_gates.failure_notifications import dismiss_gate_execution_failed
from sase.notification_gates.failure_outcome import record_owner_lost_outcome
from sase.notification_gates.hashing import load_and_verify_bundle
from sase.notification_gates.models import GATE_RESPONSE_SCHEMA_VERSION, GateError
from sase.notification_gates.paths import (
    CANCELLATION_FILENAME,
    RESPONSE_FILENAME,
    assert_owned_bundle,
)


CANCEL_LOCK_TIMEOUT_SECONDS = 5.0
"""Maximum wait for decision acceptance to finish during cancellation."""


def cancel_gate(
    bundle_path: Path,
    *,
    reason: str = "requester_cancelled",
    source: str = "requester",
    lock_timeout_seconds: float | None = CANCEL_LOCK_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Persist a write-once cancellation if the lifecycle policy allows it."""
    bundle_path = assert_owned_bundle(bundle_path)
    with file_lock(
        bundle_path / ACCEPTANCE_LOCK_FILENAME, timeout=lock_timeout_seconds
    ):
        envelope, _adapter = load_and_verify_bundle(bundle_path)
        response_path = bundle_path / RESPONSE_FILENAME
        if response_path.exists():
            raise GateError(
                "already_answered", str(response_path), "gate already has a response"
            )
        if envelope.get("kind") == "sudo":
            _reject_cancel_during_sudo_attempt(bundle_path)
        path = bundle_path / CANCELLATION_FILENAME
        if path.exists():
            return read_json_object(path)
        receipt_path = bundle_path / DECISION_RECEIPT_FILENAME
        if receipt_path.exists():
            facts = collect_gate_lifecycle_facts(
                bundle_path, envelope, now=time.time(), deadline=None, grace_seconds=0.0
            )
            try:
                lifecycle = classify_gate_lifecycle(facts)
            except ValueError as exc:
                raise GateError(
                    "invalid_gate_decision_receipt", str(receipt_path), str(exc)
                ) from exc
            if not bool(lifecycle.get("can_cancel")):
                raise GateError(
                    "already_answered",
                    str(receipt_path),
                    "gate decision is already accepted",
                )
            if lifecycle.get("disposition") == DISPOSITION_ACCEPTED_OWNER_LOST:
                record_owner_lost_outcome(
                    bundle_path, receipt=facts.receipt, source=source
                )
        cancellation = {
            "schema_version": GATE_RESPONSE_SCHEMA_VERSION,
            "request_id": envelope["request_id"],
            "kind": envelope["kind"],
            "reason": reason,
            "source": source,
            "cancelled_at_unix": time.time(),
        }
        atomic_write_json(path, cancellation, exclusive=True)
        settle_gate_notification(envelope, {}, source=source, action="cancelled")
        dismiss_gate_execution_failed(bundle_path=bundle_path, envelope=envelope)
        return cancellation


def _reject_cancel_during_sudo_attempt(bundle_path: Path) -> None:
    try:
        from sase.sudo.execution import (
            execution_liveness,
            load_execution_state,
            live_execution_error,
        )

        state = load_execution_state(bundle_path)
    except GateError:
        raise
    except Exception:
        return
    if state is not None and execution_liveness(state).get("classification") != "dead":
        raise live_execution_error(state)


__all__ = ["CANCEL_LOCK_TIMEOUT_SECONDS", "cancel_gate"]

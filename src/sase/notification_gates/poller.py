"""Generic response polling independent of transport staleness."""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from sase.notification_gates.durability import read_json_object
from sase.notification_gates.failure_outcome import record_owner_lost_outcome_if_current
from sase.notification_gates.journal import (
    ExecutionFailureFacts,
    current_gate_execution_failure,
)
from sase.notification_gates.decision import read_current_receipt
from sase.notification_gates.executor import cancel_gate
from sase.notification_gates.hashing import load_and_verify_bundle
from sase.notification_gates.models import GateError
from sase.notification_gates.paths import (
    CANCELLATION_FILENAME,
    RESPONSE_FILENAME,
    assert_owned_bundle,
)

GatePollStatus = Literal["responded", "cancelled", "timed_out", "failed"]


@dataclass(frozen=True)
class GatePollResult:
    """Terminal observation made by the common gate poller."""

    status: GatePollStatus
    payload: dict[str, Any]
    selected_option_ids: tuple[str, ...] = ()
    feedback: str | None = None
    failure: dict[str, Any] | None = None


def poll_gate(bundle_path: Path) -> GatePollResult | None:
    """Return the current terminal state without waiting."""
    bundle_path = assert_owned_bundle(bundle_path)
    response_path = bundle_path / RESPONSE_FILENAME
    receipt = read_current_receipt(bundle_path)
    if response_path.exists():
        payload = read_json_object(response_path)
        selected_option_ids, feedback = _response_projection(payload)
        failure = current_gate_execution_failure(
            bundle_path, receipt, response_exists=True
        )
        if failure is not None:
            return _failed_result(failure, selected_option_ids, feedback)
        return GatePollResult(
            "responded",
            payload,
            selected_option_ids=selected_option_ids,
            feedback=feedback,
        )
    cancellation_path = bundle_path / CANCELLATION_FILENAME
    if cancellation_path.exists():
        payload = read_json_object(cancellation_path)
        status: GatePollStatus = (
            "timed_out" if payload.get("reason") == "timeout" else "cancelled"
        )
        return GatePollResult(status, payload)
    if receipt is not None:
        failure = current_gate_execution_failure(
            bundle_path, receipt, response_exists=False
        )
        if failure is not None:
            return _failed_result(failure)
        failure = _record_owner_lost_if_needed(bundle_path, receipt)
        if failure is not None:
            return _failed_result(failure)
    return None


def _response_projection(
    payload: Mapping[str, Any],
) -> tuple[tuple[str, ...], str | None]:
    raw_option_ids = payload.get("selected_option_ids", [])
    selected_option_ids = (
        tuple(raw_option_ids)
        if isinstance(raw_option_ids, list)
        and all(isinstance(option_id, str) for option_id in raw_option_ids)
        else ()
    )
    feedback = payload.get("feedback")
    return selected_option_ids, feedback if isinstance(feedback, str) else None


def _record_owner_lost_if_needed(
    bundle_path: Path, receipt: Mapping[str, Any]
) -> ExecutionFailureFacts | None:
    del receipt
    try:
        envelope, _adapter = load_and_verify_bundle(bundle_path)
    except Exception:
        return None
    return record_owner_lost_outcome_if_current(
        bundle_path,
        source="gate_poller",
        now=time.time(),
        deadline=_deadline(envelope),
        grace_seconds=0.0,
    )


def _deadline(envelope: Mapping[str, Any]) -> float | None:
    created = envelope.get("created_at_unix")
    timeout_seconds = envelope.get("gate_timeout_seconds")
    if isinstance(created, (int, float)) and isinstance(timeout_seconds, (int, float)):
        return float(created) + float(timeout_seconds)
    return None


def _failed_result(
    failure: ExecutionFailureFacts,
    selected_option_ids: tuple[str, ...] = (),
    feedback: str | None = None,
) -> GatePollResult:
    payload = {"failure": failure.to_wire()}
    return GatePollResult(
        "failed",
        payload,
        selected_option_ids=selected_option_ids,
        feedback=feedback,
        failure=failure.to_wire(),
    )


def wait_for_gate(
    bundle_path: Path,
    *,
    timeout_seconds: float | None = None,
    poll_interval: float = 0.2,
    cancelled: Callable[[], bool] | None = None,
    on_poll: Callable[[], None] | None = None,
) -> GatePollResult:
    """Wait for response/cancellation or the request's explicit gate timeout.

    The pending-action 24-hour staleness threshold is intentionally not read here;
    it is only a transport advisory state.
    """
    if poll_interval <= 0:
        raise GateError(
            "invalid_poll_interval", "poll_interval", "poll_interval must be positive"
        )
    envelope, _adapter = load_and_verify_bundle(bundle_path)
    configured = envelope.get("gate_timeout_seconds")
    configured_remaining: float | None = None
    if configured is not None:
        created = float(envelope.get("created_at_unix", time.time()))
        configured_remaining = max(0.0, created + float(configured) - time.time())
    if timeout_seconds is not None and timeout_seconds < 0:
        raise GateError(
            "invalid_timeout", "timeout_seconds", "timeout cannot be negative"
        )
    if configured_remaining is not None:
        timeout_seconds = (
            configured_remaining
            if timeout_seconds is None
            else min(timeout_seconds, configured_remaining)
        )
    deadline = None if timeout_seconds is None else time.monotonic() + timeout_seconds
    while True:
        result = poll_gate(bundle_path)
        if result is not None:
            return result
        if cancelled is not None and cancelled():
            try:
                payload = cancel_gate(bundle_path, source="requester")
            except GateError as exc:
                if exc.code != "already_answered":
                    raise
                response = poll_gate(bundle_path)
                if response is not None:
                    return response
                cancelled = None
                continue
            return GatePollResult("cancelled", payload)
        if on_poll is not None:
            on_poll()
            result = poll_gate(bundle_path)
            if result is not None:
                return result
        if deadline is not None and time.monotonic() >= deadline:
            try:
                payload = cancel_gate(
                    bundle_path, reason="timeout", source="gate_poller"
                )
            except GateError as exc:
                if exc.code != "already_answered":
                    raise
                response = poll_gate(bundle_path)
                if response is not None:
                    return response
                deadline = None
                continue
            return GatePollResult("timed_out", payload)
        sleep_for = poll_interval
        if deadline is not None:
            sleep_for = min(sleep_for, max(0.0, deadline - time.monotonic()))
        time.sleep(sleep_for)


__all__ = ["GatePollResult", "GatePollStatus", "poll_gate", "wait_for_gate"]

"""Generic response polling independent of transport staleness."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from sase.notification_gates.durability import read_json_object
from sase.notification_gates.executor import cancel_gate
from sase.notification_gates.hashing import load_and_verify_bundle
from sase.notification_gates.models import GateError
from sase.notification_gates.paths import (
    CANCELLATION_FILENAME,
    RESPONSE_FILENAME,
    assert_owned_bundle,
)

GatePollStatus = Literal["responded", "cancelled", "timed_out"]


@dataclass(frozen=True)
class GatePollResult:
    """Terminal observation made by the common gate poller."""

    status: GatePollStatus
    payload: dict[str, Any]


def poll_gate(bundle_path: Path) -> GatePollResult | None:
    """Return the current terminal state without waiting."""
    bundle_path = assert_owned_bundle(bundle_path)
    response_path = bundle_path / RESPONSE_FILENAME
    if response_path.exists():
        return GatePollResult("responded", read_json_object(response_path))
    cancellation_path = bundle_path / CANCELLATION_FILENAME
    if cancellation_path.exists():
        payload = read_json_object(cancellation_path)
        status: GatePollStatus = (
            "timed_out" if payload.get("reason") == "timeout" else "cancelled"
        )
        return GatePollResult(status, payload)
    return None


def wait_for_gate(
    bundle_path: Path,
    *,
    timeout_seconds: float | None = None,
    poll_interval: float = 0.2,
    cancelled: Callable[[], bool] | None = None,
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
    if timeout_seconds is None and configured is not None:
        timeout_seconds = float(configured)
        created = float(envelope.get("created_at_unix", time.time()))
        timeout_seconds = max(0.0, created + timeout_seconds - time.time())
    if timeout_seconds is not None and timeout_seconds < 0:
        raise GateError(
            "invalid_timeout", "timeout_seconds", "timeout cannot be negative"
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
                raise
            return GatePollResult("cancelled", payload)
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
                raise
            return GatePollResult("timed_out", payload)
        sleep_for = poll_interval
        if deadline is not None:
            sleep_for = min(sleep_for, max(0.0, deadline - time.monotonic()))
        time.sleep(sleep_for)


__all__ = ["GatePollResult", "GatePollStatus", "poll_gate", "wait_for_gate"]

"""Ordinary continuation reservation, spawn claiming, and receiver adoption."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import json
import os
from typing import Any

from sase.llm_provider.continuation_budget import MONITOR_CONTINUATION_ENV
from sase.monitor.continuation_admission import journal_continuation_reservation
from sase.monitor.delivery import (
    apply_delivery_transition,
    claim_dispatch_slot,
    delivery_key,
)
from sase.xprompt.queue_directive import format_queue_directive

DELIVERY_ARTIFACTS_ENV = "SASE_MONITOR_DELIVERY_ARTIFACTS_DIR"
DELIVERY_KEY_ENV = "SASE_MONITOR_DELIVERY_KEY"
DELIVERY_IDENTITY_ENV = "SASE_MONITOR_DELIVERY_IDENTITY"
DELIVERY_CRASH_ENV = "SASE_CONTINUATION_DELIVERY_CRASH_AT"
_TERMINAL_NO_SPAWN = frozenset(
    {"cancelled", "nonlaunchable", "needs_attention", "settled"}
)


class _InjectedDeliveryCrash(BaseException):
    """Test-only injected crash that must not be handled as a launch error."""


@dataclass(frozen=True, slots=True)
class _ContinuationDispatchClaim:
    """Outcome of reserving one ordinary continuation delivery."""

    key: dict[str, str]
    record: dict[str, Any]
    identity: str | None
    spawn: bool
    error: str | None = None


def claim_ordinary_continuation_dispatch(
    artifacts_dir: str,
    *,
    monitor_id: str,
    result_id: str,
    branch: str,
    selected_action: str,
    reserved_identity: str,
    extra: Mapping[str, Any] | None = None,
    workspace_identity: str | None = None,
    workspace_degraded: bool = False,
) -> _ContinuationDispatchClaim:
    """Reserve *reserved_identity* and claim the spawn slot for one delivery.

    Concurrent callers discover an already dispatching, acknowledged, or
    settled receiver instead of allocating a second identity. Identity is
    persisted before spawn so a supervisor death cannot start another model
    turn.
    """

    key = delivery_key(monitor_id=monitor_id, result_id=result_id, branch=branch)
    maybe_crash("before_reserve")
    record, claimed = claim_dispatch_slot(
        artifacts_dir,
        key,
        selected_action=selected_action,
        reserved_identity=reserved_identity,
        workspace_identity=workspace_identity,
        workspace_degraded=workspace_degraded,
        after_reserve=lambda: maybe_crash("after_reserve"),
    )
    identity = str(record.get("reserved_identity") or reserved_identity or "") or None
    if str(record.get("disposition") or "") in _TERMINAL_NO_SPAWN:
        return _ContinuationDispatchClaim(
            key=key,
            record=record,
            identity=identity,
            spawn=False,
            error=str(record.get("disposition_reason") or record["disposition"]),
        )
    if identity:
        journal_continuation_reservation(
            artifacts_dir,
            key=key,
            identity=identity,
            extra=extra,
            phase=str(record.get("disposition") or "reserved"),
        )
    return _ContinuationDispatchClaim(
        key=key,
        record=record,
        identity=identity,
        spawn=claimed and str(record.get("disposition")) == "dispatching",
    )


def mark_ordinary_continuation_terminal(
    artifacts_dir: str,
    key: Mapping[str, str],
    disposition: str,
    *,
    selected_action: str,
    reason: str | None = None,
    reserved_identity: str | None = None,
    retryable_pre_dispatch_failure: bool = False,
) -> dict[str, Any]:
    """Record a terminal or retryable ordinary-delivery outcome."""

    return apply_delivery_transition(
        artifacts_dir,
        key,
        disposition,
        selected_action=selected_action,
        reason=reason,
        reserved_identity=reserved_identity,
        retryable_pre_dispatch_failure=retryable_pre_dispatch_failure,
    )


def adopt_ordinary_continuation_delivery(
    *,
    env: Mapping[str, str] | None = None,
    agent_name: str | None = None,
) -> dict[str, Any] | None:
    """Adopt the reserved delivery key before provider invocation.

    Idempotent for the reserved receiver. A different identity cannot adopt
    the key and must not invoke a provider.
    """

    runtime = env or os.environ
    raw_key = runtime.get(DELIVERY_KEY_ENV)
    artifacts_dir = runtime.get(DELIVERY_ARTIFACTS_ENV)
    identity = (
        agent_name
        or runtime.get("SASE_AGENT_NAME")
        or runtime.get(DELIVERY_IDENTITY_ENV)
    )
    if not raw_key or not artifacts_dir or not identity:
        return None
    maybe_crash("before_adopt")
    key = json.loads(raw_key)
    if not isinstance(key, dict):
        raise ValueError("continuation delivery key must be a JSON object")
    record = apply_delivery_transition(
        artifacts_dir,
        {
            "monitor_id": str(key["monitor_id"]),
            "result_id": str(key["result_id"]),
            "branch": str(key["branch"]),
        },
        "acknowledged",
        selected_action="continue",
        reserved_identity=identity,
        acknowledged_by=identity,
    )
    maybe_crash("after_adopt")
    return record


def continuation_delivery_env(
    artifacts_dir: str,
    key: Mapping[str, str],
    identity: str,
) -> dict[str, str]:
    """Return child env vars that carry the exact delivery key."""

    return {
        MONITOR_CONTINUATION_ENV: "1",
        DELIVERY_ARTIFACTS_ENV: artifacts_dir,
        DELIVERY_KEY_ENV: json.dumps(dict(key), sort_keys=True),
        DELIVERY_IDENTITY_ENV: identity,
    }


def queue_launch_prefix(meta: Mapping[str, Any]) -> str:
    """Return a live ``%queue`` prefix carrying parent weight/priority/capacity."""

    weight = _optional_float(meta.get("queue_weight"))
    priority = _optional_int(meta.get("wait_priority") or meta.get("queue_priority"))
    capacity = _optional_int(meta.get("wait_runners") or meta.get("queue_capacity"))
    if weight is None and priority is None and capacity is None:
        return ""
    formatted = format_queue_directive(
        capacity=capacity, priority=priority, weight=weight
    )
    return f"{formatted}\n" if formatted else ""


def launch_wire_extra(meta: Mapping[str, Any]) -> dict[str, Any]:
    """Return admission-journal extras from the monitor's launch wires."""

    extra: dict[str, Any] = {}
    weight = _optional_float(meta.get("queue_weight"))
    if weight is not None:
        extra["queue_weight"] = weight
        extra["queue_weight_explicit"] = bool(meta.get("queue_weight_explicit"))
    target = _optional_text(meta.get("dispatch_target"))
    if target:
        extra["dispatch_target"] = target
    reference = _optional_text(
        meta.get("workspace_reference") or meta.get("continuation_workspace_ref")
    )
    if reference:
        extra["workspace_reference"] = reference
    return extra


def maybe_crash(point: str) -> None:
    """Raise when tests inject a crash at *point*."""

    wanted = os.environ.get(DELIVERY_CRASH_ENV)
    if wanted == point:
        raise _InjectedDeliveryCrash(f"injected continuation delivery crash at {point}")


def _optional_text(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _optional_float(value: object) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int | float):
        return float(value)
    return None


def _optional_int(value: object) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    return None


__all__ = [
    "DELIVERY_ARTIFACTS_ENV",
    "DELIVERY_CRASH_ENV",
    "DELIVERY_IDENTITY_ENV",
    "DELIVERY_KEY_ENV",
    "adopt_ordinary_continuation_delivery",
    "claim_ordinary_continuation_dispatch",
    "continuation_delivery_env",
    "launch_wire_extra",
    "mark_ordinary_continuation_terminal",
    "maybe_crash",
    "queue_launch_prefix",
]

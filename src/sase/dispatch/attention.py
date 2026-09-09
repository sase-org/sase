"""Source-side fleet attention client: fetch and answer remote gates/questions."""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from sase.core.paths import sase_home
from sase.core.rust import require_rust_binding

from .attention_intent import (
    load_dispatch_attention_intent,
    update_dispatch_attention_intent,
    upsert_dispatch_attention_intent,
)
from .config import load_dispatch_config
from .federation import (
    FederationWorkerResponseError,
    FederationWorkerUnavailable,
    build_federation_facade,
    load_federation_config,
)
from .models import DispatchError, MachineRecord

_FLEET_SCHEMA_VERSION = 1
AttentionOutcome = Literal[
    "applied",
    "already_settled",
    "stale_revision",
    "unknown_request",
    "capability_missing",
    "precondition_failed",
    "unsent",
    "uncertain",
]


class RemoteDispatchAttentionError(RuntimeError):
    """Raised when a remote attention answer cannot be submitted safely."""

    def __init__(self, message: str, *, outcome: AttentionOutcome = "unsent") -> None:
        super().__init__(message)
        self.outcome = outcome


@dataclass(frozen=True)
class RemoteAttentionResult:
    """Typed outcome of answering one remote question or approving one gate."""

    alias: str
    outcome: AttentionOutcome
    message: str
    receipt: dict[str, Any] | None = None
    settled_response: dict[str, Any] | None = None
    decision: str | None = None
    reason: str | None = None


def fetch_remote_attention(
    logical_keys: Sequence[str],
    *,
    cache_only: bool = False,
    timeout_seconds: float | None = None,
) -> dict[str, Any]:
    """Fetch pending attention for a bounded set of followed logical keys.

    Degrades to the disabled-read shape when no machine is configured,
    mirroring ``followed_batch``. Callers skip this call entirely when
    *logical_keys* is empty, so laziness holds with no followed rows.
    """
    if not logical_keys:
        return {
            "schema_version": _FLEET_SCHEMA_VERSION,
            "operation": "attention",
            "disabled": True,
            "hosts": [],
        }
    config = load_federation_config()
    request = {
        "schema_version": _FLEET_SCHEMA_VERSION,
        "logical_keys": list(logical_keys),
    }
    return build_federation_facade(config).attention_sync(
        request,
        cache_only=cache_only,
        timeout_seconds=timeout_seconds or config.worker.request_timeout_seconds,
    )


def fetch_remote_attention_inventory(
    *,
    cursor: str | None = None,
    limit: int | None = None,
    cache_only: bool = False,
    timeout_seconds: float | None = None,
) -> dict[str, Any]:
    """Fetch a bounded fleet-wide page of pending owner-side attention."""

    config = load_federation_config()
    request: dict[str, Any] = {"schema_version": _FLEET_SCHEMA_VERSION}
    if cursor is not None:
        request["cursor"] = cursor
    if limit is not None:
        request["limit"] = limit
    return build_federation_facade(config).attention_inventory_sync(
        request,
        cache_only=cache_only,
        timeout_seconds=timeout_seconds or config.worker.request_timeout_seconds,
    )


def submit_remote_attention_answer(
    alias: str,
    intent: Mapping[str, Any],
    *,
    operation_id: str | None = None,
    timeout_seconds: float | None = None,
) -> RemoteAttentionResult:
    """Submit one question answer or gate approval against a remote host.

    *intent* carries the answer fields the owner's fleet attention contract
    expects (kind, request_key, observed_revision, and either the gate's
    selected_option_ids/feedback or the question's answer fields), without
    schema_version. The owner re-validates the request against its own
    current state; this function never assumes the answer will be applied
    as submitted.
    """
    try:
        config = load_dispatch_config()
        machine = _target_machine(config.machine_by_alias(), alias)
        full_intent = {"schema_version": _FLEET_SCHEMA_VERSION, **dict(intent)}
        operation_key = _operation_key(operation_id, alias, full_intent)
        fingerprint = _call_dict_binding(
            "fleet_attention_payload_fingerprint",
            full_intent,
            what="attention payload fingerprint",
        )
        request = {
            "schema_version": _FLEET_SCHEMA_VERSION,
            "key": operation_key,
            "target_installation_id": machine.pinned_installation_id,
            "intent": full_intent,
            "payload_fingerprint": fingerprint,
            "acceptance_window_seconds": max(
                timeout_seconds or config.request_timeout_seconds,
                30.0,
            ),
        }
        _call_dict_binding(
            "fleet_validate_attention_request",
            request,
            what="attention request validation",
        )
        existing = load_dispatch_attention_intent(operation_key)
        if existing is not None and existing.get("status") in {
            "settled",
            "accepted",
        }:
            receipt = existing.get("receipt")
            if isinstance(receipt, Mapping):
                return _result_from_receipt(
                    alias,
                    dict(receipt),
                    decision="return_original_receipt",
                    reason="same_scoped_key_and_payload",
                )
        upsert_dispatch_attention_intent(
            {
                "schema_version": _FLEET_SCHEMA_VERSION,
                "operation_key": operation_key,
                "target": alias,
                "target_installation_id": machine.pinned_installation_id,
                "request_key": dict(full_intent["request_key"]),
                "payload_fingerprint": fingerprint,
                "status": "unsent",
                "created_at_unix": time.time(),
                "updated_at_unix": time.time(),
            }
        )
        update_dispatch_attention_intent(operation_key, status="acceptance_uncertain")
        try:
            response = build_federation_facade().resolve_attention_sync(
                alias,
                request,
                timeout_seconds=timeout_seconds or config.request_timeout_seconds,
            )
        except FederationWorkerUnavailable as exc:
            update_dispatch_attention_intent(
                operation_key,
                status="unsent",
                error=str(exc),
            )
            raise RemoteDispatchAttentionError(
                f"answer was not sent to {alias}: {exc}",
                outcome="unsent",
            ) from exc
        except FederationWorkerResponseError as exc:
            update_dispatch_attention_intent(
                operation_key,
                status="acceptance_uncertain",
                error=str(exc),
            )
            raise RemoteDispatchAttentionError(
                f"answer outcome is uncertain for {alias}: {exc}",
                outcome="uncertain",
            ) from exc
        receipt, decision, reason_code = _receipt_from_response(response, alias)
        source_status = "settled" if receipt.get("state") == "settled" else "accepted"
        update_dispatch_attention_intent(
            operation_key,
            status=source_status,
            receipt=receipt,
        )
        return _result_from_receipt(
            alias,
            receipt,
            decision=decision,
            reason=reason_code,
        )
    except (DispatchError, ValueError) as exc:
        raise RemoteDispatchAttentionError(str(exc), outcome="unsent") from exc


def _target_machine(
    machines: Mapping[str, MachineRecord],
    target: str,
) -> MachineRecord:
    machine = machines.get(target)
    if machine is None:
        raise RemoteDispatchAttentionError(
            f"dispatch target {target!r} is not enrolled in dispatch.machines"
        )
    if machine.quarantined:
        reason = machine.quarantine_reason or "machine is quarantined"
        raise RemoteDispatchAttentionError(
            f"dispatch target {target!r} is quarantined: {reason}"
        )
    return machine


def _operation_key(
    operation_id: str | None,
    alias: str,
    intent: Mapping[str, Any],
) -> dict[str, str | int]:
    source_identity = require_rust_binding("fleet_installation_identity_ensure")(
        str(sase_home())
    )
    record = source_identity.get("record") if isinstance(source_identity, dict) else {}
    controller_id = (
        record.get("installation_id") if isinstance(record, Mapping) else None
    )
    if not isinstance(controller_id, str) or not controller_id:
        raise RemoteDispatchAttentionError(
            "could not resolve source installation identity"
        )
    resolved_id = operation_id or _deterministic_operation_id(alias, intent)
    return {
        "schema_version": _FLEET_SCHEMA_VERSION,
        "controller_id": controller_id,
        "operation_id": resolved_id,
    }


def _deterministic_operation_id(alias: str, intent: Mapping[str, Any]) -> str:
    digest = hashlib.sha256(
        json.dumps(
            {"target": alias, "intent": dict(intent)},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return f"attention-{digest[:32]}"


def _receipt_from_response(
    response: Mapping[str, Any],
    alias: str,
) -> tuple[dict[str, Any], str, str]:
    hosts = response.get("hosts")
    if not isinstance(hosts, list) or len(hosts) != 1:
        raise RemoteDispatchAttentionError(
            f"federation resolve_attention returned no host for {alias}"
        )
    host = hosts[0]
    if not isinstance(host, Mapping):
        raise RemoteDispatchAttentionError(
            "federation resolve_attention host result is invalid"
        )
    error = host.get("error")
    if isinstance(error, Mapping):
        raise RemoteDispatchAttentionError(
            str(error.get("message") or "federation resolve_attention host failed"),
            outcome="uncertain",
        )
    payload = host.get("payload")
    if not isinstance(payload, Mapping):
        raise RemoteDispatchAttentionError(
            "federation resolve_attention returned no receipt payload"
        )
    receipt = payload.get("receipt")
    if not isinstance(receipt, Mapping):
        raise RemoteDispatchAttentionError(
            "federation resolve_attention response is missing receipt"
        )
    return (
        dict(receipt),
        str(payload.get("decision") or ""),
        str(payload.get("reason") or ""),
    )


def _result_from_receipt(
    alias: str,
    receipt: Mapping[str, Any],
    *,
    decision: str,
    reason: str,
) -> RemoteAttentionResult:
    outcome_value = receipt.get("outcome") or "applied"
    outcome: AttentionOutcome = (
        outcome_value if isinstance(outcome_value, str) else "applied"  # type: ignore[assignment]
    )
    message = str(receipt.get("message") or f"answer on {alias} {outcome}")
    settled_response = receipt.get("settled_response")
    return RemoteAttentionResult(
        alias=alias,
        outcome=outcome,
        message=message,
        receipt=dict(receipt),
        settled_response=(
            dict(settled_response) if isinstance(settled_response, Mapping) else None
        ),
        decision=decision,
        reason=reason,
    )


def _call_dict_binding(
    name: str, payload: Mapping[str, Any], *, what: str
) -> dict[str, Any]:
    try:
        result = require_rust_binding(name)(dict(payload))
    except Exception as exc:
        raise RemoteDispatchAttentionError(f"{what} failed: {exc}") from exc
    if not isinstance(result, dict):
        raise RemoteDispatchAttentionError(f"{what} returned a non-object result")
    return result


__all__ = [
    "AttentionOutcome",
    "RemoteAttentionResult",
    "RemoteDispatchAttentionError",
    "fetch_remote_attention",
    "fetch_remote_attention_inventory",
    "submit_remote_attention_answer",
]

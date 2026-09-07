"""Source-side fleet lifecycle mutation client."""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from sase.core.paths import sase_home
from sase.core.rust import require_rust_binding

from .config import load_dispatch_config
from .federation import (
    FederationWorkerResponseError,
    FederationWorkerUnavailable,
    build_federation_facade,
)
from .follow_store import (
    FollowStoreError,
    activate_dispatch_follow,
    load_follow_snapshot,
)
from .models import DispatchError, MachineRecord
from .mutation_intent import (
    load_dispatch_mutation_intent,
    update_dispatch_mutation_intent,
    upsert_dispatch_mutation_intent,
)

_FLEET_SCHEMA_VERSION = 1
MutationKind = Literal["stop", "retry", "fork"]
MutationOutcome = Literal[
    "applied",
    "already_settled",
    "precondition_failed",
    "capability_missing",
    "unsent",
    "uncertain",
]


class RemoteDispatchMutationError(RuntimeError):
    """Raised when a remote lifecycle mutation cannot be submitted safely."""

    def __init__(self, message: str, *, outcome: MutationOutcome = "unsent") -> None:
        super().__init__(message)
        self.outcome = outcome


@dataclass(frozen=True)
class RemoteMutationResult:
    """Typed per-target mutation outcome."""

    alias: str
    kind: MutationKind
    outcome: MutationOutcome
    message: str
    receipt: dict[str, Any] | None = None
    decision: str | None = None
    reason: str | None = None


def _submit_remote_mutation(
    *,
    alias: str,
    kind: MutationKind,
    snapshot: Mapping[str, Any],
    fork_prompt: str | None = None,
    kill_source_first: bool | None = None,
    follow: bool = True,
    reason: str | None = None,
    operation_id: str | None = None,
    timeout_seconds: float | None = None,
) -> RemoteMutationResult:
    """Submit one stop/retry/fork mutation against a remote row snapshot."""
    try:
        config = load_dispatch_config()
        machine = _target_machine(config.machine_by_alias(), alias)
        _require_advertised_capability(kind, snapshot, alias=alias)
        intent = _mutation_intent(
            kind,
            snapshot,
            fork_prompt=fork_prompt,
            kill_source_first=kill_source_first,
            follow=follow,
            reason=reason,
        )
        operation_key = _operation_key(operation_id, alias, intent)
        fingerprint = _call_dict_binding(
            "fleet_mutation_payload_fingerprint",
            intent,
            what="mutation payload fingerprint",
        )
        request = {
            "schema_version": _FLEET_SCHEMA_VERSION,
            "key": operation_key,
            "target_installation_id": machine.pinned_installation_id,
            "intent": intent,
            "payload_fingerprint": fingerprint,
            "acceptance_window_seconds": max(
                timeout_seconds or config.request_timeout_seconds,
                30.0,
            ),
        }
        _call_dict_binding(
            "fleet_validate_mutation_request",
            request,
            what="mutation request validation",
        )
        existing = load_dispatch_mutation_intent(operation_key)
        if existing is not None and existing.get("status") in {
            "settled",
            "accepted",
        }:
            receipt = existing.get("receipt")
            if isinstance(receipt, Mapping):
                return _result_from_receipt(
                    alias,
                    kind,
                    dict(receipt),
                    decision="return_original_receipt",
                    reason="same_scoped_key_and_payload",
                )
        upsert_dispatch_mutation_intent(
            {
                "schema_version": _FLEET_SCHEMA_VERSION,
                "operation_key": operation_key,
                "target": alias,
                "target_installation_id": machine.pinned_installation_id,
                "kind": kind,
                "exact_locator": dict(intent["target"]),
                "payload_fingerprint": fingerprint,
                "follow": follow,
                "status": "unsent",
                "created_at_unix": time.time(),
                "updated_at_unix": time.time(),
            }
        )
        update_dispatch_mutation_intent(operation_key, status="acceptance_uncertain")
        try:
            response = build_federation_facade().mutate_sync(
                alias,
                request,
                timeout_seconds=timeout_seconds or config.request_timeout_seconds,
            )
        except FederationWorkerUnavailable as exc:
            update_dispatch_mutation_intent(
                operation_key,
                status="unsent",
                error=str(exc),
            )
            raise RemoteDispatchMutationError(
                f"mutation was not sent to {alias}: {exc}",
                outcome="unsent",
            ) from exc
        except FederationWorkerResponseError as exc:
            update_dispatch_mutation_intent(
                operation_key,
                status="acceptance_uncertain",
                error=str(exc),
            )
            raise RemoteDispatchMutationError(
                f"mutation outcome is uncertain for {alias}: {exc}",
                outcome="uncertain",
            ) from exc
        receipt, decision, reason_code = _receipt_from_response(response, alias)
        if decision not in {"accept_new", "return_original_receipt"}:
            update_dispatch_mutation_intent(
                operation_key,
                status=decision,
                receipt=receipt,
                error=reason_code,
            )
            outcome = _decision_outcome(decision, reason_code)
            raise RemoteDispatchMutationError(
                _host_named_message(alias, kind, outcome, reason_code),
                outcome=outcome,
            )
        source_status = "settled" if receipt.get("state") == "settled" else "accepted"
        update_dispatch_mutation_intent(
            operation_key,
            status=source_status,
            receipt=receipt,
        )
        result = _result_from_receipt(
            alias,
            kind,
            receipt,
            decision=decision,
            reason=reason_code,
        )
        if follow and kind in {"retry", "fork"}:
            _activate_follow(receipt, operation_key=operation_key)
        return result
    except (DispatchError, FollowStoreError, ValueError) as exc:
        raise RemoteDispatchMutationError(str(exc), outcome="unsent") from exc


def submit_remote_mutations(
    targets: Sequence[Mapping[str, Any]],
    *,
    kind: MutationKind,
    fork_prompt: str | None = None,
    kill_source_first: bool | None = None,
    follow: bool = True,
    reason: str | None = None,
    timeout_seconds: float | None = None,
) -> tuple[RemoteMutationResult, ...]:
    """Partition *targets* by origin and submit one mutation per attributed row."""
    bulk_targets = [_bulk_target(item) for item in targets]
    partition = require_rust_binding("fleet_partition_bulk_targets")(bulk_targets)
    results: list[RemoteMutationResult] = []
    for item in partition.get("unattributed") or ():
        results.append(
            RemoteMutationResult(
                alias=str(item.get("alias") or "unknown"),
                kind=kind,
                outcome="unsent",
                message="remote mutation target has no origin installation",
            )
        )
    for group in partition.get("groups") or ():
        alias = str(group.get("alias") or "")
        for item in group.get("targets") or ():
            snapshot = {
                "alias": alias,
                "origin_installation_id": group.get("origin_installation_id"),
                "exact_locator": item.get("target"),
                "row_revision": item.get("row_revision"),
                "capabilities": item.get("capabilities") or {},
            }
            try:
                results.append(
                    _submit_remote_mutation(
                        alias=alias,
                        kind=kind,
                        snapshot=snapshot,
                        fork_prompt=fork_prompt,
                        kill_source_first=kill_source_first,
                        follow=follow,
                        reason=reason,
                        timeout_seconds=timeout_seconds,
                    )
                )
            except RemoteDispatchMutationError as exc:
                results.append(
                    RemoteMutationResult(
                        alias=alias,
                        kind=kind,
                        outcome=exc.outcome,
                        message=str(exc),
                    )
                )
    return tuple(results)


def _bulk_target(item: Mapping[str, Any]) -> dict[str, Any]:
    target = item.get("exact_locator") or item.get("target")
    revision = item.get("row_revision")
    if not isinstance(target, Mapping) or not isinstance(revision, Mapping):
        raise RemoteDispatchMutationError(
            "bulk mutation target requires exact_locator and row_revision"
        )
    return {
        "schema_version": _FLEET_SCHEMA_VERSION,
        "origin_installation_id": item.get("origin_installation_id"),
        "alias": item.get("alias"),
        "target": dict(target),
        "row_revision": dict(revision),
    }


_KIND_CAPABILITY: dict[MutationKind, str] = {
    "stop": "lifecycle.stop",
    "retry": "lifecycle.retry",
    "fork": "lifecycle.fork",
}


def _require_advertised_capability(
    kind: MutationKind,
    snapshot: Mapping[str, Any],
    *,
    alias: str,
) -> None:
    capabilities = snapshot.get("capabilities")
    if not isinstance(capabilities, Mapping):
        return
    resource = capabilities.get("resource")
    if not isinstance(resource, (list, tuple, set)) or not resource:
        return
    needed = _KIND_CAPABILITY[kind]
    if needed not in resource:
        raise RemoteDispatchMutationError(
            f"{kind} on {alias} capability_missing: {needed}",
            outcome="capability_missing",
        )


def _mutation_intent(
    kind: MutationKind,
    snapshot: Mapping[str, Any],
    *,
    fork_prompt: str | None,
    kill_source_first: bool | None,
    follow: bool,
    reason: str | None,
) -> dict[str, Any]:
    target = snapshot.get("exact_locator") or snapshot.get("target")
    revision = snapshot.get("row_revision")
    if not isinstance(target, Mapping):
        raise RemoteDispatchMutationError("mutation snapshot is missing exact_locator")
    if not isinstance(revision, Mapping):
        raise RemoteDispatchMutationError("mutation snapshot is missing row_revision")
    return {
        "schema_version": _FLEET_SCHEMA_VERSION,
        "kind": kind,
        "target": dict(target),
        "row_revision": dict(revision),
        "reason": reason,
        "fork_prompt": fork_prompt if kind == "fork" else None,
        "kill_source_first": kill_source_first if kind == "retry" else None,
        "follow": follow,
    }


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
        raise RemoteDispatchMutationError(
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
    return f"mutate-{digest[:32]}"


def _target_machine(
    machines: Mapping[str, MachineRecord],
    target: str,
) -> MachineRecord:
    machine = machines.get(target)
    if machine is None:
        raise RemoteDispatchMutationError(
            f"dispatch target {target!r} is not enrolled in dispatch.machines"
        )
    if machine.quarantined:
        reason = machine.quarantine_reason or "machine is quarantined"
        raise RemoteDispatchMutationError(
            f"dispatch target {target!r} is quarantined: {reason}"
        )
    return machine


def _receipt_from_response(
    response: Mapping[str, Any],
    alias: str,
) -> tuple[dict[str, Any], str, str]:
    hosts = response.get("hosts")
    if not isinstance(hosts, list) or len(hosts) != 1:
        raise RemoteDispatchMutationError(
            f"federation mutate returned no host for {alias}"
        )
    host = hosts[0]
    if not isinstance(host, Mapping):
        raise RemoteDispatchMutationError("federation mutate host result is invalid")
    error = host.get("error")
    if isinstance(error, Mapping):
        raise RemoteDispatchMutationError(
            str(error.get("message") or "federation mutate host failed"),
            outcome="uncertain",
        )
    payload = host.get("payload")
    if not isinstance(payload, Mapping):
        raise RemoteDispatchMutationError(
            "federation mutate returned no receipt payload"
        )
    receipt = payload.get("receipt")
    if not isinstance(receipt, Mapping):
        raise RemoteDispatchMutationError(
            "federation mutate response is missing receipt"
        )
    return (
        dict(receipt),
        str(payload.get("decision") or ""),
        str(payload.get("reason") or ""),
    )


def _result_from_receipt(
    alias: str,
    kind: MutationKind,
    receipt: Mapping[str, Any],
    *,
    decision: str,
    reason: str,
) -> RemoteMutationResult:
    outcome: MutationOutcome = (
        "already_settled" if decision == "return_original_receipt" else "applied"
    )
    verb = {
        "stop": "Stop requested",
        "retry": "Retry requested",
        "fork": "Fork requested",
    }[kind]
    message = str(receipt.get("message") or f"{verb} on {alias}")
    if " on " not in message:
        message = f"{verb} on {alias}"
    return RemoteMutationResult(
        alias=alias,
        kind=kind,
        outcome=outcome,
        message=message,
        receipt=dict(receipt),
        decision=decision,
        reason=reason,
    )


def _decision_outcome(decision: str, reason: str) -> MutationOutcome:
    if "capability" in reason:
        return "capability_missing"
    if decision in {"precondition_mismatch", "conflict", "expired"}:
        return "precondition_failed"
    return "uncertain"


def _host_named_message(
    alias: str,
    kind: MutationKind,
    outcome: MutationOutcome,
    reason: str,
) -> str:
    return f"{kind} on {alias} {outcome}: {reason}"


def _activate_follow(
    receipt: Mapping[str, Any],
    *,
    operation_key: Mapping[str, Any],
) -> None:
    logical = receipt.get("logical_locator")
    if not isinstance(logical, Mapping):
        return
    snapshot = load_follow_snapshot()
    logical_key = _locator_key(logical)
    if logical_key and any(
        tombstone.get("logical_key") == logical_key for tombstone in snapshot.tombstones
    ):
        return
    activate_dispatch_follow(logical, operation_key=operation_key)


def _locator_key(locator: Mapping[str, Any]) -> str | None:
    try:
        return str(require_rust_binding("fleet_logical_locator_key")(dict(locator)))
    except Exception:
        return None


def _call_dict_binding(
    name: str, payload: Mapping[str, Any], *, what: str
) -> dict[str, Any]:
    try:
        result = require_rust_binding(name)(dict(payload))
    except Exception as exc:
        raise RemoteDispatchMutationError(f"{what} failed: {exc}") from exc
    if not isinstance(result, dict):
        raise RemoteDispatchMutationError(f"{what} returned a non-object result")
    return result


__all__ = [
    "RemoteDispatchMutationError",
    "RemoteMutationResult",
    "submit_remote_mutations",
]

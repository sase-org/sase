"""Source-side `%dispatch` submission and receipt handling."""

from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .config import load_dispatch_config
from .federation import (
    FederationWorkerResponseError,
    FederationWorkerUnavailable,
    build_federation_facade,
)
from .follow_store import (
    FollowStoreError,
    activate_dispatch_follow,
    prewrite_dispatch_follow,
    promote_agent_session_follow,
)
from .launch_intent import (
    update_dispatch_launch_intent,
    upsert_dispatch_launch_intent,
)
from .launch_preview import preview_dispatch_launch
from .models import DispatchError
from ._launch_common import (
    FLEET_SCHEMA_VERSION,
    RemoteDispatchLaunchError,
    RemoteDispatchLaunchPreview,
    optional_string,
)


@dataclass(frozen=True)
class _RemoteDispatchLaunchResult:
    """Successful source-side dispatch result for `run.launch` emission."""

    target: str
    prompt: str
    message: str
    payload: dict[str, object]


def maybe_dispatch_launch(
    query: str,
    *,
    payload: Mapping[str, Any],
    unresolved_names: Sequence[str] = (),
) -> _RemoteDispatchLaunchResult | None:
    """Submit a remote dispatch launch if *query* contains `%dispatch`."""
    preview: RemoteDispatchLaunchPreview | None = None
    try:
        preview = preview_dispatch_launch(query, payload=payload)
        if preview is None:
            return None
        config = load_dispatch_config()
        upsert_dispatch_launch_intent(
            {
                "schema_version": FLEET_SCHEMA_VERSION,
                "operation_key": preview.operation_key,
                "target": preview.target,
                "target_installation_id": preview.target_installation_id,
                "prompt": preview.prompt,
                "portable_context": preview.portable_context,
                "payload_fingerprint": preview.payload_fingerprint,
                "follow": preview.intent["follow"],
                "status": "unsent",
                "created_at_unix": time.time(),
                "updated_at_unix": time.time(),
            }
        )
        if preview.intent["follow"]:
            prewrite_dispatch_follow(preview.provisional_locator, preview.operation_key)
        update_dispatch_launch_intent(
            preview.operation_key, status="acceptance_uncertain"
        )
        try:
            response = build_federation_facade().launch_sync(
                preview.target,
                preview.request,
                timeout_seconds=config.request_timeout_seconds,
            )
        except FederationWorkerUnavailable as exc:
            update_dispatch_launch_intent(
                preview.operation_key,
                status="unsent",
                error=str(exc),
            )
            raise
        except FederationWorkerResponseError as exc:
            update_dispatch_launch_intent(
                preview.operation_key,
                status="acceptance_uncertain",
                error=str(exc),
            )
            raise
        receipt, decision, reason = _launch_receipt_from_response(response)
        if decision not in {"accept_new", "return_original_receipt"}:
            update_dispatch_launch_intent(
                preview.operation_key,
                status=decision,
                receipt=receipt,
                error=reason,
            )
            raise RemoteDispatchLaunchError(
                f"remote dispatch {decision} for {preview.target}: {reason}"
            )
        source_status = _source_status_from_receipt(receipt)
        update_dispatch_launch_intent(
            preview.operation_key,
            status=source_status,
            receipt=receipt,
        )
        if source_status == "failed":
            message = _failed_receipt_message(preview.target, receipt, reason)
            update_dispatch_launch_intent(
                preview.operation_key,
                status="failed",
                receipt=receipt,
                error=message,
            )
            raise RemoteDispatchLaunchError(message)
        if preview.intent["follow"]:
            _activate_receipt_follow(
                preview.provisional_locator,
                receipt,
                operation_key=preview.operation_key,
            )
        message = f"Dispatched launch to {preview.target} ({source_status})"
        if preview.target_detail:
            message = f"{message}; {preview.target_detail}"
        return _RemoteDispatchLaunchResult(
            target=preview.target,
            prompt=str(preview.intent["prompt"]),
            message=message,
            payload=_run_launch_payload(
                preview=preview,
                receipt=receipt,
                decision=decision,
                reason=reason,
                source_status=source_status,
                unresolved_names=unresolved_names,
            ),
        )
    except (DispatchError, FollowStoreError, ValueError) as exc:
        raise RemoteDispatchLaunchError(str(exc)) from exc
    except FederationWorkerUnavailable as exc:
        target = preview.target if preview is not None else "remote target"
        raise RemoteDispatchLaunchError(
            f"remote dispatch was not sent to {target}: {exc}"
        ) from exc
    except FederationWorkerResponseError as exc:
        target = preview.target if preview is not None else "remote target"
        raise RemoteDispatchLaunchError(
            f"remote dispatch outcome is uncertain for {target}: {exc}"
        ) from exc


def _activate_receipt_follow(
    provisional_locator: Mapping[str, Any],
    receipt: Mapping[str, Any],
    *,
    operation_key: Mapping[str, Any],
) -> None:
    logical = receipt.get("logical_locator")
    if not isinstance(logical, Mapping):
        return
    # legacy agent-family spelling: core emits ``family_id`` until core-contract;
    # new writers send ``agent_session_id``.
    if dict(logical) != dict(provisional_locator) and (
        logical.get("agent_session_id") or logical.get("family_id")
    ):
        promote_agent_session_follow(provisional_locator, logical)
    activate_dispatch_follow(logical, operation_key=operation_key)


def _launch_receipt_from_response(
    response: Mapping[str, Any],
) -> tuple[dict[str, Any], str, str]:
    hosts = response.get("hosts")
    if not isinstance(hosts, list) or len(hosts) != 1:
        raise RemoteDispatchLaunchError("federation launch returned no target host")
    host = hosts[0]
    if not isinstance(host, Mapping):
        raise RemoteDispatchLaunchError("federation launch host result is invalid")
    error = host.get("error")
    if isinstance(error, Mapping):
        raise RemoteDispatchLaunchError(
            str(error.get("message") or "federation launch host failed")
        )
    payload = host.get("payload")
    if not isinstance(payload, Mapping):
        raise RemoteDispatchLaunchError("federation launch returned no receipt payload")
    receipt = payload.get("receipt")
    if not isinstance(receipt, Mapping):
        raise RemoteDispatchLaunchError("federation launch response is missing receipt")
    decision = str(payload.get("decision") or "")
    reason = str(payload.get("reason") or "")
    return dict(receipt), decision, reason


def _source_status_from_receipt(receipt: Mapping[str, Any]) -> str:
    state = receipt.get("state")
    if state == "settled":
        return "settled"
    if state == "failed":
        return "failed"
    return "accepted"


def _failed_receipt_message(
    target: str,
    receipt: Mapping[str, Any],
    reason: str,
) -> str:
    message = optional_string(receipt.get("message")) or optional_string(reason)
    if message is None:
        message = "launch failed"
    return f"remote dispatch failed for {target}: {message}"


def _run_launch_payload(
    *,
    preview: RemoteDispatchLaunchPreview,
    receipt: Mapping[str, Any],
    decision: str,
    reason: str,
    source_status: str,
    unresolved_names: Sequence[str],
) -> dict[str, object]:
    payload: dict[str, object] = {
        "count": 0,
        "pids": [],
        "results": [],
        "request_agents_refresh": True,
        "schedule_agents_refresh": True,
        "dispatch": {
            "target": preview.target,
            "source": preview.source,
            "target_installation_id": preview.target_installation_id,
            "operation_key": dict(preview.operation_key),
            "payload_fingerprint": dict(preview.payload_fingerprint),
            "portable_context": dict(preview.portable_context),
            "decision": decision,
            "reason": reason,
            "state": receipt.get("state"),
            "source_status": source_status,
            "receipt": dict(receipt),
        },
    }
    if unresolved_names:
        from sase.xprompt.unresolved import format_unresolved_references_toast

        payload["warning_messages"] = [
            format_unresolved_references_toast(tuple(unresolved_names))
        ]
    return payload


__all__ = [
    "maybe_dispatch_launch",
]

"""Reference non-mutating finalizer fixture."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def provider(request: Mapping[str, Any]) -> dict[str, Any]:
    operation = str(request["operation"])
    payload = request.get("payload")
    if operation == "validate":
        if payload is not None and not isinstance(payload, Mapping):
            return _failed(
                request,
                operation,
                "payload_not_object",
                "audit payload must be an object",
            )
        if isinstance(payload, Mapping) and payload.get("reject"):
            reason = payload.get("reason")
            message = (
                reason
                if isinstance(reason, str) and reason.strip()
                else "audit payload rejected"
            )
            return _failed(request, operation, "payload_rejected", message)
    evidence: list[dict[str, str]] = []
    if operation == "execute":
        evidence.append({"kind": "reference", "value": "non-mutating"})
        if isinstance(payload, Mapping):
            note = payload.get("note")
            if isinstance(note, str) and note:
                evidence.append({"kind": "payload_note", "value": note})
        obligations = request.get("obligations")
        if isinstance(obligations, list):
            evidence.append(
                {"kind": "obligation_count", "value": str(len(obligations))}
            )
    return {
        "schema_version": 1,
        "operation": operation,
        "provider_ref": "example-finalizers@audit",
        "instance_id": str(request["instance_id"]),
        "status": "success" if operation == "execute" else "ok",
        "evidence": evidence,
    }


def _failed(
    request: Mapping[str, Any],
    operation: str,
    code: str,
    message: str,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "operation": operation,
        "provider_ref": "example-finalizers@audit",
        "instance_id": str(request["instance_id"]),
        "status": "failed",
        "diagnostics": [
            {
                "code": code,
                "severity": "error",
                "message": message,
            }
        ],
    }

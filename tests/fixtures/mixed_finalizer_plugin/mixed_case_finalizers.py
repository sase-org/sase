"""Mixed-case distribution fixture with a request-callable provider."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

CALLS = 0


def provider(request: Mapping[str, Any]) -> dict[str, Any]:
    global CALLS
    CALLS += 1
    payload = request.get("payload")
    if isinstance(payload, Mapping) and payload.get("boom"):
        raise TypeError("internal boom")
    operation = str(request["operation"])
    return {
        "schema_version": 1,
        "operation": operation,
        "provider_ref": "mixed-case-finalizers@audit",
        "instance_id": str(request["instance_id"]),
        "status": "success" if operation == "execute" else "ok",
        "evidence": [],
    }

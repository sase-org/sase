"""Reference non-mutating finalizer fixture."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def provider(request: Mapping[str, Any]) -> dict[str, Any]:
    operation = str(request["operation"])
    return {
        "schema_version": 1,
        "operation": operation,
        "provider_ref": "example-finalizers@audit",
        "instance_id": str(request["instance_id"]),
        "status": "success" if operation == "execute" else "ok",
        "evidence": [{"kind": "reference", "value": "non-mutating"}]
        if operation == "execute"
        else [],
    }

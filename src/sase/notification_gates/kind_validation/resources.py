"""Shared resource access helpers for gate kind validation."""

from __future__ import annotations

from sase.notification_gates.models import GateError, GateResource


def read_gate_resource(
    resource: GateResource, *, code: str, description: str
) -> str | None:
    """Return a gate resource's inline content or its on-disk source text."""
    try:
        if resource.content is not None:
            return resource.content
        if resource.source is not None:
            return resource.source.read_text(encoding="utf-8")
    except OSError as exc:
        raise GateError(
            code, resource.path, f"cannot read {description}: {exc}"
        ) from exc
    return None

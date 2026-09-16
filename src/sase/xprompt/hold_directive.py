"""Thin Python adapter for the shared Rust ``%hold`` contract."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from sase.core.rust import require_rust_binding

AGENT_HOLDS_FLAG = "agent_holds"

HOLD_POSITIONAL_SUGGESTIONS: tuple[str, ...] = ("pending", "future")
HOLD_KEYWORDS: tuple[str, ...] = ("hood", "scope", "ttl", "tribe")
HOLD_SCOPE_SUGGESTIONS: tuple[str, ...] = ("project", "host")


@dataclass(frozen=True)
class HoldFields:
    """Canonical `%hold` fields returned by the Rust parser."""

    names: tuple[str, ...] = field(default_factory=tuple)
    tribes: tuple[str, ...] = field(default_factory=tuple)
    hoods: tuple[str, ...] = field(default_factory=tuple)
    pending: bool = False
    future: bool = False
    ttl: str | None = None
    ttl_seconds: int | None = None
    scope: str | None = None

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any] | None) -> HoldFields | None:
        if data is None:
            return None
        return cls(
            names=tuple(str(item) for item in data.get("names", [])),
            tribes=tuple(str(item) for item in data.get("tribes", [])),
            hoods=tuple(str(item) for item in data.get("hoods", [])),
            pending=bool(data.get("pending", False)),
            future=bool(data.get("future", False)),
            ttl=None if data.get("ttl") is None else str(data["ttl"]),
            ttl_seconds=(
                None if data.get("ttl_seconds") is None else int(data["ttl_seconds"])
            ),
            scope=None if data.get("scope") is None else str(data["scope"]),
        )

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {}
        if self.names:
            data["names"] = list(self.names)
        if self.tribes:
            data["tribes"] = list(self.tribes)
        if self.hoods:
            data["hoods"] = list(self.hoods)
        if self.pending:
            data["pending"] = True
        if self.future:
            data["future"] = True
        if self.ttl is not None:
            data["ttl"] = self.ttl
        if self.ttl_seconds is not None:
            data["ttl_seconds"] = self.ttl_seconds
        if self.scope is not None:
            data["scope"] = self.scope
        return data


def agent_holds_enabled() -> bool:
    """Return whether the process-local ``agent_holds`` beta flag is enabled."""
    from sase.feature_flags.registry import FeatureFlag
    from sase.feature_flags.snapshot import current_flags

    return current_flags().enabled(FeatureFlag.agent_holds)


def collect_hold_fields(
    occurrences: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Validate and merge hold occurrences through the Rust contract."""
    from sase.xprompt.queue_directive import launch_feature_flag_keys

    binding = require_rust_binding("collect_hold_fields")
    try:
        payload = binding(list(occurrences), launch_feature_flag_keys())
    except TypeError:
        payload = binding(list(occurrences))
    if not isinstance(payload, dict):
        return {"fields": None, "errors": []}
    return dict(payload)


def format_hold_directive(fields: HoldFields | Mapping[str, Any] | None) -> str | None:
    """Return canonical ``%hold(...)`` for parsed fields."""
    if fields is None:
        return None
    payload = fields.to_dict() if isinstance(fields, HoldFields) else dict(fields)
    binding = require_rust_binding("format_hold_directive")
    formatted = binding(payload)
    return str(formatted) if formatted else None


def hold_fields_to_selectors(
    fields: HoldFields | Mapping[str, Any],
    pending_artifact_dirs: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Expand parsed hold fields into durable agent-hold selectors."""
    payload = fields.to_dict() if isinstance(fields, HoldFields) else dict(fields)
    binding = require_rust_binding("hold_fields_to_selectors")
    selectors = binding(payload, list(pending_artifact_dirs or ()))
    return dict(selectors) if isinstance(selectors, Mapping) else {}


__all__ = [
    "AGENT_HOLDS_FLAG",
    "HOLD_KEYWORDS",
    "HOLD_POSITIONAL_SUGGESTIONS",
    "HOLD_SCOPE_SUGGESTIONS",
    "HoldFields",
    "agent_holds_enabled",
    "collect_hold_fields",
    "format_hold_directive",
    "hold_fields_to_selectors",
]

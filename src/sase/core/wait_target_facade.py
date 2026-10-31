"""Typed thin adapter over the Rust wait-target vocabulary.

Parse, effective-target rules, and current-turn selection live in
``sase-core``. This module rehydrates wire payloads through
:func:`sase.core.rust.require_rust_binding` with no Python fallback.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from sase.core.rust import require_rust_binding

WaitTargetName = Literal["session", "turn"]
WaitReferenceKindName = Literal[
    "bare_agent",
    "exact_member",
    "clan",
    "tribe",
    "proc",
    "unresolved",
]
WaitScopeName = Literal[
    "session",
    "current_turn",
    "member",
    "single",
    "clan",
    "tribe",
    "name",
]


@dataclass(frozen=True, slots=True)
class EffectiveWaitTarget:
    """Effective target, whether it was explicit, and the binding scope."""

    target: WaitTargetName
    explicit: bool
    scope: WaitScopeName


@dataclass(frozen=True, slots=True)
class WaitTurnFacts:
    """One session member's facts for current-turn selection."""

    timestamp: str
    pending: bool = False
    excluded: bool = False

    def to_wire(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "pending": self.pending,
            "excluded": self.excluded,
        }


def parse_wait_target(raw: str) -> WaitTargetName:
    """Return ``session`` or ``turn`` for an exact, case-sensitive spelling."""
    binding = require_rust_binding("parse_wait_target")
    return _wait_target_name(binding(raw))


def effective_wait_target(
    *,
    requested: str | None,
    kind: WaitReferenceKindName,
    reference: str,
) -> EffectiveWaitTarget:
    """Apply the effective-target table for one classified reference."""
    binding = require_rust_binding("effective_wait_target")
    raw = binding(
        {
            "requested": requested,
            "kind": kind,
            "reference": reference,
        }
    )
    if not isinstance(raw, dict):
        raise TypeError("effective_wait_target returned a non-dict payload")
    return EffectiveWaitTarget(
        target=_wait_target_name(raw.get("target")),
        explicit=bool(raw.get("explicit")),
        scope=_wait_scope_name(raw.get("scope")),
    )


def select_current_wait_turn(
    members: Sequence[WaitTurnFacts | Mapping[str, Any]],
) -> int | None:
    """Return the input index of the current turn, or ``None``."""
    binding = require_rust_binding("select_current_wait_turn")
    raw = binding({"members": [_member_wire(member) for member in members]})
    if raw is None:
        return None
    return int(raw)


def wait_targets_with_descriptions() -> tuple[tuple[str, str], ...]:
    """Return the shared ``(value, description)`` table."""
    binding = require_rust_binding("wait_targets_with_descriptions")
    rows = binding()
    if not isinstance(rows, list):
        raise TypeError("wait_targets_with_descriptions returned a non-list")
    out: list[tuple[str, str]] = []
    for row in rows:
        if not isinstance(row, dict):
            raise TypeError("wait_targets_with_descriptions row is not a dict")
        out.append((str(row["value"]), str(row["description"])))
    return tuple(out)


def _member_wire(member: WaitTurnFacts | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(member, WaitTurnFacts):
        return member.to_wire()
    return {
        "timestamp": str(member.get("timestamp", "")),
        "pending": bool(member.get("pending", False)),
        "excluded": bool(member.get("excluded", False)),
    }


_WAIT_TARGETS: dict[str, WaitTargetName] = {
    "session": "session",
    "turn": "turn",
}
_WAIT_SCOPES: dict[str, WaitScopeName] = {
    "session": "session",
    "current_turn": "current_turn",
    "member": "member",
    "single": "single",
    "clan": "clan",
    "tribe": "tribe",
    "name": "name",
}


def _wait_target_name(value: object) -> WaitTargetName:
    resolved = _WAIT_TARGETS.get(str(value))
    if resolved is None:
        raise TypeError(f"unexpected wait target {value!r}")
    return resolved


def _wait_scope_name(value: object) -> WaitScopeName:
    resolved = _WAIT_SCOPES.get(str(value))
    if resolved is None:
        raise TypeError(f"unexpected wait scope {value!r}")
    return resolved


__all__ = [
    "EffectiveWaitTarget",
    "WaitTurnFacts",
    "effective_wait_target",
    "parse_wait_target",
    "select_current_wait_turn",
    "wait_targets_with_descriptions",
]

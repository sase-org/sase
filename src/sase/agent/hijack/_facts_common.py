"""Shared occupant-facts kernel for hijack resolution and decision."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sase.agent.hijack._stop_models import HijackTarget


@dataclass
class MemberFacts:
    """Durable and live facts for one possible session occupant."""

    member: Any
    name: str
    artifacts_dir: str
    timestamp: str
    meta: dict[str, Any]
    row: Any | None
    claim: Any | None
    status: str
    pid: int | None
    process_alive: bool
    done_outcome: str | None
    is_home: bool
    occupying_kind: str
    turn_phase: str | None
    finalizer_phase: str | None
    gate_state: str | None
    monitor_state: str | None
    settled: bool
    in_flight: bool
    waiting: bool


@dataclass
class HijackSubject:
    """One requested identity resolved to its current occupying member."""

    requested_name: str
    target: HijackTarget | None
    selected: MemberFacts | None
    context: MemberFacts | None
    members: tuple[MemberFacts, ...]
    session: Any | None
    occupant_reason: str
    is_session_container: bool
    is_named_proc: bool
    is_clan_container: bool
    is_remote: bool
    is_bulk: bool
    row: Any | None
    found: bool

    @property
    def occupant_name(self) -> str | None:
        return None if self.selected is None else self.selected.name


def eligibility_schema_version() -> int:
    from sase.agent.hijack.core import agent_hijack_eligibility_wire_schema_version

    return agent_hijack_eligibility_wire_schema_version()


def has_numbered_claim(claim: Any | None) -> bool:
    return positive_int(getattr(claim, "workspace_num", None)) is not None


def capabilities(meta: dict[str, Any]) -> list[str]:
    value = meta.get("runner_capabilities")
    return (
        [item for item in value if isinstance(item, str)]
        if isinstance(value, list)
        else []
    )


def positive_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return None
    return value


def nested_text(value: dict[str, Any], *keys: str) -> str | None:
    nested: Any = value
    for key in keys:
        nested = nested.get(key) if isinstance(nested, dict) else None
    return text(nested)


def text(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def value(data: Any, name: str, default: Any = None) -> Any:
    if isinstance(data, dict):
        return data.get(name, default)
    return getattr(data, name, default)


__all__ = [
    "HijackSubject",
    "MemberFacts",
    "capabilities",
    "eligibility_schema_version",
    "has_numbered_claim",
    "nested_text",
    "positive_int",
    "text",
    "value",
]

"""Shared result types for chop action lifecycle finalization."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AgentCompletion:
    """Terminal-state classification for one linked chop agent."""

    terminal: bool
    succeeded: bool
    detail: str


@dataclass(frozen=True)
class MatchedAgentRecord:
    """A registry record paired with the launch descriptor it matched."""

    record: object
    launch: dict[str, object]


@dataclass(frozen=True)
class TypedAdmissionReconciliation:
    """Typed-admission launch outcomes to merge into chop finalization."""

    applies: bool = False
    waiting: bool = False
    launches: list[dict[str, object]] | None = None
    failures: list[str] | None = None
    release_keys: list[str] | None = None
    success_detail: str = ""


__all__ = [
    "AgentCompletion",
    "MatchedAgentRecord",
    "TypedAdmissionReconciliation",
]

"""Shared result types for chop action lifecycle finalization."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class _AgentCompletion:
    terminal: bool
    succeeded: bool
    detail: str


@dataclass(frozen=True)
class _MatchedAgentRecord:
    record: object
    launch: dict[str, object]


@dataclass(frozen=True)
class _TypedAdmissionReconciliation:
    applies: bool = False
    waiting: bool = False
    launches: list[dict[str, object]] | None = None
    failures: list[str] | None = None
    release_keys: list[str] | None = None
    success_detail: str = ""

"""Shared types for runner-owned chop policy helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Protocol

ChopDecisionOutcome = Literal["fire", "skip", "check_error"]
ChopCheckpointEvent = Literal[
    "observed", "action_accepted", "action_succeeded", "action_failed"
]


@dataclass(frozen=True)
class ChopPreflight:
    """One normalized guard/trigger decision made before script dispatch."""

    outcome: ChopDecisionOutcome
    reason: str
    decision: dict[str, Any] | None = None
    checkpoint_enabled: bool = False


@dataclass(frozen=True)
class ChopOncePerOutcome:
    """Per-proposal once-per decisions for one structured chop result."""

    accepted_indices: tuple[int, ...]
    decisions: dict[int, dict[str, str]]
    effective_waits: dict[int, int | str | None]


class Proposal(Protocol):
    @property
    def index(self) -> int: ...

    @property
    def proposal_id(self) -> str | None: ...

    @property
    def workspace(self) -> str: ...

    @property
    def agent_name(self) -> str: ...

    @property
    def dedupe_key(self) -> str | None: ...

    @property
    def wait_on(self) -> int | str | None: ...


__all__ = [
    "ChopCheckpointEvent",
    "ChopDecisionOutcome",
    "ChopOncePerOutcome",
    "ChopPreflight",
    "Proposal",
]

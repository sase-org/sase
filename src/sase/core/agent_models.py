"""Required Rust-backed summaries of recorded concrete agent-turn models."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, dataclass
from typing import Literal

from sase.core.rust import require_rust_binding

AgentModelTurnKind = Literal["agent", "gate", "monitor", "other"]


@dataclass(frozen=True, slots=True)
class AgentModelTurnFact:
    """Recorded model facts for one turn in causal projection order."""

    kind: AgentModelTurnKind
    provider: str | None
    model: str | None


@dataclass(frozen=True, slots=True)
class AgentModelIdentity:
    """One normalized recorded provider/model identity."""

    provider: str | None
    model: str


@dataclass(frozen=True, slots=True)
class AgentModelSummary:
    """Distinct models, latest use, and turns without recorded model facts."""

    models: tuple[AgentModelIdentity, ...]
    latest: AgentModelIdentity | None
    unknown_turn_count: int


def summarize_agent_models(
    turns: Sequence[AgentModelTurnFact],
) -> AgentModelSummary:
    """Summarize an already ordered session projection in the required Rust core."""
    payload = require_rust_binding("summarize_agent_models")(
        {"turns": [asdict(turn) for turn in turns]}
    )
    models = tuple(
        AgentModelIdentity(
            provider=_optional_text(value.get("provider")),
            model=str(value.get("model", "")),
        )
        for value in payload.get("models", ())
        if isinstance(value, dict)
    )
    latest_value = payload.get("latest")
    latest = (
        AgentModelIdentity(
            provider=_optional_text(latest_value.get("provider")),
            model=str(latest_value.get("model", "")),
        )
        if isinstance(latest_value, dict)
        else None
    )
    return AgentModelSummary(
        models=models,
        latest=latest,
        unknown_turn_count=int(payload.get("unknown_turn_count", 0)),
    )


def _optional_text(value: object) -> str | None:
    return value if isinstance(value, str) else None


__all__ = [
    "AgentModelIdentity",
    "AgentModelSummary",
    "AgentModelTurnFact",
    "AgentModelTurnKind",
    "summarize_agent_models",
]

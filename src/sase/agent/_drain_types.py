"""Types shared by the provider-drain planning and execution modules.

Planning is read-only, so a refusal is a :class:`ProviderDrainError` raised
before anything is killed; execution reports every later failure as an
:class:`AgentRestartOutcome` status inside :class:`ProviderDrainOutcome`
instead, mirroring how ``sase.agent.restart`` never raises for one bad row.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from sase.agent.restart import AgentRestartOutcome, AgentRestartPlan
from sase.llm_provider.provider_disable import TemporaryProviderDisable

DrainRouteKind = Literal["reroute", "stranded"]


class ProviderDrainError(Exception):
    """A drain that was refused before any mutation."""

    def __init__(self, *, reason: str, message: str, hint: str = "") -> None:
        super().__init__(message)
        self.reason = reason
        self.message = message
        self.hint = hint


@dataclass(frozen=True)
class DrainRoute:
    """Where one agent would land if its drain move ran."""

    kind: DrainRouteKind
    target_provider: str | None
    target_model: str | None


@dataclass(frozen=True)
class ProviderDrainMove:
    """One agent a drain plan will restart."""

    name: str
    presented_name: str
    project: str
    status: str
    route: DrainRoute
    restart_plan: AgentRestartPlan


@dataclass(frozen=True)
class ProviderDrainSkip:
    """One agent a drain plan will not touch, and why.

    ``reason`` is a closed set of slugs: ``monitor``, ``pending_question``,
    ``caller``, ``stranded``, ``capped``, plus every
    :class:`~sase.agent.restart.AgentRestartError` ``reason`` value passed
    through verbatim from a refused per-agent restart plan.
    """

    name: str
    presented_name: str
    status: str
    reason: str
    detail: str


@dataclass(frozen=True)
class ProviderDrainPlan:
    """A validated, not-yet-applied provider drain."""

    provider: str
    disable: TemporaryProviderDisable
    moves: tuple[ProviderDrainMove, ...]
    skips: tuple[ProviderDrainSkip, ...]
    model_override: str | None
    limit: int


@dataclass(frozen=True)
class ProviderDrainOutcome:
    """Result of applying a provider drain plan."""

    plan: ProviderDrainPlan
    results: tuple[AgentRestartOutcome, ...]

    @property
    def relaunched(self) -> int:
        """Count of moves that fully succeeded."""
        return sum(1 for result in self.results if result.status == "ok")

    @property
    def failed(self) -> int:
        """Count of moves that did not fully succeed."""
        return sum(1 for result in self.results if result.status != "ok")

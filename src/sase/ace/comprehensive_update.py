"""Typed terminal state for ACE's snapshot-gated comprehensive update."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from sase.agent_clis.models import AgentCliUpdateResult, UpdateResultStatus
from sase.agents_sync.models import CachedIntegrationResult
from sase.dev_update.models import DevUpdateResult
from sase.main.update_types import CombinedUpdateResult
from sase.uv_tool.render import UpdateSummary


class SaseUpdateResultStatus(StrEnum):
    """Terminal state of the SASE/core/plugin leg."""

    UPDATED = "updated"
    ALREADY_CURRENT = "already_current"
    SKIPPED = "skipped"
    FAILED = "failed"


SaseUpdatePayload = UpdateSummary | DevUpdateResult | CombinedUpdateResult


@dataclass(frozen=True)
class ComprehensiveSaseUpdateResult:
    """Independent terminal outcome of the SASE/core/plugin leg."""

    status: SaseUpdateResultStatus
    message: str
    payload: SaseUpdatePayload | None = None

    @property
    def changed(self) -> bool:
        """Return whether this leg changed installed SASE code."""
        return bool(getattr(self.payload, "changed", False))


@dataclass(frozen=True)
class ComprehensiveUpdateResult:
    """Aggregate terminal outcome of one tracked comprehensive update."""

    sase: ComprehensiveSaseUpdateResult
    provider_results: tuple[AgentCliUpdateResult, ...] = ()
    provider_error: str | None = None
    agents_outcomes: tuple[CachedIntegrationResult, ...] = ()
    agents_error: str | None = None
    elapsed: float = 0.0

    @property
    def code_changed(self) -> bool:
        """Code changes are defined solely by the SASE/core/plugin leg."""
        return self.sase.changed

    @property
    def has_failures(self) -> bool:
        """Return whether any independent leg reported a failure."""
        return bool(
            self.sase.status is SaseUpdateResultStatus.FAILED
            or self.provider_error
            or self.agents_error
            or any(
                result.status is UpdateResultStatus.FAILED
                for result in self.provider_results
            )
            or any(not outcome.ok for outcome in self.agents_outcomes)
        )

    @property
    def has_successful_provider_change(self) -> bool:
        return any(
            result.status is UpdateResultStatus.UPDATED
            for result in self.provider_results
        )

    @property
    def has_successful_agents_change(self) -> bool:
        return any(outcome.disposition == "applied" for outcome in self.agents_outcomes)

    @property
    def fully_failed(self) -> bool:
        """Return whether the run failed without changing either leg."""
        return self.has_failures and not (
            self.code_changed
            or self.has_successful_provider_change
            or self.has_successful_agents_change
        )


__all__ = [
    "ComprehensiveSaseUpdateResult",
    "ComprehensiveUpdateResult",
    "SaseUpdatePayload",
    "SaseUpdateResultStatus",
]

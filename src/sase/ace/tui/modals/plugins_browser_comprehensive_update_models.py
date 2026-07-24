"""Shared models for the comprehensive Updates-pane flow."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sase.agent_clis.models import (
    AgentCliUpdatePlan,
    AgentCliUpdatesReady,
    UpdateStrategy,
)
from sase.agents_sync.models import CapturedIncomingHood

from .plugins_browser_dev_update import DevUpdatePreview


@dataclass(frozen=True)
class ComprehensiveUpdateRequest:
    """One immutable provider projection captured by ``,U`` dispatch."""

    provider_names: tuple[str, ...] | None


@dataclass(frozen=True)
class DroppedProviderCandidate:
    """Captured provider identity that no longer exists in live inventory."""

    name: str
    reason: str = "no longer present in the live provider inventory"


@dataclass(frozen=True)
class ComprehensiveUpdatePreview:
    """Independent SASE and provider plans for one confirmation."""

    request: ComprehensiveUpdateRequest
    sase_preview: DevUpdatePreview | None
    sase_current: bool = False
    sase_blocker: str | None = None
    provider_plan: AgentCliUpdatePlan | None = None
    provider_dropped: tuple[DroppedProviderCandidate, ...] = ()
    provider_error: str | None = None
    agents_updates: tuple[CapturedIncomingHood, ...] = ()
    agents_error: str | None = None

    @property
    def provider_runnable(self) -> bool:
        return isinstance(self.provider_plan, AgentCliUpdatesReady) and bool(
            self.provider_plan.runnable_entries
        )

    @property
    def sase_runnable(self) -> bool:
        return bool(
            not self.sase_current
            and self.sase_blocker is None
            and self.sase_preview is not None
        )

    @property
    def runnable(self) -> bool:
        return self.sase_runnable or self.provider_runnable or self.agents_runnable

    @property
    def agents_runnable(self) -> bool:
        """Only the immutable cache items captured for confirmation may run."""
        return bool(self.agents_updates)

    @property
    def manual_provider_entries(self) -> tuple[Any, ...]:
        entries = getattr(self.provider_plan, "entries", ())
        return tuple(
            entry
            for entry in entries
            if entry.strategy is UpdateStrategy.MANUAL or entry.manual_argv is not None
        )


def error_text(error: Exception) -> str:
    """Return a useful message even for exceptions whose string is empty."""
    return str(error).strip() or type(error).__name__

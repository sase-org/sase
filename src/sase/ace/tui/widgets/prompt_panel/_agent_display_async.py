"""Async worker composition for the agent prompt panel display."""

from __future__ import annotations

from collections.abc import Callable, Collection
from typing import Any

from textual.worker import Worker

from ...models._agent_clan_sections import (
    ClanDiskSection,
    ClanDiskSnapshot,
    ClanInMemorySnapshot,
)
from ...models.agent import Agent
from ...models.agent_tribe_summary import TribePanelIdentity
from ...models.agent_bead import resolve_bead_display, should_resolve_bead_display
from ._agent_clan_aggregation import build_clan_disk_snapshot
from ._agent_display_async_agent import AgentDisplayAgentWorkerMixin
from ._agent_display_async_groups import AgentDisplayGroupWorkerMixin
from ._agent_display_async_types import AgentDetailRenderContext
from ._agent_display_header_summary import (
    build_detail_header_summary,
    should_refresh_detail_header_summary,
)
from ._agent_display_state import DetailContextLane
from ._agent_tribe_aggregation import (
    TribeEnrichmentResult,
    TribeEnrichmentSection,
    TribeUnitSource,
    build_tribe_enrichment,
)
from ..file_panel._linked_deltas import (
    compute_linked_delta_groups,
    should_refresh_linked_delta_groups,
)


class AgentDisplayWorkerMixin(
    AgentDisplayGroupWorkerMixin,
    AgentDisplayAgentWorkerMixin,
):
    """Compose all async workers used by ``AgentPromptPanel``."""

    def set_agent_detail_render_context(
        self,
        *,
        generation: int,
        attempt_view_mode: str,
        attempt_pinned_number: int | None,
        is_current: Callable[[tuple[Any, ...], int, str, int | None], bool],
    ) -> None:
        """Capture AgentDetail state used by async prompt-panel workers."""
        self._agent_detail_render_context = AgentDetailRenderContext(  # type: ignore[attr-defined]
            generation=generation,
            attempt_view_mode=attempt_view_mode,
            attempt_pinned_number=attempt_pinned_number,
            is_current=is_current,
        )

    def _build_clan_disk_snapshot(
        self,
        agent: Agent,
        in_memory: ClanInMemorySnapshot,
        *,
        sections: Collection[ClanDiskSection],
        slow_tool_threshold_ms: int,
    ) -> ClanDiskSnapshot:
        """Keep the historical builder patch point at the composition boundary."""
        return build_clan_disk_snapshot(
            self,
            agent,
            in_memory,
            sections=sections,
            slow_tool_threshold_ms=slow_tool_threshold_ms,
        )

    def _build_tribe_enrichment(
        self,
        panel_identity: TribePanelIdentity,
        sources: tuple[TribeUnitSource, ...],
        *,
        sections: Collection[TribeEnrichmentSection],
        slow_tool_threshold_ms: int,
    ) -> TribeEnrichmentResult:
        """Keep the historical builder patch point at the composition boundary."""
        return build_tribe_enrichment(
            self,
            panel_identity,
            sources,
            sections=sections,
            slow_tool_threshold_ms=slow_tool_threshold_ms,
        )

    def _should_refresh_detail_header_summary(
        self, agent: Agent
    ) -> frozenset[DetailContextLane]:
        """Keep the historical refresh-decision patch point stable."""
        return should_refresh_detail_header_summary(self, agent)

    def _build_detail_header_summary(self, agent: Agent) -> object:
        """Keep the historical header-builder patch point stable."""
        return build_detail_header_summary(agent)

    @staticmethod
    def _should_resolve_bead_display(agent: Agent) -> bool:
        return should_resolve_bead_display(agent)

    @staticmethod
    def _resolve_bead_display(agent: Agent) -> str | None:
        return resolve_bead_display(agent)

    @staticmethod
    def _should_refresh_linked_delta_groups(agent: Agent) -> bool:
        return should_refresh_linked_delta_groups(agent)

    @staticmethod
    def _compute_linked_delta_groups(agent: Agent) -> object:
        return compute_linked_delta_groups(agent)

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        """Apply async worker results while preserving later MRO handlers."""
        handler = getattr(super(), "on_worker_state_changed", None)
        if callable(handler):
            handler(event)
        self._apply_agent_bead_display_worker_result(event.worker, event.state)
        self._apply_agent_linked_delta_worker_result(event.worker, event.state)
        self._apply_agent_detail_header_enrichment_result(event.worker, event.state)
        self._apply_clan_section_enrichment_result(event.worker, event.state)
        self._apply_tribe_section_enrichment_result(event.worker, event.state)

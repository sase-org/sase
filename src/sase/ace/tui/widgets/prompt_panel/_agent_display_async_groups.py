"""Clan and tribe workers for the agent prompt panel display."""

from __future__ import annotations

from collections.abc import Callable, Collection
from typing import Any, cast

from textual.worker import Worker, WorkerState

from ...models._agent_clan_sections import (
    CLAN_DISK_SECTIONS,
    ClanDiskSection,
    ClanDiskSnapshot,
    ClanInMemorySnapshot,
)
from ...models.agent import Agent
from ...models.agent_tribe_summary import TribePanelIdentity
from ._agent_clan_aggregation import (
    cache_clan_disk_snapshot,
    clear_clan_snapshot_loading,
    get_cached_clan_section_snapshot,
    mark_clan_snapshot_loading,
    should_refresh_clan_disk_snapshot,
)
from ._agent_display_async_types import (
    AgentDetailRenderContext,
    ClanSectionEnrichmentRequest,
    TribeSectionEnrichmentRequest,
)
from ._agent_tribe_aggregation import (
    TribeEnrichmentResult,
    TribeEnrichmentSection,
    cache_tribe_enrichment,
    clear_tribe_snapshot_loading,
    get_cached_tribe_sources,
    mark_tribe_snapshot_loading,
    tribe_sections_to_refresh,
)
from ._messages import ClanSectionSnapshotLoaded, TribeSectionSnapshotLoaded


class AgentDisplayGroupWorkerMixin:
    """Async clan and tribe workers for ``AgentPromptPanel``."""

    _tribe_section_pending_request: TribeSectionEnrichmentRequest | None = None

    def set_clan_disk_sections_required(
        self,
        sections: Collection[str],
    ) -> None:
        """Set disk sections required by the current fold-aware clan render.

        The collapsed renderer leaves this empty. The rendering phase can set
        the effective non-collapsed sections before calling ``update_display``
        without coupling this data layer to a particular fold-state owner.
        """
        self._clan_disk_sections_required = _normalize_clan_disk_sections(  # type: ignore[attr-defined]
            sections
        )

    def _clan_disk_sections_from_context(
        self,
        agent: Agent,
    ) -> frozenset[ClanDiskSection]:
        sections: object = getattr(
            self,
            "_clan_disk_sections_required",
            frozenset(),
        )
        try:
            app = self.app  # type: ignore[attr-defined]
        except Exception:
            app = None
        resolver = getattr(app, "clan_disk_sections_for_agent", None)
        if callable(resolver):
            sections = resolver(agent)
        return _normalize_clan_disk_sections(sections)

    def _start_clan_section_enrichment_from_context(self, agent: Agent) -> None:
        context: AgentDetailRenderContext | None = getattr(
            self, "_agent_detail_render_context", None
        )
        if context is None or context.attempt_pinned_number is not None:
            return
        sections = self._clan_disk_sections_from_context(agent)
        if not sections or not should_refresh_clan_disk_snapshot(
            self,
            agent,
            sections,
        ):
            return
        snapshot = get_cached_clan_section_snapshot(self, agent)
        if snapshot is None:
            return
        from ...tools.slow import slow_tool_call_threshold_ms_from_widget

        self.start_clan_section_enrichment(
            agent,
            in_memory=snapshot.in_memory,
            sections=sections,
            slow_tool_threshold_ms=slow_tool_call_threshold_ms_from_widget(self),
            generation=context.generation,
            attempt_view_mode=context.attempt_view_mode,
            attempt_pinned_number=context.attempt_pinned_number,
            is_current=context.is_current,
        )

    def start_clan_section_enrichment(
        self,
        agent: Agent,
        *,
        in_memory: ClanInMemorySnapshot,
        sections: Collection[ClanDiskSection],
        slow_tool_threshold_ms: int,
        generation: int,
        attempt_view_mode: str,
        attempt_pinned_number: int | None,
        is_current: Callable[[tuple[Any, ...], int, str, int | None], bool],
    ) -> None:
        """Load clan member artifacts in one coalesced worker thread."""
        run_worker = getattr(self, "run_worker", None)
        requested = frozenset(sections)
        if not callable(run_worker) or not requested:
            return
        request = ClanSectionEnrichmentRequest(
            agent=agent,
            agent_identity=agent.identity,
            in_memory=in_memory,
            sections=requested,
            slow_tool_threshold_ms=slow_tool_threshold_ms,
            generation=generation,
            attempt_view_mode=attempt_view_mode,
            attempt_pinned_number=attempt_pinned_number,
            is_current=is_current,
        )
        current_worker = getattr(self, "_clan_section_worker", None)
        if current_worker is not None and getattr(current_worker, "is_running", False):
            current_request: ClanSectionEnrichmentRequest | None = getattr(
                self,
                "_clan_section_request",
                None,
            )
            if (
                current_request is not None
                and current_request.agent_identity == request.agent_identity
                and request.sections.issubset(current_request.sections)
            ):
                self._clan_section_request = request  # type: ignore[attr-defined]
                return
            current_worker.cancel()

        mark_clan_snapshot_loading(self, agent, requested)

        def load_task() -> ClanDiskSnapshot:
            return self._build_clan_disk_snapshot(  # type: ignore[attr-defined,no-any-return]
                agent,
                in_memory,
                sections=requested,
                slow_tool_threshold_ms=slow_tool_threshold_ms,
            )

        self._clan_section_request = request  # type: ignore[attr-defined]
        self._clan_section_worker = run_worker(load_task, thread=True)  # type: ignore[attr-defined]

    def _cancel_clan_section_worker_for_selection_change(self, agent: Agent) -> None:
        current_worker = getattr(self, "_clan_section_worker", None)
        if current_worker is None or not getattr(current_worker, "is_running", False):
            return
        current_request: ClanSectionEnrichmentRequest | None = getattr(
            self,
            "_clan_section_request",
            None,
        )
        if current_request is None or current_request.agent_identity != agent.identity:
            current_worker.cancel()

    def start_tribe_section_enrichment(
        self,
        panel_identity: TribePanelIdentity,
        *,
        sections: Collection[TribeEnrichmentSection],
        slow_tool_threshold_ms: int,
    ) -> None:
        """Load tribe sections in one coalesced, last-request-wins worker."""
        requested = tribe_sections_to_refresh(self, panel_identity, sections)
        run_worker = getattr(self, "run_worker", None)
        if not requested or not callable(run_worker):
            return
        request = TribeSectionEnrichmentRequest(
            panel_identity=panel_identity,
            sources=get_cached_tribe_sources(self, panel_identity),
            sections=requested,
            slow_tool_threshold_ms=slow_tool_threshold_ms,
        )
        current_worker = getattr(self, "_tribe_section_worker", None)
        if current_worker is not None and getattr(current_worker, "is_running", False):
            current_request: TribeSectionEnrichmentRequest | None = getattr(
                self, "_tribe_section_request", None
            )
            if (
                current_request is not None
                and current_request.panel_identity == request.panel_identity
                and tuple(source.signature for source in current_request.sources)
                == tuple(source.signature for source in request.sources)
                and request.sections.issubset(current_request.sections)
            ):
                pending = self._tribe_section_pending_request
                if pending is not None:
                    clear_tribe_snapshot_loading(
                        self,
                        pending.panel_identity,
                        pending.sections,
                    )
                    self._tribe_section_pending_request = None
                return
            pending = self._tribe_section_pending_request
            if pending is not None:
                clear_tribe_snapshot_loading(
                    self,
                    pending.panel_identity,
                    pending.sections,
                )
            mark_tribe_snapshot_loading(self, panel_identity, requested)
            self._tribe_section_pending_request = request
            return
        self._launch_tribe_section_enrichment(request)

    def _launch_tribe_section_enrichment(
        self,
        request: TribeSectionEnrichmentRequest,
    ) -> None:
        run_worker = getattr(self, "run_worker", None)
        if not callable(run_worker):
            return
        mark_tribe_snapshot_loading(
            self,
            request.panel_identity,
            request.sections,
        )

        def load_task() -> TribeEnrichmentResult:
            return self._build_tribe_enrichment(  # type: ignore[attr-defined,no-any-return]
                request.panel_identity,
                request.sources,
                sections=request.sections,
                slow_tool_threshold_ms=request.slow_tool_threshold_ms,
            )

        self._tribe_section_request = request  # type: ignore[attr-defined]
        self._tribe_section_worker = run_worker(load_task, thread=True)  # type: ignore[attr-defined]

    def _cancel_tribe_section_worker_for_agent_selection(self) -> None:
        """Cancel tribe-only work after selection returns to a real row."""
        pending = self._tribe_section_pending_request
        if pending is not None:
            clear_tribe_snapshot_loading(
                self,
                pending.panel_identity,
                pending.sections,
            )
        self._tribe_section_pending_request = None
        current_worker = getattr(self, "_tribe_section_worker", None)
        current_request: TribeSectionEnrichmentRequest | None = getattr(
            self, "_tribe_section_request", None
        )
        if current_request is not None:
            clear_tribe_snapshot_loading(
                self,
                current_request.panel_identity,
                current_request.sections,
            )
        if current_worker is not None and getattr(current_worker, "is_running", False):
            current_worker.cancel()

    def _apply_tribe_section_enrichment_result(
        self,
        worker: Worker[Any],
        state: WorkerState,
    ) -> None:
        current_worker = getattr(self, "_tribe_section_worker", None)
        if worker != current_worker:
            return
        request: TribeSectionEnrichmentRequest | None = getattr(
            self, "_tribe_section_request", None
        )
        terminal = state in (
            WorkerState.SUCCESS,
            WorkerState.ERROR,
            WorkerState.CANCELLED,
        )
        if not terminal:
            return
        self._tribe_section_worker = None  # type: ignore[attr-defined]
        if request is not None:
            clear_tribe_snapshot_loading(
                self,
                request.panel_identity,
                request.sections,
            )
        if state is WorkerState.SUCCESS and request is not None:
            result = cast(TribeEnrichmentResult, worker.result)
            if cache_tribe_enrichment(self, result) is not None:
                post_message = getattr(self, "post_message", None)
                if callable(post_message):
                    post_message(TribeSectionSnapshotLoaded(request.panel_identity))
        pending: TribeSectionEnrichmentRequest | None = getattr(
            self, "_tribe_section_pending_request", None
        )
        self._tribe_section_pending_request = None
        if pending is not None:
            self.start_tribe_section_enrichment(
                pending.panel_identity,
                sections=pending.sections,
                slow_tool_threshold_ms=pending.slow_tool_threshold_ms,
            )

    def _apply_clan_section_enrichment_result(
        self,
        worker: Worker[Any],
        state: WorkerState,
    ) -> None:
        current_worker = getattr(self, "_clan_section_worker", None)
        if worker != current_worker:
            return
        request: ClanSectionEnrichmentRequest | None = getattr(
            self,
            "_clan_section_request",
            None,
        )
        if state in (WorkerState.SUCCESS, WorkerState.ERROR, WorkerState.CANCELLED):
            self._clan_section_worker = None  # type: ignore[attr-defined]
            if request is not None:
                clear_clan_snapshot_loading(self, request.agent)
        if state != WorkerState.SUCCESS or request is None:
            return
        if not request.is_current(
            request.agent_identity,
            request.generation,
            request.attempt_view_mode,
            request.attempt_pinned_number,
        ):
            return
        disk = cast(ClanDiskSnapshot, worker.result)
        if cache_clan_disk_snapshot(self, request.agent, disk) is None:
            return
        post_message = getattr(self, "post_message", None)
        if callable(post_message):
            post_message(ClanSectionSnapshotLoaded(request.agent_identity))


def _normalize_clan_disk_sections(
    sections: Collection[str] | object,
) -> frozenset[ClanDiskSection]:
    if not isinstance(sections, Collection) or isinstance(sections, (str, bytes)):
        return frozenset()
    return frozenset(
        cast(ClanDiskSection, section)
        for section in sections
        if isinstance(section, str) and section in CLAN_DISK_SECTIONS
    )

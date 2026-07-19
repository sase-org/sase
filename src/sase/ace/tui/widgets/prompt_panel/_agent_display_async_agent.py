"""Per-agent workers for the agent prompt panel display."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from typing import Any, cast

from textual.worker import Worker, WorkerState

from ...models.agent import Agent
from ...models.agent_bead import cached_bead_display, resolve_bead_display
from ._agent_display_async_types import (
    AgentDetailRenderContext,
    BeadDisplayResolveRequest,
    DetailHeaderEnrichmentRequest,
    LinkedDeltaResolveRequest,
)
from ._agent_display_header_summary import (
    cache_detail_header_summary,
    get_cached_detail_header_summary,
)
from ._messages import AgentDetailHeaderEnriched
from ..file_panel._messages import LinkedDeltasRefreshed


class AgentDisplayAgentWorkerMixin:
    """Async enrichment workers for individual agent rows."""

    def _start_agent_bead_display_resolve_from_context(self, agent: Agent) -> None:
        context: AgentDetailRenderContext | None = getattr(
            self, "_agent_detail_render_context", None
        )
        if context is None or context.attempt_pinned_number is not None:
            return
        if not self._should_resolve_bead_display(agent):  # type: ignore[attr-defined]
            return

        self.start_agent_bead_display_resolve(
            agent,
            generation=context.generation,
            attempt_view_mode=context.attempt_view_mode,
            attempt_pinned_number=context.attempt_pinned_number,
            is_current=context.is_current,
        )

    def _start_agent_linked_delta_refresh_from_context(self, agent: Agent) -> None:
        context: AgentDetailRenderContext | None = getattr(
            self, "_agent_detail_render_context", None
        )
        if context is None or context.attempt_pinned_number is not None:
            return
        if not self._should_refresh_linked_delta_groups(agent):  # type: ignore[attr-defined]
            return

        self.start_agent_linked_delta_refresh(
            agent,
            generation=context.generation,
            attempt_view_mode=context.attempt_view_mode,
            attempt_pinned_number=context.attempt_pinned_number,
            is_current=context.is_current,
        )

    def _start_agent_detail_header_enrichment_from_context(self, agent: Agent) -> None:
        context: AgentDetailRenderContext | None = getattr(
            self, "_agent_detail_render_context", None
        )
        if context is None or context.attempt_pinned_number is not None:
            return
        if not self._should_refresh_detail_header_summary(  # type: ignore[attr-defined]
            agent
        ):
            return

        self.start_agent_detail_header_enrichment(
            agent,
            generation=context.generation,
            attempt_view_mode=context.attempt_view_mode,
            attempt_pinned_number=context.attempt_pinned_number,
            is_current=context.is_current,
        )

    def start_agent_detail_header_enrichment(
        self,
        agent: Agent,
        *,
        generation: int,
        attempt_view_mode: str,
        attempt_pinned_number: int | None,
        is_current: Callable[[tuple[Any, ...], int, str, int | None], bool],
    ) -> None:
        """Build expensive detail-header metadata in a worker thread."""
        run_worker = getattr(self, "run_worker", None)
        if not callable(run_worker):
            return

        request = DetailHeaderEnrichmentRequest(
            agent=agent,
            agent_identity=agent.identity,
            generation=generation,
            attempt_view_mode=attempt_view_mode,
            attempt_pinned_number=attempt_pinned_number,
            is_current=is_current,
        )

        current_worker = getattr(self, "_agent_detail_header_worker", None)
        if current_worker is not None and getattr(current_worker, "is_running", False):
            current_request: DetailHeaderEnrichmentRequest | None = getattr(
                self,
                "_agent_detail_header_request",
                None,
            )
            if (
                current_request is not None
                and current_request.agent_identity == request.agent_identity
                and current_request.attempt_view_mode == request.attempt_view_mode
                and current_request.attempt_pinned_number
                == request.attempt_pinned_number
            ):
                self._agent_detail_header_request = request  # type: ignore[attr-defined]
                return
            current_worker.cancel()

        def enrich_task() -> object:
            return self._build_detail_header_summary(agent)  # type: ignore[attr-defined,no-any-return]

        self._agent_detail_header_request = request  # type: ignore[attr-defined]
        self._agent_detail_header_worker = run_worker(  # type: ignore[attr-defined]
            enrich_task, thread=True
        )

    def _cancel_agent_detail_header_worker_for_selection_change(
        self,
        agent: Agent,
    ) -> None:
        current_worker = getattr(self, "_agent_detail_header_worker", None)
        if current_worker is None or not getattr(current_worker, "is_running", False):
            return
        current_request: DetailHeaderEnrichmentRequest | None = getattr(
            self,
            "_agent_detail_header_request",
            None,
        )
        if current_request is None or current_request.agent_identity != agent.identity:
            current_worker.cancel()

    def start_agent_linked_delta_refresh(
        self,
        agent: Agent,
        *,
        generation: int,
        attempt_view_mode: str,
        attempt_pinned_number: int | None,
        is_current: Callable[[tuple[Any, ...], int, str, int | None], bool],
    ) -> None:
        """Refresh linked-repo deltas in a worker thread."""
        run_worker = getattr(self, "run_worker", None)
        if not callable(run_worker):
            return

        request = LinkedDeltaResolveRequest(
            agent=agent,
            agent_identity=agent.identity,
            generation=generation,
            attempt_view_mode=attempt_view_mode,
            attempt_pinned_number=attempt_pinned_number,
            is_current=is_current,
        )

        current_worker = getattr(self, "_agent_linked_delta_worker", None)
        if current_worker is not None and getattr(current_worker, "is_running", False):
            current_request: LinkedDeltaResolveRequest | None = getattr(
                self,
                "_agent_linked_delta_request",
                None,
            )
            if (
                current_request is not None
                and current_request.agent_identity == request.agent_identity
                and current_request.attempt_view_mode == request.attempt_view_mode
                and current_request.attempt_pinned_number
                == request.attempt_pinned_number
            ):
                self._agent_linked_delta_request = request  # type: ignore[attr-defined]
                return
            current_worker.cancel()

        def resolve_task() -> object:
            return self._compute_linked_delta_groups(agent)  # type: ignore[attr-defined,no-any-return]

        self._agent_linked_delta_request = request  # type: ignore[attr-defined]
        self._agent_linked_delta_worker = run_worker(  # type: ignore[attr-defined]
            resolve_task, thread=True
        )

    def _cancel_agent_linked_delta_worker_for_selection_change(
        self,
        agent: Agent,
    ) -> None:
        current_worker = getattr(self, "_agent_linked_delta_worker", None)
        if current_worker is None or not getattr(current_worker, "is_running", False):
            return
        current_request: LinkedDeltaResolveRequest | None = getattr(
            self,
            "_agent_linked_delta_request",
            None,
        )
        if current_request is None or current_request.agent_identity != agent.identity:
            current_worker.cancel()

    def start_agent_bead_display_resolve(
        self,
        agent: Agent,
        *,
        generation: int,
        attempt_view_mode: str,
        attempt_pinned_number: int | None,
        is_current: Callable[[tuple[Any, ...], int, str, int | None], bool],
    ) -> None:
        """Resolve a bead description in a worker thread and re-render on success."""
        run_worker = getattr(self, "run_worker", None)
        if not callable(run_worker):
            return

        request = BeadDisplayResolveRequest(
            agent=agent,
            agent_identity=agent.identity,
            generation=generation,
            attempt_view_mode=attempt_view_mode,
            attempt_pinned_number=attempt_pinned_number,
            is_current=is_current,
        )

        current_worker = getattr(self, "_agent_bead_display_worker", None)
        if current_worker is not None and getattr(current_worker, "is_running", False):
            current_request: BeadDisplayResolveRequest | None = getattr(
                self, "_agent_bead_display_request", None
            )
            if (
                current_request is not None
                and current_request.agent_identity == request.agent_identity
                and current_request.attempt_view_mode == request.attempt_view_mode
                and current_request.attempt_pinned_number
                == request.attempt_pinned_number
            ):
                self._agent_bead_display_request = request  # type: ignore[attr-defined]
                return
            current_worker.cancel()

        def resolve_task() -> str | None:
            return self._resolve_bead_display(agent)  # type: ignore[attr-defined,no-any-return]

        self._agent_bead_display_request = request  # type: ignore[attr-defined]
        self._agent_bead_display_worker = run_worker(  # type: ignore[attr-defined]
            resolve_task, thread=True
        )

    def _cancel_agent_bead_display_worker_for_selection_change(
        self, agent: Agent
    ) -> None:
        current_worker = getattr(self, "_agent_bead_display_worker", None)
        if current_worker is None or not getattr(current_worker, "is_running", False):
            return
        current_request: BeadDisplayResolveRequest | None = getattr(
            self, "_agent_bead_display_request", None
        )
        if current_request is None or current_request.agent_identity != agent.identity:
            current_worker.cancel()

    def _apply_agent_detail_header_enrichment_result(
        self, worker: Worker[Any], state: WorkerState
    ) -> None:
        current_worker = getattr(self, "_agent_detail_header_worker", None)
        if worker != current_worker:
            return

        if state in (WorkerState.SUCCESS, WorkerState.ERROR, WorkerState.CANCELLED):
            self._agent_detail_header_worker = None  # type: ignore[attr-defined]

        if state != WorkerState.SUCCESS:
            return

        request: DetailHeaderEnrichmentRequest | None = getattr(
            self,
            "_agent_detail_header_request",
            None,
        )
        if request is None:
            return
        summary = cast(Any, worker.result)
        cache_detail_header_summary(self, request.agent, summary)

        if not request.is_current(
            request.agent_identity,
            request.generation,
            request.attempt_view_mode,
            request.attempt_pinned_number,
        ):
            return

        post_message = getattr(self, "post_message", None)
        if callable(post_message):
            post_message(AgentDetailHeaderEnriched(request.agent_identity))
        else:
            # Mixin-only consumers have no Textual message path.
            self._update_display_impl(request.agent)  # type: ignore[attr-defined]
        configure_slow_tick = getattr(self, "_configure_slow_tool_render_tick", None)
        if callable(configure_slow_tick):
            configure_slow_tick(request.agent)

    def _apply_agent_linked_delta_worker_result(
        self, worker: Worker[Any], state: WorkerState
    ) -> None:
        current_worker = getattr(self, "_agent_linked_delta_worker", None)
        if worker != current_worker:
            return

        if state in (WorkerState.SUCCESS, WorkerState.ERROR, WorkerState.CANCELLED):
            self._agent_linked_delta_worker = None  # type: ignore[attr-defined]

        if state != WorkerState.SUCCESS:
            return

        request: LinkedDeltaResolveRequest | None = getattr(
            self,
            "_agent_linked_delta_request",
            None,
        )
        if request is None:
            return
        if not request.is_current(
            request.agent_identity,
            request.generation,
            request.attempt_view_mode,
            request.attempt_pinned_number,
        ):
            return

        self._update_display_impl(request.agent)  # type: ignore[attr-defined]
        self.post_message(LinkedDeltasRefreshed(request.agent_identity))  # type: ignore[attr-defined]

    def _apply_agent_bead_display_worker_result(
        self, worker: Worker[Any], state: WorkerState
    ) -> None:
        current_worker = getattr(self, "_agent_bead_display_worker", None)
        if worker != current_worker:
            return

        if state in (WorkerState.SUCCESS, WorkerState.ERROR, WorkerState.CANCELLED):
            self._agent_bead_display_worker = None  # type: ignore[attr-defined]

        if state != WorkerState.SUCCESS:
            return

        request: BeadDisplayResolveRequest | None = getattr(
            self, "_agent_bead_display_request", None
        )
        if request is None:
            return
        if not request.is_current(
            request.agent_identity,
            request.generation,
            request.attempt_view_mode,
            request.attempt_pinned_number,
        ):
            return

        summary = get_cached_detail_header_summary(self, request.agent)
        if summary is not None:
            cached_display = cached_bead_display(request.agent)
            bead_display = cached_display if isinstance(cached_display, str) else None
            if summary.bead_display != bead_display:
                cache_detail_header_summary(
                    self,
                    request.agent,
                    replace(summary, bead_display=bead_display),
                )

        self._update_display_impl(request.agent)  # type: ignore[attr-defined]

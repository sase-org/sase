"""Async worker handling for the agent prompt panel display."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from textual.worker import Worker, WorkerState

from ...models.agent import Agent
from ...models.agent_bead import resolve_bead_display, should_resolve_bead_display
from ..file_panel._linked_deltas import (
    compute_linked_delta_groups,
    should_refresh_linked_delta_groups,
)
from ..file_panel._messages import LinkedDeltasRefreshed


@dataclass(frozen=True)
class _AgentDetailRenderContext:
    """Current AgentDetail state needed by async prompt-panel workers."""

    generation: int
    attempt_view_mode: str
    attempt_pinned_number: int | None
    is_current: Callable[[tuple[Any, ...], int, str, int | None], bool]


@dataclass(frozen=True)
class _BeadDisplayResolveRequest:
    """State captured when an async bead display resolve is started."""

    agent: Agent
    agent_identity: tuple[Any, ...]
    generation: int
    attempt_view_mode: str
    attempt_pinned_number: int | None
    is_current: Callable[[tuple[Any, ...], int, str, int | None], bool]


@dataclass(frozen=True)
class _LinkedDeltaResolveRequest:
    """State captured when an async linked-deltas refresh is started."""

    agent: Agent
    agent_identity: tuple[Any, ...]
    generation: int
    attempt_view_mode: str
    attempt_pinned_number: int | None
    is_current: Callable[[tuple[Any, ...], int, str, int | None], bool]


class AgentDisplayWorkerMixin:
    """Async bead and linked-delta workers for AgentPromptPanel."""

    def set_agent_detail_render_context(
        self,
        *,
        generation: int,
        attempt_view_mode: str,
        attempt_pinned_number: int | None,
        is_current: Callable[[tuple[Any, ...], int, str, int | None], bool],
    ) -> None:
        """Capture AgentDetail state used by async prompt-panel workers."""
        self._agent_detail_render_context = _AgentDetailRenderContext(  # type: ignore[attr-defined]
            generation=generation,
            attempt_view_mode=attempt_view_mode,
            attempt_pinned_number=attempt_pinned_number,
            is_current=is_current,
        )

    def _start_agent_bead_display_resolve_from_context(self, agent: Agent) -> None:
        context: _AgentDetailRenderContext | None = getattr(
            self, "_agent_detail_render_context", None
        )
        if context is None:
            return
        if context.attempt_pinned_number is not None:
            return
        if not should_resolve_bead_display(agent):
            return

        self.start_agent_bead_display_resolve(
            agent,
            generation=context.generation,
            attempt_view_mode=context.attempt_view_mode,
            attempt_pinned_number=context.attempt_pinned_number,
            is_current=context.is_current,
        )

    def _start_agent_linked_delta_refresh_from_context(self, agent: Agent) -> None:
        context: _AgentDetailRenderContext | None = getattr(
            self, "_agent_detail_render_context", None
        )
        if context is None:
            return
        if context.attempt_pinned_number is not None:
            return
        if not should_refresh_linked_delta_groups(agent):
            return

        self.start_agent_linked_delta_refresh(
            agent,
            generation=context.generation,
            attempt_view_mode=context.attempt_view_mode,
            attempt_pinned_number=context.attempt_pinned_number,
            is_current=context.is_current,
        )

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

        request = _LinkedDeltaResolveRequest(
            agent=agent,
            agent_identity=agent.identity,
            generation=generation,
            attempt_view_mode=attempt_view_mode,
            attempt_pinned_number=attempt_pinned_number,
            is_current=is_current,
        )

        current_worker = getattr(self, "_agent_linked_delta_worker", None)
        if current_worker is not None and getattr(current_worker, "is_running", False):
            current_request: _LinkedDeltaResolveRequest | None = getattr(
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
            return compute_linked_delta_groups(agent)

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
        current_request: _LinkedDeltaResolveRequest | None = getattr(
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

        request = _BeadDisplayResolveRequest(
            agent=agent,
            agent_identity=agent.identity,
            generation=generation,
            attempt_view_mode=attempt_view_mode,
            attempt_pinned_number=attempt_pinned_number,
            is_current=is_current,
        )

        current_worker = getattr(self, "_agent_bead_display_worker", None)
        if current_worker is not None and getattr(current_worker, "is_running", False):
            current_request: _BeadDisplayResolveRequest | None = getattr(
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
            return resolve_bead_display(agent)

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
        current_request: _BeadDisplayResolveRequest | None = getattr(
            self, "_agent_bead_display_request", None
        )
        if current_request is None or current_request.agent_identity != agent.identity:
            current_worker.cancel()

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        """Apply async worker results while preserving later MRO handlers."""
        handler = getattr(super(), "on_worker_state_changed", None)
        if callable(handler):
            handler(event)
        self._apply_agent_bead_display_worker_result(event.worker, event.state)
        self._apply_agent_linked_delta_worker_result(event.worker, event.state)

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

        request: _LinkedDeltaResolveRequest | None = getattr(
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

        request: _BeadDisplayResolveRequest | None = getattr(
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

        self._update_display_impl(request.agent)  # type: ignore[attr-defined]

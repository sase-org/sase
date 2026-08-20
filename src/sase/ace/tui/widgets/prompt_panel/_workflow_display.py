"""Workflow display mixin for the agent prompt panel."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, cast

from rich.console import Group, RenderableType
from rich.text import Text
from textual.worker import Worker, WorkerState

from sase.project_display_names import humanize_vcs_refs_in_text

from ...tools import build_slow_tool_sources, supports_slow_tool_sources
from ...tools.slow import slow_tool_call_threshold_ms_from_widget
from ...models._loaders._json_cache import load_json_cached
from ...models.agent import Agent
from ...util.lazy_syntax import lazy_renderable
from ._workflow_data import (
    load_workflow_detail_snapshot as _load_workflow_detail_snapshot_impl,
)
from ._workflow_render import (
    build_workflow_detail_renderable as _build_workflow_detail_renderable,
    workflow_steps_rich_from_snapshot as _workflow_steps_rich_from_snapshot,
)
from ._workflow_types import WorkflowDetailSnapshot


@dataclass(frozen=True)
class _WorkflowDetailRenderRequest:
    """State captured when an async workflow detail render is started."""

    agent: Agent
    agent_identity: tuple[Any, ...]
    generation: int
    attempt_view_mode: str
    attempt_pinned_number: int | None
    is_current: Callable[[tuple[Any, ...], int, str, int | None], bool]


class WorkflowDisplayMixin:
    """Mixin providing workflow-specific display methods for AgentPromptPanel."""

    def _workflow_prompt_renderer(
        self, agent: Agent
    ) -> Callable[[str], RenderableType]:
        """Return an authored-prompt renderer bound to *agent*'s catalogs."""
        render_prompt = getattr(self, "_render_agent_prompt", None)
        if not callable(render_prompt):

            def _fallback(content: str) -> RenderableType:
                return lazy_renderable(humanize_vcs_refs_in_text(content), "markdown")

            return _fallback

        def _render(content: str) -> RenderableType:
            return cast(RenderableType, render_prompt(agent, content))

        return _render

    def _update_workflow_display(self, agent: Agent) -> None:
        """Update display for a workflow agent.

        Args:
            agent: The workflow agent to display.
        """
        snapshot = _load_workflow_detail_snapshot(agent)
        slow_tool_sources = (
            build_slow_tool_sources(agent)
            if supports_slow_tool_sources(agent)
            else None
        )
        slow_tool_call_threshold_ms = slow_tool_call_threshold_ms_from_widget(self)
        self.update(  # type: ignore[attr-defined]
            _build_workflow_detail_renderable(
                agent,
                snapshot,
                slow_tool_sources=slow_tool_sources,
                slow_tool_call_threshold_ms=slow_tool_call_threshold_ms,
                render_prompt=self._workflow_prompt_renderer(agent),
            )
        )

    def start_workflow_detail_render(
        self,
        agent: Agent,
        *,
        generation: int,
        attempt_view_mode: str,
        attempt_pinned_number: int | None,
        is_current: Callable[[tuple[Any, ...], int, str, int | None], bool],
    ) -> None:
        """Render a workflow parent row in a worker thread."""
        prepare_sections = getattr(self, "prepare_section_document_for_agent", None)
        if callable(prepare_sections):
            prepare_sections(agent)
        current_worker = getattr(self, "_workflow_detail_worker", None)
        if current_worker is not None and current_worker.is_running:
            current_worker.cancel()

        request = _WorkflowDetailRenderRequest(
            agent=agent,
            agent_identity=agent.identity,
            generation=generation,
            attempt_view_mode=attempt_view_mode,
            attempt_pinned_number=attempt_pinned_number,
            is_current=is_current,
        )
        self._workflow_detail_request = request  # type: ignore[attr-defined]
        slow_tool_call_threshold_ms = slow_tool_call_threshold_ms_from_widget(self)

        render_prompt = self._workflow_prompt_renderer(agent)

        def render_task() -> Group:
            snapshot = _load_workflow_detail_snapshot(agent)
            slow_tool_sources = (
                build_slow_tool_sources(agent)
                if supports_slow_tool_sources(agent)
                else None
            )
            return _build_workflow_detail_renderable(
                agent,
                snapshot,
                slow_tool_sources=slow_tool_sources,
                slow_tool_call_threshold_ms=slow_tool_call_threshold_ms,
                render_prompt=render_prompt,
            )

        self._workflow_detail_worker = self.run_worker(  # type: ignore[attr-defined]
            render_task, thread=True
        )

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        """Apply async workflow detail worker results when still current."""
        self._apply_workflow_detail_worker_result(event.worker, event.state)

    def _apply_workflow_detail_worker_result(
        self, worker: Worker[Any], state: WorkerState
    ) -> None:
        current_worker = getattr(self, "_workflow_detail_worker", None)
        if worker != current_worker:
            return

        if state in (WorkerState.SUCCESS, WorkerState.ERROR, WorkerState.CANCELLED):
            self._workflow_detail_worker = None  # type: ignore[attr-defined]

        if state != WorkerState.SUCCESS:
            return

        request: _WorkflowDetailRenderRequest | None = getattr(
            self, "_workflow_detail_request", None
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

        self.update(worker.result)  # type: ignore[attr-defined]
        configure_slow_tick = getattr(self, "_configure_slow_tool_render_tick", None)
        if callable(configure_slow_tick):
            configure_slow_tick(request.agent)

    def _load_workflow_inputs(self, agent: Agent) -> dict[str, Any] | None:
        """Load workflow inputs from workflow_state.json."""
        return _load_workflow_detail_snapshot(agent).inputs

    def _load_workflow_meta_raw(self, agent: Agent) -> dict[str, str] | None:
        """Load raw meta_* fields from workflow step outputs as a dict."""
        return _load_workflow_detail_snapshot(agent).meta_raw

    def _load_workflow_meta_fields(self, agent: Agent) -> list[tuple[str, str]]:
        """Load aggregated meta_* fields from workflow step outputs."""
        return _load_workflow_detail_snapshot(agent).meta_fields

    def _load_workflow_prompt(self, agent: Agent) -> str | None:
        """Load prompt content for a workflow."""
        return _load_workflow_detail_snapshot(agent).prompt_content

    def _load_workflow_steps_rich(self, agent: Agent) -> Text | None:
        """Load and format workflow steps as a rich Text from workflow_state.json."""
        return _workflow_steps_rich_from_snapshot(_load_workflow_detail_snapshot(agent))


def _load_workflow_detail_snapshot(agent: Agent) -> WorkflowDetailSnapshot:
    """Load all workflow detail artifacts needed for one render pass."""
    return _load_workflow_detail_snapshot_impl(agent, json_loader=load_json_cached)

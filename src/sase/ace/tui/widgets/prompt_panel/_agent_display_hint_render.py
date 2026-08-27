"""Body-rendering paths for file-hint agent documents."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sase.ace.tui.tools.report import SlowToolCallReportSpec
from sase.ace.tui.tools.slow import slow_tool_call_threshold_ms_from_widget

from ...agent_completion import agent_wait_status_maps_for_app
from ...models.agent import Agent, AgentType, wait_display_agent
from ...models.agent_family_members import family_roster_container
from ...models.agent_hoods import agent_owns_sase_agent
from ._agent_clan_aggregation import (
    get_cached_clan_section_snapshot,
    prepare_clan_section_snapshot,
)
from ._agent_display_clan import (
    clan_disk_sections_for_fold_state,
    panel_fold_state_from_widget,
)
from ._agent_display_context import runner_capacity_for_app
from ._agent_display_header import build_header_text
from ._agent_display_header_summary import (
    detail_header_summary_is_complete,
    get_cached_detail_header_summary,
    publish_opened_workspaces_cache,
)
from ._agent_display_hint_body import render_agent_prompt_hint_body
from ._agent_display_hint_sections import (
    render_gate_hint_document,
    render_monitor_hint_document,
    render_proc_shell_hint_document,
)
from ._agent_display_state import AgentHintRender, HeaderHintState
from ._file_path_hints import resolve_agent_workspace_dir
from ._hint_caps import append_bounded_text_with_file_hints
from ._member_roster import member_jump_map_publisher_for

if TYPE_CHECKING:
    from rich.console import RenderableType

    from ...util.lazy_syntax import CachedRenderable


class AgentHintRenderMixin:
    """Render regular and clan agent documents with file-path hints."""

    if TYPE_CHECKING:

        def _prepare_cached_hint_renderable(
            self,
            renderable: RenderableType,
        ) -> CachedRenderable: ...

    def _update_display_with_hints_impl(self, agent: Agent) -> AgentHintRender:
        """Render agent display with ``[N]`` file path hints.

        Same visual structure as ``update_display`` but scans xprompt, prompt,
        and chat sections for file paths and inserts numbered hint markers.
        Syntax highlighting is temporarily replaced with plain text so that
        hint markers can be inserted inline.
        """
        # Workflow top-level or bash/python/parallel: no hint support
        if (
            agent.agent_type == AgentType.WORKFLOW
            and not agent.is_workflow_child
            and not agent.appears_as_agent
        ):
            self.update_display(agent)  # type: ignore[attr-defined]
            return AgentHintRender(file_hints={}, tool_call_reports={})

        if agent.is_workflow_child and agent.step_type in (
            "bash",
            "python",
            "parallel",
        ):
            self.update_display(agent)  # type: ignore[attr-defined]
            return AgentHintRender(file_hints={}, tool_call_reports={})

        self._agent_hint_mode_rendered = True  # type: ignore[attr-defined]
        cancel_slow_tick = getattr(self, "_cancel_slow_tool_render_tick", None)
        if callable(cancel_slow_tick):
            cancel_slow_tick()
        if agent.is_clan_container:
            return self._update_clan_display_with_hints(agent)
        humanize_text = self._humanize_display_text  # type: ignore[attr-defined]
        workspace_dir = resolve_agent_workspace_dir(
            agent.effective_workspace_num,
            agent.project_file,
            agent.workspace_dir,
        )
        hint_counter = 1
        hint_mappings: dict[int, str] = {}
        tool_call_reports: dict[str, SlowToolCallReportSpec] = {}

        # Build header (same structured fields as normal display)
        header_hint_state = HeaderHintState(
            hint_counter=hint_counter,
            hint_mappings=hint_mappings,
            workspace_dir=workspace_dir,
            tool_call_reports=tool_call_reports,
        )
        summary = get_cached_detail_header_summary(self, agent)
        if summary is not None:
            publish_opened_workspaces_cache(self, agent, summary.opened_workspaces)
        wait_status_maps = (
            agent_wait_status_maps_for_app(getattr(self, "app", None))
            if wait_display_agent(agent).waiting_for
            else None
        )
        agent_status_buckets = (
            wait_status_maps.buckets if wait_status_maps is not None else None
        )
        clan_wait_member_statuses = (
            wait_status_maps.clan_member_statuses
            if wait_status_maps is not None
            else None
        )
        tribe_wait_bindings = (
            wait_status_maps.tribe_bindings if wait_status_maps is not None else None
        )
        lane_fold_level, lane_fold_overrides = panel_fold_state_from_widget(self)
        try:
            app = self.app  # type: ignore[attr-defined]
        except Exception:
            app = None
        lane_owner = agent_owns_sase_agent(agent)
        lane_summary_enabled = (
            agent.is_family_container_row
            or lane_owner
            or family_roster_container(agent) is not None
        )
        projection_resolver = getattr(app, "lane_neighbor_projection_for", None)
        lane_neighbors = (
            projection_resolver(agent)
            if lane_owner and callable(projection_resolver)
            else None
        )
        header_text, error_tb_syntax = build_header_text(
            agent,
            hint_state=header_hint_state,
            summary=summary,
            agent_status_buckets=agent_status_buckets,
            clan_wait_member_statuses=clan_wait_member_statuses,
            tribe_wait_bindings=tribe_wait_bindings,
            unread_agent_ids=getattr(app, "_unread_completed_agent_ids", set()),
            marked_agent_ids=getattr(app, "_marked_agents", set()),
            slow_tool_call_threshold_ms=slow_tool_call_threshold_ms_from_widget(self),
            lane_fold_level=lane_fold_level,
            lane_section_fold_overrides=lane_fold_overrides,
            lane_neighbors=lane_neighbors,
            runner_capacity=runner_capacity_for_app(app),
            member_jump_map_publisher=(
                member_jump_map_publisher_for(app) if lane_summary_enabled else None
            ),
        )
        hint_counter = header_hint_state.hint_counter

        if agent.is_family_container_row:
            self._update_family_display(  # type: ignore[attr-defined]
                agent,
                header_text,
                error_tb_syntax,
                panel_level=lane_fold_level,
                section_fold_overrides=lane_fold_overrides,
                hint_state=header_hint_state,
            )
            if summary is None:
                self._start_agent_detail_header_enrichment_from_context(agent)  # type: ignore[attr-defined]
            return AgentHintRender(
                file_hints=hint_mappings,
                tool_call_reports=tool_call_reports,
                commit_views=header_hint_state.commit_views,
                glossary_reports=header_hint_state.glossary_reports,
                memory_reports=header_hint_state.memory_reports,
                artifact_read_refs=header_hint_state.artifact_read_refs,
                header_enrichment_pending=not detail_header_summary_is_complete(
                    summary
                ),
            )

        # Error traceback as text with hints (not Syntax)
        if agent.error_traceback:
            hint_counter = append_bounded_text_with_file_hints(
                header_text,
                agent.error_traceback + "\n",
                hint_counter,
                hint_mappings,
                workspace_dir,
            )

        if agent.is_proc_shell:
            return render_proc_shell_hint_document(
                self,
                agent,
                header_text,
                hint_counter,
                hint_mappings,
                workspace_dir,
                lane_fold_level,
                lane_fold_overrides,
                header_hint_state,
                tool_call_reports,
            )

        if agent.is_monitor:
            return render_monitor_hint_document(
                self,
                agent,
                header_text,
                hint_counter,
                hint_mappings,
                workspace_dir,
                lane_fold_level,
                lane_fold_overrides,
                header_hint_state,
                tool_call_reports,
                summary,
            )

        if agent.is_gate:
            return render_gate_hint_document(
                self,
                agent,
                header_text,
                hint_counter,
                hint_mappings,
                workspace_dir,
                lane_fold_level,
                lane_fold_overrides,
                header_hint_state,
                tool_call_reports,
                summary,
            )

        hint_counter = render_agent_prompt_hint_body(
            self,
            agent,
            header_text,
            humanize_text,
            hint_counter,
            hint_mappings,
            workspace_dir,
        )

        self.update(self._prepare_cached_hint_renderable(header_text))  # type: ignore[attr-defined]
        if summary is None:
            self._start_agent_detail_header_enrichment_from_context(agent)  # type: ignore[attr-defined]
        return AgentHintRender(
            file_hints=hint_mappings,
            tool_call_reports=tool_call_reports,
            commit_views=header_hint_state.commit_views,
            glossary_reports=header_hint_state.glossary_reports,
            memory_reports=header_hint_state.memory_reports,
            artifact_read_refs=header_hint_state.artifact_read_refs,
            header_enrichment_pending=not detail_header_summary_is_complete(summary),
        )

    def _update_clan_display_with_hints(self, agent: Agent) -> AgentHintRender:
        """Render one fold-aware clan document with summary path hints."""
        self._cancel_tribe_section_worker_for_agent_selection()  # type: ignore[attr-defined]
        self._cancel_clan_section_worker_for_selection_change(agent)  # type: ignore[attr-defined]
        snapshot = prepare_clan_section_snapshot(self, agent)
        fold_level, fold_overrides = panel_fold_state_from_widget(self)
        required_sections = clan_disk_sections_for_fold_state(
            fold_level,
            fold_overrides,
        )
        self.set_clan_disk_sections_required(required_sections)  # type: ignore[attr-defined]
        try:
            app = self.app  # type: ignore[attr-defined]
        except Exception:
            app = None

        hint_mappings: dict[int, str] = {}
        tool_call_reports: dict[str, SlowToolCallReportSpec] = {}
        hint_state = HeaderHintState(
            hint_counter=1,
            hint_mappings=hint_mappings,
            workspace_dir=None,
            tool_call_reports=tool_call_reports,
        )
        clan_text, _error_tb_syntax = build_header_text(
            agent,
            hint_state=hint_state,
            unread_agent_ids=getattr(app, "_unread_completed_agent_ids", set()),
            clan_snapshot=snapshot,
            clan_fold_level=fold_level,
            clan_section_fold_overrides=fold_overrides,
            member_jump_map_publisher=member_jump_map_publisher_for(app),
        )
        self.update(self._prepare_cached_hint_renderable(clan_text))  # type: ignore[attr-defined]

        self._cancel_agent_bead_display_worker_for_selection_change(agent)  # type: ignore[attr-defined]
        self._cancel_agent_linked_delta_worker_for_selection_change(agent)  # type: ignore[attr-defined]
        self._cancel_agent_detail_header_worker_for_selection_change(agent)  # type: ignore[attr-defined]
        self._start_clan_section_enrichment_from_context(agent)  # type: ignore[attr-defined]

        snapshot = get_cached_clan_section_snapshot(self, agent) or snapshot
        loaded_sections = (
            snapshot.disk.loaded_sections if snapshot.disk is not None else frozenset()
        )
        enrichment_pending = bool(snapshot.loading_sections) or not (
            required_sections.issubset(loaded_sections)
        )
        return AgentHintRender(
            file_hints=hint_mappings,
            tool_call_reports=tool_call_reports,
            commit_views=hint_state.commit_views,
            glossary_reports=hint_state.glossary_reports,
            memory_reports=hint_state.memory_reports,
            artifact_read_refs=hint_state.artifact_read_refs,
            header_enrichment_pending=enrichment_pending,
        )

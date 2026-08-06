"""Agent display mixin for the agent prompt panel."""

from __future__ import annotations

from rich.console import Group

from ...agent_completion import agent_wait_status_maps_for_app
from ...models.agent import Agent, wait_display_agent
from ...models.agent_family_members import family_roster_container
from ...models.agent_hoods import agent_owns_lane
from ...models.agent_tribe_summary import AgentTribeSummarySnapshot
from ...tools.slow import slow_tool_call_threshold_ms_from_widget
from ...util.trace import tui_trace
from ._agent_display_attempts import (
    find_attempt,
    render_attempt_banner,
    render_merged_attempt_history,
    should_render_merged,
)
from ._agent_display_async import AgentDisplayWorkerMixin
from ._agent_clan_aggregation import (
    get_cached_clan_section_snapshot,
    prepare_clan_section_snapshot,
)
from ._agent_display_clan import (
    clan_disk_sections_for_fold_state,
    panel_fold_state_from_widget,
)
from ._agent_display_context import runner_capacity_for_app
from ._agent_display_tribe import tribe_enrichment_sections_for_fold_state
from ._agent_display_header import build_header_text
from ._agent_display_render import AgentDisplayRenderMixin
from ._member_roster import member_jump_map_publisher_for
from ._agent_tribe_aggregation import (
    get_cached_tribe_section_snapshot,
    prepare_tribe_section_snapshot,
)

_find_attempt = find_attempt
_render_attempt_banner = render_attempt_banner
_render_merged_attempt_history = render_merged_attempt_history
_should_render_merged = should_render_merged


class AgentDisplayMixin(AgentDisplayRenderMixin, AgentDisplayWorkerMixin):
    """Mixin providing agent-specific display methods for AgentPromptPanel."""

    def update_display(self, agent: Agent) -> None:
        """Update with agent information and prompt.

        Args:
            agent: The Agent to display.
        """
        with tui_trace("widget.prompt_panel.update_display"):
            self._cancel_tribe_section_worker_for_agent_selection()
            self._cancel_clan_section_worker_for_selection_change(agent)
            if agent.is_clan_container:
                prepare_clan_section_snapshot(self, agent)
            self._agent_hint_mode_rendered = False  # type: ignore[attr-defined]
            prepare_sections = getattr(self, "prepare_section_document_for_agent", None)
            if callable(prepare_sections):
                prepare_sections(agent)
            self._reset_markdown_render_cache_for_agent(agent)
            self._update_display_impl(agent)
            if agent.is_clan_container:
                self._cancel_agent_bead_display_worker_for_selection_change(agent)
                self._cancel_agent_linked_delta_worker_for_selection_change(agent)
                self._cancel_agent_detail_header_worker_for_selection_change(agent)
                cancel_slow_tick = getattr(self, "_cancel_slow_tool_render_tick", None)
                if callable(cancel_slow_tick):
                    cancel_slow_tick()
                self._start_clan_section_enrichment_from_context(agent)
                return
            self._start_agent_detail_header_enrichment_from_context(agent)
            self._start_agent_linked_delta_refresh_from_context(agent)
            self._start_agent_bead_display_resolve_from_context(agent)
            configure_slow_tick = getattr(
                self, "_configure_slow_tool_render_tick", None
            )
            if callable(configure_slow_tick):
                configure_slow_tick(agent)

    def update_tribe_display(
        self,
        snapshot: AgentTribeSummarySnapshot,
        *,
        cheap: bool = False,
    ) -> None:
        """Render one pure tribe document on the regular prompt surface."""
        with tui_trace("widget.prompt_panel.update_tribe_display", cheap=cheap):
            self._agent_hint_mode_rendered = False  # type: ignore[attr-defined]
            prepare_sections = getattr(self, "prepare_section_document", None)
            if callable(prepare_sections):
                prepare_sections((snapshot.container_identity, "tribe"))
            if cheap:
                preserve_section = getattr(
                    self,
                    "preserve_missing_section_on_next_update",
                    None,
                )
                if callable(preserve_section):
                    preserve_section()
            cancel_slow_tick = getattr(self, "_cancel_slow_tool_render_tick", None)
            if callable(cancel_slow_tick):
                cancel_slow_tick()
            for worker_name in (
                "_agent_bead_display_worker",
                "_agent_linked_delta_worker",
                "_agent_detail_header_worker",
                "_clan_section_worker",
            ):
                worker = getattr(self, worker_name, None)
                if worker is not None and getattr(worker, "is_running", False):
                    worker.cancel()

            fold_level, fold_overrides = panel_fold_state_from_widget(self)
            try:
                app = self.app  # type: ignore[attr-defined]
            except Exception:
                app = None
            agents_resolver = getattr(app, "_agents_in_focused_panel", None)
            if callable(agents_resolver):
                prepare_tribe_section_snapshot(
                    self,
                    snapshot,
                    agents_resolver(),
                )
            from ._agent_display_tribe import build_tribe_detail_text

            self.update(  # type: ignore[attr-defined]
                build_tribe_detail_text(
                    snapshot,
                    section_snapshot=get_cached_tribe_section_snapshot(
                        self,
                        snapshot.container_identity,
                    ),
                    fold_level=fold_level,
                    section_fold_overrides=fold_overrides,
                    member_jump_map_publisher=(
                        None if cheap else member_jump_map_publisher_for(app)
                    ),
                    cheap=cheap,
                )
            )
            if not cheap:
                required = tribe_enrichment_sections_for_fold_state(
                    fold_level,
                    fold_overrides,
                )
                if required:
                    self.start_tribe_section_enrichment(
                        snapshot.container_identity,
                        sections=required,
                        slow_tool_threshold_ms=slow_tool_call_threshold_ms_from_widget(
                            self
                        ),
                    )

    def refresh_slow_tool_metadata_from_cache(self, agent: Agent) -> None:
        """Re-render from cached header/tool data for the slow-tool tick."""
        with tui_trace("widget.prompt_panel.refresh_slow_tool_metadata_from_cache"):
            prepare_sections = getattr(self, "prepare_section_document_for_agent", None)
            if callable(prepare_sections):
                prepare_sections(agent)
            self._update_display_impl(agent)

    def refresh_detail_header_from_cache(self, agent: Agent) -> None:
        """Re-render after async detail-header enrichment populated the cache."""
        with tui_trace("widget.prompt_panel.refresh_detail_header_from_cache"):
            self._agent_hint_mode_rendered = False  # type: ignore[attr-defined]
            self._update_display_impl(agent)
            configure_slow_tick = getattr(
                self, "_configure_slow_tool_render_tick", None
            )
            if callable(configure_slow_tick):
                configure_slow_tick(agent)

    def update_header_only(self, agent: Agent) -> None:
        """Render only the agent-details header + inline error traceback.

        Phase-3 immediate path: builds the cheap, in-memory header and
        renders it directly. Does **not** touch the artifact-file cache, list
        the artifacts directory, or read prompt / reply / response files.
        The debounced full update path is responsible for filling in the
        prompt body, reply, tools, and file content shortly after.
        """
        with tui_trace("widget.prompt_panel.update_header_only"):
            self._cancel_tribe_section_worker_for_agent_selection()
            self._cancel_clan_section_worker_for_selection_change(agent)
            if agent.is_clan_container:
                prepare_clan_section_snapshot(self, agent)
            self._agent_hint_mode_rendered = False  # type: ignore[attr-defined]
            prepare_sections = getattr(self, "prepare_section_document_for_agent", None)
            if callable(prepare_sections):
                prepare_sections(agent)
            preserve_section = getattr(
                self, "preserve_missing_section_on_next_update", None
            )
            if callable(preserve_section):
                preserve_section()
            cancel_slow_tick = getattr(self, "_cancel_slow_tool_render_tick", None)
            if callable(cancel_slow_tick):
                cancel_slow_tick()
            self._cancel_agent_bead_display_worker_for_selection_change(agent)
            self._cancel_agent_linked_delta_worker_for_selection_change(agent)
            self._cancel_agent_detail_header_worker_for_selection_change(agent)
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
                wait_status_maps.tribe_bindings
                if wait_status_maps is not None
                else None
            )
            try:
                app = self.app  # type: ignore[attr-defined]
            except Exception:
                app = None
            clan_fold_level, clan_fold_overrides = panel_fold_state_from_widget(self)
            lane_owner = agent_owns_lane(agent)
            lane_summary_enabled = (
                agent.is_family_container_row
                or lane_owner
                or family_roster_container(agent) is not None
            )
            projection_resolver = getattr(
                app,
                "lane_neighbor_projection_for",
                None,
            )
            lane_neighbors = (
                projection_resolver(agent)
                if lane_owner and callable(projection_resolver)
                else None
            )
            if agent.is_clan_container and app is not None:
                self.set_clan_disk_sections_required(
                    clan_disk_sections_for_fold_state(
                        clan_fold_level,
                        clan_fold_overrides,
                    )
                )
            header_text, error_tb_syntax = build_header_text(
                agent,
                cheap=True,
                agent_status_buckets=agent_status_buckets,
                clan_wait_member_statuses=clan_wait_member_statuses,
                tribe_wait_bindings=tribe_wait_bindings,
                unread_agent_ids=getattr(app, "_unread_completed_agent_ids", set()),
                marked_agent_ids=getattr(app, "_marked_agents", set()),
                slow_tool_call_threshold_ms=slow_tool_call_threshold_ms_from_widget(
                    self
                ),
                clan_snapshot=get_cached_clan_section_snapshot(self, agent),
                clan_fold_level=clan_fold_level,
                clan_section_fold_overrides=clan_fold_overrides,
                lane_fold_level=clan_fold_level,
                lane_section_fold_overrides=clan_fold_overrides,
                lane_neighbors=lane_neighbors,
                runner_capacity=runner_capacity_for_app(app),
                member_jump_map_publisher=(
                    member_jump_map_publisher_for(app)
                    if agent.is_clan_container or lane_summary_enabled
                    else None
                ),
            )
            if error_tb_syntax is not None:
                self.update(Group(header_text, error_tb_syntax))  # type: ignore[attr-defined]
            else:
                self.update(header_text)  # type: ignore[attr-defined]


__all__ = [
    "AgentDisplayMixin",
    "find_attempt",
    "render_attempt_banner",
    "render_merged_attempt_history",
    "should_render_merged",
    "_find_attempt",
    "_render_attempt_banner",
    "_render_merged_attempt_history",
    "_should_render_merged",
]

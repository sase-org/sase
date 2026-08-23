"""Body-rendering paths for file-hint agent documents."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING

from rich.text import Text

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
from ._agent_display_content import (
    get_phase_label,
    get_prompt_content,
    render_phase_divider,
    render_timestamp_divider,
)
from ._agent_display_context import runner_capacity_for_app
from ._agent_display_header import AgentHeader, build_header_text
from ._agent_display_header_summary import (
    detail_header_summary_is_complete,
    get_cached_detail_header_summary,
    publish_opened_workspaces_cache,
)
from ._agent_display_state import AgentHintRender, HeaderHintState
from ._agent_monitor_section import (
    MONITOR_SECTION_ID,
    MonitorTextAnnotator,
    build_monitor_output,
    build_monitor_section,
    monitor_phase_text,
)
from ._agent_proc_shell_section import (
    PROC_SHELL_SECTION_ID,
    ProcShellTextAnnotator,
    build_proc_shell_output,
    build_proc_shell_preview,
    build_proc_shell_section,
)
from ._agent_xprompt_highlighting import (
    agent_prompt_highlight_context,
    apply_authored_prompt_overlays,
)
from ._file_path_hints import resolve_agent_workspace_dir
from ._file_path_hints import iter_xprompt_file_path_matches
from ._helpers import append_section_heading, format_output
from ._hint_caps import append_bounded_text_with_file_hints
from ._member_roster import member_jump_map_publisher_for

if TYPE_CHECKING:
    from rich.console import RenderableType

    from ...util.lazy_syntax import CachedRenderable


def _render_reply_with_hints(
    agent: Agent,
    target: AgentHeader,
    hint_counter: int,
    hint_mappings: dict[int, str],
    workspace_dir: str | None,
    humanize_text: Callable[[str], str],
) -> int:
    """Render one agent's reply content with file hints into a Text."""
    chunks = agent.get_timestamped_reply_chunks()
    if chunks:
        for ts, chunk_text in chunks:
            target.append_text(render_timestamp_divider(ts))
            content = chunk_text.strip()
            if content:
                content = humanize_text(content)
                hint_counter = append_bounded_text_with_file_hints(
                    target,
                    content + "\n",
                    hint_counter,
                    hint_mappings,
                    workspace_dir,
                )
                target.append("\n")
        return hint_counter
    live_reply = agent.get_live_reply_content()
    if live_reply:
        live_reply = humanize_text(live_reply)
        return append_bounded_text_with_file_hints(
            target,
            live_reply + "\n",
            hint_counter,
            hint_mappings,
            workspace_dir,
        )
    response_content = agent.get_response_content()
    if response_content:
        response_content = humanize_text(response_content)
        return append_bounded_text_with_file_hints(
            target,
            response_content + "\n",
            hint_counter,
            hint_mappings,
            workspace_dir,
        )
    return hint_counter


def _hint_monitor_annotator(
    hint_counter: int,
    hint_mappings: dict[int, str],
    workspace_dir: str | None,
) -> tuple[MonitorTextAnnotator, Callable[[], int]]:
    """Annotate free-form monitor text and expose the updated hint counter."""

    def annotate(content: str | Text) -> Text:
        nonlocal hint_counter
        target = Text(end="")
        raw = content.plain if isinstance(content, Text) else content
        hint_counter = append_bounded_text_with_file_hints(
            target,
            raw,
            hint_counter,
            hint_mappings,
            workspace_dir,
        )
        return target

    return annotate, lambda: hint_counter


def _hint_proc_shell_annotator(
    hint_counter: int,
    hint_mappings: dict[int, str],
    workspace_dir: str | None,
) -> tuple[ProcShellTextAnnotator, Callable[[], int]]:
    """Annotate free-form proc-shell text and expose the updated hint counter."""

    def annotate(content: str | Text) -> Text:
        nonlocal hint_counter
        target = Text(end="")
        raw = content.plain if isinstance(content, Text) else content
        hint_counter = append_bounded_text_with_file_hints(
            target,
            raw,
            hint_counter,
            hint_mappings,
            workspace_dir,
        )
        return target

    return annotate, lambda: hint_counter


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
            annotate, hint_count = _hint_proc_shell_annotator(
                hint_counter,
                hint_mappings,
                workspace_dir,
            )
            section_level = (
                lane_fold_overrides.get(PROC_SHELL_SECTION_ID, lane_fold_level)
                if isinstance(lane_fold_overrides, Mapping)
                else lane_fold_level
            )
            for part in build_proc_shell_preview(agent, annotate=annotate):
                if isinstance(part, Text):
                    header_text.append_text(part)
            for part in build_proc_shell_section(
                agent,
                panel_level=section_level,
                annotate=annotate,
            ):
                if isinstance(part, Text):
                    header_text.append_text(part)
            for part in build_proc_shell_output(agent, annotate=annotate):
                if isinstance(part, Text):
                    header_text.append_text(part)
            hint_counter = hint_count()
            self.update(self._prepare_cached_hint_renderable(header_text))  # type: ignore[attr-defined]
            return AgentHintRender(
                file_hints=hint_mappings,
                tool_call_reports=tool_call_reports,
                commit_views=header_hint_state.commit_views,
                glossary_reports=header_hint_state.glossary_reports,
                header_enrichment_pending=False,
            )

        if agent.is_monitor:
            annotate, hint_count = _hint_monitor_annotator(
                hint_counter,
                hint_mappings,
                workspace_dir,
            )
            section_level = (
                lane_fold_overrides.get(MONITOR_SECTION_ID, lane_fold_level)
                if isinstance(lane_fold_overrides, Mapping)
                else lane_fold_level
            )
            for part in build_monitor_section(
                agent,
                panel_level=section_level,
                annotate=annotate,
            ):
                if isinstance(part, Text):
                    header_text.append_text(part)
            for part in build_monitor_output(agent, annotate=annotate):
                if isinstance(part, Text):
                    header_text.append_text(part)
            hint_counter = hint_count()
            self.update(self._prepare_cached_hint_renderable(header_text))  # type: ignore[attr-defined]
            if summary is None:
                self._start_agent_detail_header_enrichment_from_context(agent)  # type: ignore[attr-defined]
            return AgentHintRender(
                file_hints=hint_mappings,
                tool_call_reports=tool_call_reports,
                commit_views=header_hint_state.commit_views,
                glossary_reports=header_hint_state.glossary_reports,
                header_enrichment_pending=not detail_header_summary_is_complete(
                    summary
                ),
            )

        # AGENT XPROMPT section (with file path hints)
        raw_xprompt = agent.get_raw_xprompt_content()
        highlight_context = agent_prompt_highlight_context(
            self,
            agent,
            raw_xprompt or "",
        )
        if raw_xprompt:
            source_xprompt = raw_xprompt
            raw_xprompt = humanize_text(source_xprompt)
            append_section_heading(header_text, "AGENT XPROMPT")
            xprompt_start = len(header_text.plain)
            hint_counter = append_bounded_text_with_file_hints(
                header_text,
                raw_xprompt + "\n",
                hint_counter,
                hint_mappings,
                workspace_dir,
                matcher=iter_xprompt_file_path_matches,
            )
            xprompt_source = header_text.plain[xprompt_start:]
            hint_spans = tuple(
                span for span in header_text.spans if span.end > xprompt_start
            )
            apply_authored_prompt_overlays(
                header_text,
                xprompt_source,
                highlight_context,
                region_start=xprompt_start,
                include_xprompt=True,
                hint_spans=hint_spans,
            )
            header_text.append("\n")
            header_text.append("\u2500" * 50 + "\n", style="dim")
            header_text.append("\n")

        # AGENT PROMPT section (with file path hints, Text instead of Syntax)
        append_section_heading(header_text, "AGENT PROMPT")

        prompt_content = get_prompt_content(agent)
        if prompt_content:
            prompt_content = humanize_text(prompt_content)
            prompt_start = len(header_text.plain)
            hint_counter = append_bounded_text_with_file_hints(
                header_text,
                prompt_content + "\n",
                hint_counter,
                hint_mappings,
                workspace_dir,
            )
            prompt_source = header_text.plain[prompt_start:]
            prompt_hint_spans = tuple(
                span for span in header_text.spans if span.end > prompt_start
            )
            apply_authored_prompt_overlays(
                header_text,
                prompt_source,
                highlight_context,
                region_start=prompt_start,
                hint_spans=prompt_hint_spans,
            )

            # Consolidated AGENT REPLY for agents with follow-ups (with hints)
            if agent.followup_agents:
                header_text.append("\n")
                header_text.append("\u2500" * 50 + "\n", style="dim")
                header_text.append("\n")
                append_section_heading(header_text, "AGENT REPLY")

                # Main agent's phase
                header_text.append_text(
                    render_phase_divider(
                        get_phase_label(agent),
                        agent.run_start_time or agent.start_time,
                    )
                )
                hint_counter = _render_reply_with_hints(
                    agent,
                    header_text,
                    hint_counter,
                    hint_mappings,
                    workspace_dir,
                    humanize_text,
                )

                # Follow-up phases
                for followup in agent.followup_agents:
                    if followup.is_monitor:
                        annotate, hint_count = _hint_monitor_annotator(
                            hint_counter,
                            hint_mappings,
                            workspace_dir,
                        )
                        header_text.append_text(
                            monitor_phase_text(followup, annotate=annotate)
                        )
                        hint_counter = hint_count()
                        continue
                    header_text.append_text(
                        render_phase_divider(
                            get_phase_label(followup),
                            followup.run_start_time or followup.start_time,
                        )
                    )
                    hint_counter = _render_reply_with_hints(
                        followup,
                        header_text,
                        hint_counter,
                        hint_mappings,
                        workspace_dir,
                        humanize_text,
                    )
            # AGENT CHAT section for completed agents (with hints)
            elif agent.status in ("DONE", "FAILED"):
                response_content = agent.get_response_content()
                # Only use step_output when it has displayable content (_raw/_data),
                # not when it only contains meta_* metadata fields.
                if (
                    response_content is None
                    and agent.is_workflow_child
                    and isinstance(agent.step_output, dict)
                    and ("_raw" in agent.step_output or "_data" in agent.step_output)
                ):
                    response_content = format_output(agent.step_output)

                header_text.append("\n")
                header_text.append("\u2500" * 50 + "\n", style="dim")
                header_text.append("\n")
                append_section_heading(header_text, "AGENT CHAT")

                chunks = agent.get_timestamped_reply_chunks()
                if chunks:
                    for ts, chunk_text in chunks:
                        header_text.append_text(render_timestamp_divider(ts))
                        content = chunk_text.strip()
                        if content:
                            content = humanize_text(content)
                            hint_counter = append_bounded_text_with_file_hints(
                                header_text,
                                content + "\n",
                                hint_counter,
                                hint_mappings,
                                workspace_dir,
                            )
                            header_text.append("\n")
                elif response_content:
                    response_content = humanize_text(response_content)
                    hint_counter = append_bounded_text_with_file_hints(
                        header_text,
                        response_content + "\n",
                        hint_counter,
                        hint_mappings,
                        workspace_dir,
                    )
                else:
                    header_text.append("No response file found.\n", style="dim italic")
            else:
                # AGENT REPLY section for running agents (with hints)
                header_text.append("\n")
                header_text.append("\u2500" * 50 + "\n", style="dim")
                header_text.append("\n")
                append_section_heading(header_text, "AGENT REPLY")

                live_reply = agent.get_live_reply_content()
                chunks = agent.get_timestamped_reply_chunks()
                if chunks:
                    for ts, chunk_text in chunks:
                        header_text.append_text(render_timestamp_divider(ts))
                        content = chunk_text.strip()
                        if content:
                            content = humanize_text(content)
                            hint_counter = append_bounded_text_with_file_hints(
                                header_text,
                                content + "\n",
                                hint_counter,
                                hint_mappings,
                                workspace_dir,
                            )
                            header_text.append("\n")
                elif live_reply:
                    live_reply = humanize_text(live_reply)
                    hint_counter = append_bounded_text_with_file_hints(
                        header_text,
                        live_reply + "\n",
                        hint_counter,
                        hint_mappings,
                        workspace_dir,
                    )
                else:
                    header_text.append(
                        "Waiting for agent response...\n",
                        style="dim italic",
                    )
        else:
            header_text.append("No prompt file found.\n", style="dim italic")

        self.update(self._prepare_cached_hint_renderable(header_text))  # type: ignore[attr-defined]
        if summary is None:
            self._start_agent_detail_header_enrichment_from_context(agent)  # type: ignore[attr-defined]
        return AgentHintRender(
            file_hints=hint_mappings,
            tool_call_reports=tool_call_reports,
            commit_views=header_hint_state.commit_views,
            glossary_reports=header_hint_state.glossary_reports,
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
            header_enrichment_pending=enrichment_pending,
        )

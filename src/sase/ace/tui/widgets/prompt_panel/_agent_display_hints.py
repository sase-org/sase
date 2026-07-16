"""Agent display with file-path hints for the agent prompt panel."""

from collections.abc import Callable

from rich.text import Text

from sase.ace.tui.tools.report import SlowToolCallReportSpec
from sase.ace.tui.tools.slow import slow_tool_call_threshold_ms_from_widget

from ...agent_completion import agent_status_buckets_for_app
from ...models.agent import Agent, AgentType
from ...util.trace import tui_trace
from ...util.xprompt_syntax import apply_xprompt_overlays
from ._agent_display_content import (
    get_phase_label,
    get_prompt_content,
    render_phase_divider,
    render_timestamp_divider,
)
from ._agent_display_header import AgentHeader, build_header_text
from ._agent_display_header_summary import (
    get_cached_detail_header_summary,
    publish_opened_workspaces_cache,
)
from ._agent_display_state import AgentHintRender, HeaderHintState
from ._agent_xprompt_highlighting import known_xprompt_skill_names
from ._file_path_hints import (
    append_text_with_file_hints,
    resolve_agent_workspace_dir,
)
from ._helpers import append_section_heading, format_output


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
                hint_counter = append_text_with_file_hints(
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
        return append_text_with_file_hints(
            target,
            live_reply + "\n",
            hint_counter,
            hint_mappings,
            workspace_dir,
        )
    response_content = agent.get_response_content()
    if response_content:
        response_content = humanize_text(response_content)
        return append_text_with_file_hints(
            target,
            response_content + "\n",
            hint_counter,
            hint_mappings,
            workspace_dir,
        )
    return hint_counter


class AgentHintsDisplayMixin:
    """Mixin providing hint-annotated agent display for AgentPromptPanel."""

    def update_display_with_hints(self, agent: Agent) -> AgentHintRender:
        """Render the agent display with hints and trace the keystroke path."""
        with tui_trace("widget.prompt_panel.update_display_with_hints"):
            return self._update_display_with_hints_impl(agent)

    def _update_display_with_hints_impl(self, agent: Agent) -> AgentHintRender:
        """Render agent display with ``[N]`` file path hints.

        Same visual structure as :meth:`update_display` but scans xprompt,
        prompt, and chat sections for file paths and inserts numbered hint
        markers.  Syntax highlighting is temporarily replaced with plain
        text so that hint markers can be inserted inline.

        Args:
            agent: The Agent to display.

        Returns:
            File hint mappings and deferred tool-call report specs.
        """
        prepare_sections = getattr(self, "prepare_section_document_for_agent", None)
        if callable(prepare_sections):
            prepare_sections(agent)

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
        self._reset_markdown_render_cache_for_agent(agent)  # type: ignore[attr-defined]
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
        agent_status_buckets = (
            agent_status_buckets_for_app(getattr(self, "app", None))
            if agent.waiting_for
            else None
        )
        header_text, _ = build_header_text(
            agent,
            hint_state=header_hint_state,
            summary=summary,
            agent_status_buckets=agent_status_buckets,
            slow_tool_call_threshold_ms=slow_tool_call_threshold_ms_from_widget(self),
        )
        hint_counter = header_hint_state.hint_counter

        # Error traceback as text with hints (not Syntax)
        if agent.error_traceback:
            hint_counter = append_text_with_file_hints(
                header_text,
                agent.error_traceback + "\n",
                hint_counter,
                hint_mappings,
                workspace_dir,
            )

        # AGENT XPROMPT section (with file path hints)
        raw_xprompt = agent.get_raw_xprompt_content()
        if raw_xprompt:
            source_xprompt = raw_xprompt
            raw_xprompt = humanize_text(source_xprompt)
            append_section_heading(header_text, "AGENT XPROMPT")
            xprompt_start = len(header_text.plain)
            hint_counter = append_text_with_file_hints(
                header_text,
                raw_xprompt + "\n",
                hint_counter,
                hint_mappings,
                workspace_dir,
            )
            xprompt_source = header_text.plain[xprompt_start:]
            hint_spans = [
                span for span in header_text.spans if span.end > xprompt_start
            ]
            try:
                apply_xprompt_overlays(
                    header_text,
                    xprompt_source,
                    region_start=xprompt_start,
                    known_skills=known_xprompt_skill_names(
                        self,
                        agent,
                        source_xprompt,
                    ),
                )
                for span in hint_spans:
                    header_text.stylize(span.style, span.start, span.end)
            except Exception:
                pass
            header_text.append("\n")
            header_text.append("\u2500" * 50 + "\n", style="dim")
            header_text.append("\n")

        # AGENT PROMPT section (with file path hints, Text instead of Syntax)
        append_section_heading(header_text, "AGENT PROMPT")

        prompt_content = get_prompt_content(agent)
        if prompt_content:
            prompt_content = humanize_text(prompt_content)
            hint_counter = append_text_with_file_hints(
                header_text,
                prompt_content + "\n",
                hint_counter,
                hint_mappings,
                workspace_dir,
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
                            hint_counter = append_text_with_file_hints(
                                header_text,
                                content + "\n",
                                hint_counter,
                                hint_mappings,
                                workspace_dir,
                            )
                            header_text.append("\n")
                elif response_content:
                    response_content = humanize_text(response_content)
                    hint_counter = append_text_with_file_hints(
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
                            hint_counter = append_text_with_file_hints(
                                header_text,
                                content + "\n",
                                hint_counter,
                                hint_mappings,
                                workspace_dir,
                            )
                            header_text.append("\n")
                elif live_reply:
                    live_reply = humanize_text(live_reply)
                    hint_counter = append_text_with_file_hints(
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

        self.update(header_text)  # type: ignore[attr-defined]
        if summary is None:
            self._start_agent_detail_header_enrichment_from_context(agent)  # type: ignore[attr-defined]
        return AgentHintRender(
            file_hints=hint_mappings,
            tool_call_reports=tool_call_reports,
            commit_views=header_hint_state.commit_views,
            header_enrichment_pending=summary is None,
        )

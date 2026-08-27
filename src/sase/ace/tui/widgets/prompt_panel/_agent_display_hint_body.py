"""AGENT XPROMPT / PROMPT / REPLY / CHAT body rendering for hint documents."""

from __future__ import annotations

from collections.abc import Callable

from ...models._projected_record import resolve_step_output
from ...models.agent import Agent
from ._agent_display_content import (
    get_phase_label,
    get_prompt_content,
    render_phase_divider,
    render_timestamp_divider,
)
from ._agent_display_header import AgentHeader
from ._agent_display_hint_annotators import (
    hint_monitor_annotator,
    render_reply_with_hints,
)
from ._agent_monitor_section import monitor_phase_text
from ._agent_xprompt_highlighting import (
    agent_prompt_highlight_context,
    apply_authored_prompt_overlays,
)
from ._file_path_hints import iter_xprompt_file_path_matches
from ._helpers import append_section_heading, format_output
from ._hint_caps import append_bounded_text_with_file_hints


def render_agent_prompt_hint_body(
    panel: object,
    agent: Agent,
    header_text: AgentHeader,
    humanize_text: Callable[[str], str],
    hint_counter: int,
    hint_mappings: dict[int, str],
    workspace_dir: str | None,
) -> int:
    """Render the xprompt, prompt, and reply/chat sections with file hints.

    Returns the updated hint counter.
    """
    # AGENT XPROMPT section (with file path hints)
    raw_xprompt = agent.get_raw_xprompt_content()
    highlight_context = agent_prompt_highlight_context(
        panel,
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
        header_text.append("─" * 50 + "\n", style="dim")
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
            header_text.append("─" * 50 + "\n", style="dim")
            header_text.append("\n")
            append_section_heading(header_text, "AGENT REPLY")

            # Main agent's phase
            header_text.append_text(
                render_phase_divider(
                    get_phase_label(agent),
                    agent.run_start_time or agent.start_time,
                )
            )
            hint_counter = render_reply_with_hints(
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
                    annotate, hint_count = hint_monitor_annotator(
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
                hint_counter = render_reply_with_hints(
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
            step_output = resolve_step_output(agent)
            if (
                response_content is None
                and agent.is_workflow_child
                and step_output is not None
                and ("_raw" in step_output or "_data" in step_output)
            ):
                response_content = format_output(step_output)

            header_text.append("\n")
            header_text.append("─" * 50 + "\n", style="dim")
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
            header_text.append("─" * 50 + "\n", style="dim")
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

    return hint_counter

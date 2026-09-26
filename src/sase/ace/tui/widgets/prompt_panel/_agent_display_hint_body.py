"""AGENT XPROMPT / PROMPT / REPLY / CHAT body rendering for hint documents."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from rich.text import Text

from ...models._projected_record import resolve_step_output
from ...models.agent import Agent
from ..decks.card_block import BlockSpreadOnly, card_block_id
from ._agent_display_agent_session import legacy_followup_shell_facts
from ._agent_display_content import (
    get_phase_label,
    get_prompt_content,
    render_phase_divider,
    render_timestamp_divider,
)
from ._agent_display_header import AgentHeader
from ._agent_display_xprompt import attach_xprompt_to_identity
from ._agent_display_hint_annotators import (
    hint_gate_annotator,
    hint_monitor_annotator,
    render_reply_with_hints,
)
from ._agent_gate_section import gate_phase_text
from ._agent_monitor_section import monitor_phase_text
from ._agent_session_reply_blocks import (
    block_meta_for_session_shell,
    phase_card_block,
    session_reply_heading,
)
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
    reply_text: AgentHeader,
) -> tuple[int, list[Any]]:
    """Render the xprompt, prompt, and reply/chat sections with file hints.

    Context sections go into ``header_text``; reply/chat sections go into
    ``reply_text``. Returns the updated hint counter plus extra Reply card
    parts: the legacy ``followup_agents`` path returns its
    ``BlockSpreadOnly`` heading and one :class:`CardBlock` per phase here so
    the caller can keep per-phase blocks; every other path returns no extra
    parts and appends into ``reply_text`` as before.
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
        xprompt = Text()
        xprompt_hints_before = hint_counter
        hint_counter = append_bounded_text_with_file_hints(
            xprompt,
            raw_xprompt + "\n",
            hint_counter,
            hint_mappings,
            workspace_dir,
            matcher=iter_xprompt_file_path_matches,
        )
        xprompt_source = xprompt.plain
        hint_spans = tuple(xprompt.spans)
        apply_authored_prompt_overlays(
            xprompt,
            xprompt_source,
            highlight_context,
            region_start=0,
            include_xprompt=True,
            hint_spans=hint_spans,
        )
        if not attach_xprompt_to_identity(
            panel,
            header_text,
            xprompt,
            has_hints=hint_counter != xprompt_hints_before,
        ):
            append_section_heading(header_text, "AGENT XPROMPT")
            header_text.append_text(xprompt)
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
            phases = (agent, *agent.followup_agents)
            facts = legacy_followup_shell_facts(agent)
            reply_blocks: list[Any] = [
                BlockSpreadOnly(session_reply_heading(len(phases)))
            ]
            for number, (phase, phase_facts) in enumerate(
                zip(phases, facts, strict=True)
            ):
                block_id = card_block_id(phase.identity)
                segment = Text(end="")
                if phase.is_monitor:
                    annotate, hint_count = hint_monitor_annotator(
                        hint_counter,
                        hint_mappings,
                        workspace_dir,
                    )
                    segment.append_text(
                        monitor_phase_text(phase, annotate=annotate, block_id=block_id)
                    )
                    hint_counter = hint_count()
                elif phase.is_gate:
                    annotate, hint_count = hint_gate_annotator(
                        hint_counter,
                        hint_mappings,
                        workspace_dir,
                    )
                    segment.append_text(
                        gate_phase_text(phase, annotate=annotate, block_id=block_id)
                    )
                    hint_counter = hint_count()
                else:
                    segment.append_text(
                        render_phase_divider(
                            get_phase_label(phase),
                            phase.run_start_time or phase.start_time,
                            block_id=block_id,
                        )
                    )
                    hint_counter = render_reply_with_hints(
                        phase,
                        segment,
                        hint_counter,
                        hint_mappings,
                        workspace_dir,
                        humanize_text,
                    )
                reply_blocks.append(
                    phase_card_block(
                        phase,
                        [segment],
                        meta=block_meta_for_session_shell(phase_facts, number),
                    )
                )
            return hint_counter, reply_blocks
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

            append_section_heading(reply_text, "AGENT CHAT")

            chunks = agent.get_timestamped_reply_chunks()
            if chunks:
                for ts, chunk_text in chunks:
                    reply_text.append_text(render_timestamp_divider(ts))
                    content = chunk_text.strip()
                    if content:
                        content = humanize_text(content)
                        hint_counter = append_bounded_text_with_file_hints(
                            reply_text,
                            content + "\n",
                            hint_counter,
                            hint_mappings,
                            workspace_dir,
                        )
                        reply_text.append("\n")
            elif response_content:
                response_content = humanize_text(response_content)
                hint_counter = append_bounded_text_with_file_hints(
                    reply_text,
                    response_content + "\n",
                    hint_counter,
                    hint_mappings,
                    workspace_dir,
                )
            else:
                reply_text.append("No response file found.\n", style="dim italic")
        else:
            # AGENT REPLY section for running agents (with hints)
            append_section_heading(reply_text, "AGENT REPLY")

            live_reply = agent.get_live_reply_content()
            chunks = agent.get_timestamped_reply_chunks()
            if chunks:
                for ts, chunk_text in chunks:
                    reply_text.append_text(render_timestamp_divider(ts))
                    content = chunk_text.strip()
                    if content:
                        content = humanize_text(content)
                        hint_counter = append_bounded_text_with_file_hints(
                            reply_text,
                            content + "\n",
                            hint_counter,
                            hint_mappings,
                            workspace_dir,
                        )
                        reply_text.append("\n")
            elif live_reply:
                live_reply = humanize_text(live_reply)
                hint_counter = append_bounded_text_with_file_hints(
                    reply_text,
                    live_reply + "\n",
                    hint_counter,
                    hint_mappings,
                    workspace_dir,
                )
            else:
                reply_text.append(
                    "Waiting for agent response...\n",
                    style="dim italic",
                )
    else:
        header_text.append("No prompt file found.\n", style="dim italic")

    return hint_counter, []

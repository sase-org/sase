"""Agent display with file-path hints for the agent prompt panel."""

from rich.text import Text

from ...models.agent import Agent, AgentType
from ._agent_display_parts import (
    build_header_text,
    get_phase_label,
    get_prompt_content,
    render_phase_divider,
    render_timestamp_divider,
)
from ._file_path_hints import (
    append_text_with_file_hints,
    resolve_agent_workspace_dir,
)
from ._helpers import format_output


def _render_reply_with_hints(
    agent: Agent,
    target: Text,
    hint_counter: int,
    hint_mappings: dict[int, str],
    workspace_dir: str | None,
) -> int:
    """Render one agent's reply content with file hints into a Text."""
    chunks = agent.get_timestamped_reply_chunks()
    if chunks:
        for ts, chunk_text in chunks:
            target.append_text(render_timestamp_divider(ts))
            content = chunk_text.strip()
            if content:
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
        return append_text_with_file_hints(
            target,
            live_reply + "\n",
            hint_counter,
            hint_mappings,
            workspace_dir,
        )
    response_content = agent.get_response_content()
    if response_content:
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

    def update_display_with_hints(self, agent: Agent) -> dict[int, str]:
        """Render agent display with ``[N]`` file path hints.

        Same visual structure as :meth:`update_display` but scans xprompt,
        prompt, and chat sections for file paths and inserts numbered hint
        markers.  Syntax highlighting is temporarily replaced with plain
        text so that hint markers can be inserted inline.

        Args:
            agent: The Agent to display.

        Returns:
            Dict mapping hint numbers to resolved absolute file paths.
        """
        # Workflow top-level or bash/python/parallel: no hint support
        if (
            agent.agent_type == AgentType.WORKFLOW
            and not agent.is_workflow_child
            and not agent.appears_as_agent
        ):
            self.update_display(agent)  # type: ignore[attr-defined]
            return {}

        if agent.is_workflow_child and agent.step_type in (
            "bash",
            "python",
            "parallel",
        ):
            self.update_display(agent)  # type: ignore[attr-defined]
            return {}

        workspace_dir = resolve_agent_workspace_dir(
            agent.effective_workspace_num,
            agent.project_file,
            agent.workspace_dir,
        )
        hint_counter = 1
        hint_mappings: dict[int, str] = {}

        # Build header (same structured fields as normal display)
        header_text, _ = build_header_text(agent)

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
            header_text.append("AGENT XPROMPT\n", style="bold #D7AF5F underline")
            header_text.append("\n")
            hint_counter = append_text_with_file_hints(
                header_text,
                raw_xprompt + "\n",
                hint_counter,
                hint_mappings,
                workspace_dir,
            )
            header_text.append("\n")
            header_text.append("\u2500" * 50 + "\n", style="dim")
            header_text.append("\n")

        # AGENT PROMPT section (with file path hints, Text instead of Syntax)
        header_text.append("AGENT PROMPT\n", style="bold #D7AF5F underline")
        header_text.append("\n")

        prompt_content = get_prompt_content(agent)
        if prompt_content:
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
                header_text.append("AGENT REPLY\n", style="bold #D7AF5F underline")
                header_text.append("\n")

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
                header_text.append("AGENT CHAT\n", style="bold #D7AF5F underline")
                header_text.append("\n")

                chunks = agent.get_timestamped_reply_chunks()
                if chunks:
                    for ts, chunk_text in chunks:
                        header_text.append_text(render_timestamp_divider(ts))
                        content = chunk_text.strip()
                        if content:
                            hint_counter = append_text_with_file_hints(
                                header_text,
                                content + "\n",
                                hint_counter,
                                hint_mappings,
                                workspace_dir,
                            )
                            header_text.append("\n")
                elif response_content:
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
                header_text.append("AGENT REPLY\n", style="bold #D7AF5F underline")
                header_text.append("\n")

                live_reply = agent.get_live_reply_content()
                chunks = agent.get_timestamped_reply_chunks()
                if chunks:
                    for ts, chunk_text in chunks:
                        header_text.append_text(render_timestamp_divider(ts))
                        content = chunk_text.strip()
                        if content:
                            hint_counter = append_text_with_file_hints(
                                header_text,
                                content + "\n",
                                hint_counter,
                                hint_mappings,
                                workspace_dir,
                            )
                            header_text.append("\n")
                elif live_reply:
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
        return hint_mappings

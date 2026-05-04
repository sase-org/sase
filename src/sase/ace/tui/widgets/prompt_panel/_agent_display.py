"""Agent display mixin for the agent prompt panel."""

from datetime import datetime

from rich.console import Group
from rich.syntax import Syntax
from rich.text import Text

from ...models.agent import Agent, AgentType, AttemptRecord
from ...util.lazy_syntax import lazy_renderable
from ...util.trace import tui_trace
from ._agent_display_parts import (
    build_header_text,
    get_phase_label,
    get_prompt_content,
    render_agent_reply_content,
    render_attempt_divider,
    render_phase_divider,
    render_timestamp_divider,
)
from ._helpers import format_output


def _should_render_merged(agent: Agent, attempt_view_mode: str) -> bool:
    """Whether to prepend attempt_history dividers to the reply content."""
    return attempt_view_mode == "merged" and bool(agent.attempt_history)


def _render_merged_attempt_history(agent: Agent) -> list:
    """Render prior attempts followed by the current attempt divider.

    Emits one divider + reply block for each record in ``agent.attempt_history``
    followed by a ``CURRENT`` divider. The caller is responsible for appending
    the current attempt's reply content afterwards.
    """
    renderables: list = []
    for record in agent.attempt_history:
        renderables.append(render_attempt_divider(record, is_current=False))
        chunks = record.get_timestamped_reply_chunks()
        if chunks:
            for ts, chunk_text in chunks:
                renderables.append(render_timestamp_divider(ts))
                content = chunk_text.strip()
                if content:
                    renderables.append(lazy_renderable(content, "markdown"))
            continue
        reply = record.get_reply_content()
        if reply and reply.strip():
            renderables.append(lazy_renderable(reply, "markdown"))
    renderables.append(
        render_attempt_divider(
            None, is_current=True, fallback_model=agent.fallback_model
        )
    )
    return renderables


class AgentDisplayMixin:
    """Mixin providing agent-specific display methods for AgentPromptPanel."""

    # Reactive-ish field set by AgentDetail before calling update_display.
    attempt_view_mode: str = "merged"
    # When non-None, pin the prompt panel to the matching attempt_history
    # record. Exclusive with the merged / current-only toggle.
    attempt_pinned_number: int | None = None

    def update_display(self, agent: Agent) -> None:
        """Update with agent information and prompt.

        Args:
            agent: The Agent to display.
        """
        with tui_trace("widget.prompt_panel.update_display"):
            self._update_display_impl(agent)

    def update_header_only(self, agent: Agent) -> None:
        """Render only the agent-details header + inline error traceback.

        Phase-3 immediate path: builds the cheap, in-memory header and
        renders it directly. Does **not** touch the artifact cache, list
        the artifacts directory, or read prompt / reply / response files.
        The debounced full update path is responsible for filling in the
        prompt body, reply, thinking, and file content shortly after.
        """
        with tui_trace("widget.prompt_panel.update_header_only"):
            header_text, error_tb_syntax = build_header_text(agent, cheap=True)
            if error_tb_syntax is not None:
                self.update(Group(header_text, error_tb_syntax))  # type: ignore[attr-defined]
            else:
                self.update(header_text)  # type: ignore[attr-defined]

    def _update_display_impl(self, agent: Agent) -> None:
        # Attempt-pinned view: render the selected prior attempt's full error
        # + prompt + captured reply; skip all other rendering paths.
        if self.attempt_pinned_number is not None:
            self._render_attempt_pinned(agent, self.attempt_pinned_number)  # type: ignore[attr-defined]
            return

        # Check if this is a top-level workflow agent that should display as workflow
        # Workflows with appears_as_agent=True should show as regular agents
        # Workflow children (steps) should show the normal agent view with prompt/chat
        if (
            agent.agent_type == AgentType.WORKFLOW
            and not agent.is_workflow_child
            and not agent.appears_as_agent
        ):
            self._update_workflow_display(agent)  # type: ignore[attr-defined]
            return

        header_text, error_tb_syntax = build_header_text(agent)

        # Check if this is a bash/python workflow step - display differently
        if agent.is_workflow_child and agent.step_type in ("bash", "python"):
            self._update_bash_python_display(agent, header_text, error_tb_syntax)
            return

        # Check if this is a parallel workflow step - show output only, no prompt
        if agent.is_workflow_child and agent.step_type == "parallel":
            self._update_parallel_display(agent, header_text, error_tb_syntax)
            return

        # AGENT XPROMPT section
        raw_xprompt = agent.get_raw_xprompt_content()
        if raw_xprompt:
            header_text.append("AGENT XPROMPT\n", style="bold #D7AF5F underline")
            header_text.append("\n")
            header_text.append(f"{raw_xprompt}\n")
            header_text.append("\n")
            header_text.append("\u2500" * 50 + "\n", style="dim")
            header_text.append("\n")

        # AGENT PROMPT section
        header_text.append("AGENT PROMPT\n", style="bold #D7AF5F underline")
        header_text.append("\n")

        # Get and display prompt content
        prompt_content = get_prompt_content(agent)
        if prompt_content:
            prompt_syntax = lazy_renderable(prompt_content, "markdown")

            # For agents with follow-ups, show consolidated reply
            if agent.followup_agents:
                renderables: list = [header_text]
                if error_tb_syntax:
                    renderables.append(error_tb_syntax)
                renderables.append(prompt_syntax)

                reply_header = Text()
                reply_header.append("\n")
                reply_header.append("\u2500" * 50 + "\n", style="dim")
                reply_header.append("\n")
                reply_header.append("AGENT REPLY\n", style="bold #D7AF5F underline")
                reply_header.append("\n")
                renderables.append(reply_header)

                # Main agent's phase
                renderables.append(
                    render_phase_divider(
                        get_phase_label(agent),
                        agent.run_start_time or agent.start_time,
                    )
                )
                renderables.extend(render_agent_reply_content(agent))

                # Follow-up phases
                for followup in agent.followup_agents:
                    renderables.append(
                        render_phase_divider(
                            get_phase_label(followup),
                            followup.run_start_time or followup.start_time,
                        )
                    )
                    renderables.extend(render_agent_reply_content(followup))

                self.update(Group(*renderables))  # type: ignore[attr-defined]
            # For completed or failed agents/steps, also show the response
            elif agent.status in ("DONE", "FAILED"):
                reply_header = Text()
                reply_header.append("\n")
                reply_header.append("\u2500" * 50 + "\n", style="dim")
                reply_header.append("\n")
                reply_header.append("AGENT CHAT\n", style="bold #D7AF5F underline")
                reply_header.append("\n")

                response_content = agent.get_response_content()

                # Fallback: for workflow step agents, try step_output if no response file
                # Only use step_output when it has displayable content (_raw/_data),
                # not when it only contains meta_* metadata fields.
                if (
                    response_content is None
                    and agent.is_workflow_child
                    and isinstance(agent.step_output, dict)
                    and ("_raw" in agent.step_output or "_data" in agent.step_output)
                ):
                    response_content = format_output(agent.step_output)

                renderables = [header_text]
                if error_tb_syntax:
                    renderables.append(error_tb_syntax)
                renderables.append(prompt_syntax)

                chunks = agent.get_timestamped_reply_chunks()
                merge_history = _should_render_merged(agent, self.attempt_view_mode)
                if chunks:
                    renderables.append(reply_header)
                    if merge_history:
                        renderables.extend(_render_merged_attempt_history(agent))
                    for ts, chunk_text in chunks:
                        renderables.append(render_timestamp_divider(ts))
                        content = chunk_text.strip()
                        if content:
                            renderables.append(lazy_renderable(content, "markdown"))
                elif response_content:
                    response_syntax = lazy_renderable(response_content, "markdown")
                    renderables.append(reply_header)
                    if merge_history:
                        renderables.extend(_render_merged_attempt_history(agent))
                    renderables.append(response_syntax)
                else:
                    reply_header.append("No response file found.\n", style="dim italic")
                    renderables.append(reply_header)

                self.update(Group(*renderables))  # type: ignore[attr-defined]
            else:
                renderables_other: list = [header_text]
                if error_tb_syntax:
                    renderables_other.append(error_tb_syntax)
                renderables_other.append(prompt_syntax)

                # AGENT REPLY section for running agents
                reply_header = Text()
                reply_header.append("\n")
                reply_header.append("\u2500" * 50 + "\n", style="dim")
                reply_header.append("\n")
                reply_header.append("AGENT REPLY\n", style="bold #D7AF5F underline")
                reply_header.append("\n")

                live_reply = agent.get_live_reply_content()
                chunks = agent.get_timestamped_reply_chunks()
                merge_history = _should_render_merged(agent, self.attempt_view_mode)
                if chunks:
                    renderables_other.append(reply_header)
                    if merge_history:
                        renderables_other.extend(_render_merged_attempt_history(agent))
                    for ts, chunk_text in chunks:
                        renderables_other.append(render_timestamp_divider(ts))
                        content = chunk_text.strip()
                        if content:
                            renderables_other.append(
                                lazy_renderable(content, "markdown")
                            )
                elif live_reply:
                    reply_syntax = lazy_renderable(live_reply, "markdown")
                    renderables_other.append(reply_header)
                    if merge_history:
                        renderables_other.extend(_render_merged_attempt_history(agent))
                    renderables_other.append(reply_syntax)
                else:
                    reply_header.append(
                        "Waiting for agent response...\n",
                        style="dim italic",
                    )
                    renderables_other.append(reply_header)

                self.update(Group(*renderables_other))  # type: ignore[attr-defined]
        else:
            header_text.append("No prompt file found.\n", style="dim italic")
            if error_tb_syntax:
                self.update(Group(header_text, error_tb_syntax))  # type: ignore[attr-defined]
            else:
                self.update(header_text)  # type: ignore[attr-defined]

    def _update_bash_python_display(
        self,
        agent: Agent,
        header_text: Text,
        error_tb_syntax: Syntax | None = None,
    ) -> None:
        """Display bash command or python code with output.

        Args:
            agent: The workflow step agent to display.
            header_text: The Text object with header content to append to.
            error_tb_syntax: Optional traceback Syntax renderable.
        """
        if agent.step_type == "bash":
            source_label = "BASH COMMAND"
            syntax_lang = "bash"
        else:
            source_label = "PYTHON CODE"
            syntax_lang = "python"

        # Show source header
        header_text.append(f"{source_label}\n", style="bold #D7AF5F underline")
        header_text.append("\n")

        source_content: object
        if agent.step_source:
            source_content = lazy_renderable(agent.step_source, syntax_lang)
        else:
            source_content = Text("No source available.\n", style="dim italic")

        # Show output section
        output_header = Text()
        output_header.append("\n")
        output_header.append("\u2500" * 50 + "\n", style="dim")
        output_header.append("\n")
        output_header.append("STEP OUTPUT\n", style="bold #D7AF5F underline")
        output_header.append("\n")

        renderables: list = [header_text]
        if error_tb_syntax:
            renderables.append(error_tb_syntax)
        renderables.append(source_content)

        if agent.step_output:
            output_str = format_output(agent.step_output)
            output_syntax = lazy_renderable(output_str, "json")
            renderables.extend([output_header, output_syntax])
        else:
            output_header.append("No output available.\n", style="dim italic")
            renderables.append(output_header)

        self.update(Group(*renderables))  # type: ignore[attr-defined]

    def _update_parallel_display(
        self,
        agent: Agent,
        header_text: Text,
        error_tb_syntax: Syntax | None = None,
    ) -> None:
        """Display output for a parallel workflow step (no prompt section).

        Args:
            agent: The workflow step agent to display.
            header_text: The Text object with header content to append to.
            error_tb_syntax: Optional traceback Syntax renderable.
        """
        header_text.append("STEP OUTPUT\n", style="bold #D7AF5F underline")
        header_text.append("\n")

        renderables: list = [header_text]
        if error_tb_syntax:
            renderables.append(error_tb_syntax)

        if agent.step_output:
            output_str = format_output(agent.step_output)
            output_syntax = lazy_renderable(output_str, "json")
            renderables.append(output_syntax)
        else:
            renderables.append(Text("No output available.\n", style="dim italic"))

        self.update(Group(*renderables))  # type: ignore[attr-defined]

    def _render_attempt_pinned(self, agent: Agent, attempt_number: int) -> None:
        """Render the prompt panel pinned to a prior attempt.

        Shows the attempt banner (number, timestamp, outcome), the full
        ``error_full`` traceback, the agent prompt (invariant across retries),
        and the archived ``live_reply.md`` for the attempt. Thinking/files
        aren't snapshotted per-attempt; the detail panel hides those panels.
        """
        record = _find_attempt(agent, attempt_number)
        renderables: list = []
        if record is None:
            missing = Text()
            missing.append(
                f"Attempt {attempt_number} not found for this agent.\n",
                style="bold #FF5F5F",
            )
            self.update(missing)  # type: ignore[attr-defined]
            return

        renderables.append(
            _render_attempt_banner(record, total=len(agent.attempt_history))
        )

        if record.error_full.strip():
            renderables.append(lazy_renderable(record.error_full, "pytb"))
        elif record.error_snippet:
            snippet = Text()
            snippet.append(f"{record.error_snippet}\n", style="#FF5F5F")
            renderables.append(snippet)

        divider = Text()
        divider.append("\n")
        divider.append("─" * 50 + "\n", style="dim")
        divider.append("\n")
        renderables.append(divider)

        prompt_header = Text()
        prompt_header.append("AGENT PROMPT\n", style="bold #D7AF5F underline")
        prompt_header.append("\n")
        renderables.append(prompt_header)
        prompt_content = get_prompt_content(agent)
        if prompt_content:
            renderables.append(lazy_renderable(prompt_content, "markdown"))
        else:
            renderables.append(Text("No prompt file found.\n", style="dim italic"))

        reply_header = Text()
        reply_header.append("\n")
        reply_header.append("─" * 50 + "\n", style="dim")
        reply_header.append("\n")
        reply_header.append(
            f"ATTEMPT {record.attempt_number} REPLY\n",
            style="bold #D7AF5F underline",
        )
        reply_header.append("\n")
        renderables.append(reply_header)

        chunks = record.get_timestamped_reply_chunks()
        if chunks:
            for ts, chunk_text in chunks:
                renderables.append(render_timestamp_divider(ts))
                content = chunk_text.strip()
                if content:
                    renderables.append(
                        Syntax(content, "markdown", theme="monokai", word_wrap=True)
                    )
        else:
            reply = record.get_reply_content()
            if reply and reply.strip():
                renderables.append(
                    Syntax(reply, "markdown", theme="monokai", word_wrap=True)
                )
            else:
                renderables.append(
                    Text("(no partial reply captured)\n", style="dim italic")
                )

        self.update(Group(*renderables))  # type: ignore[attr-defined]

    def show_empty(self) -> None:
        """Show empty state."""
        text = Text("No agent selected", style="dim italic")
        self.update(text)  # type: ignore[attr-defined]


def _find_attempt(agent: Agent, attempt_number: int) -> AttemptRecord | None:
    for record in agent.attempt_history:
        if record.attempt_number == attempt_number:
            return record
    return None


def _render_attempt_banner(record: AttemptRecord, *, total: int) -> Text:
    """Render the ``Viewing Attempt N of M`` banner for the pinned view."""
    banner = Text()
    try:
        hhmmss = record.start_hhmmss
    except (ValueError, OSError):
        hhmmss = "??:??:??"
    try:
        end_time = datetime.fromtimestamp(record.end_epoch).strftime("%H:%M:%S")
    except (ValueError, OSError):
        end_time = "??:??:??"
    banner.append(
        f"Viewing Attempt {record.attempt_number} of {total}",
        style="bold #FF8700",
    )
    banner.append(
        f" · started {hhmmss} · {record.status} at {end_time}\n",
        style="dim #FF8700",
    )
    if record.used_fallback and record.model:
        banner.append(f"Fallback model: {record.model}\n", style="dim #FF8700")
    banner.append("\n")
    banner.append("ATTEMPT ERROR\n", style="bold #FF5F5F underline")
    banner.append("\n")
    return banner

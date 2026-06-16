"""Agent display mixin for the agent prompt panel."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from rich.console import Group
from rich.syntax import Syntax
from rich.text import Text
from textual.worker import Worker, WorkerState

from ...models.agent import Agent, AgentType, AttemptRecord
from ...models.agent_bead import resolve_bead_display, should_resolve_bead_display
from ...util.lazy_syntax import LazySyntaxRenderCache, lazy_renderable
from ...util.trace import tui_trace
from ._agent_display_parts import (
    build_detail_header_summary,
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


def _render_merged_attempt_history(
    agent: Agent,
    render_markdown: Callable[[str], object],
) -> list:
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
                    renderables.append(render_markdown(content))
            continue
        reply = record.get_reply_content()
        if reply and reply.strip():
            renderables.append(render_markdown(reply))
    renderables.append(
        render_attempt_divider(
            None, is_current=True, fallback_model=agent.fallback_model
        )
    )
    return renderables


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
            self._reset_markdown_render_cache_for_agent(agent)
            self._update_display_impl(agent)
            self._start_agent_bead_display_resolve_from_context(agent)

    def update_header_only(self, agent: Agent) -> None:
        """Render only the agent-details header + inline error traceback.

        Phase-3 immediate path: builds the cheap, in-memory header and
        renders it directly. Does **not** touch the artifact cache, list
        the artifacts directory, or read prompt / reply / response files.
        The debounced full update path is responsible for filling in the
        prompt body, reply, tools, and file content shortly after.
        """
        with tui_trace("widget.prompt_panel.update_header_only"):
            self._cancel_agent_bead_display_worker_for_selection_change(agent)
            header_text, error_tb_syntax = build_header_text(agent, cheap=True)
            if error_tb_syntax is not None:
                self.update(Group(header_text, error_tb_syntax))  # type: ignore[attr-defined]
            else:
                self.update(header_text)  # type: ignore[attr-defined]

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

        self._update_display_impl(request.agent)

    def _markdown_render_cache(self) -> LazySyntaxRenderCache:
        cache = getattr(self, "_agent_markdown_render_cache", None)
        if cache is None:
            cache = LazySyntaxRenderCache(max_entries=24)
            self._agent_markdown_render_cache = cache
        return cache

    def _reset_markdown_render_cache_for_agent(self, agent: Agent) -> None:
        identity = agent.identity
        previous_identity = getattr(self, "_agent_markdown_render_cache_identity", None)
        if previous_identity != identity:
            cache = getattr(self, "_agent_markdown_render_cache", None)
            if cache is not None:
                cache.clear()
            self._agent_markdown_render_cache_identity = identity

    def _render_markdown(self, content: str) -> object:
        return lazy_renderable(
            content,
            "markdown",
            render_cache=self._markdown_render_cache(),
        )

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

        header_text, error_tb_syntax = build_header_text(
            agent,
            summary=build_detail_header_summary(agent),
        )

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
            prompt_syntax = self._render_markdown(prompt_content)

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
                renderables.extend(
                    render_agent_reply_content(agent, self._render_markdown)
                )

                # Follow-up phases
                for followup in agent.followup_agents:
                    renderables.append(
                        render_phase_divider(
                            get_phase_label(followup),
                            followup.run_start_time or followup.start_time,
                        )
                    )
                    renderables.extend(
                        render_agent_reply_content(followup, self._render_markdown)
                    )

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
                        renderables.extend(
                            _render_merged_attempt_history(
                                agent,
                                self._render_markdown,
                            )
                        )
                    for ts, chunk_text in chunks:
                        renderables.append(render_timestamp_divider(ts))
                        content = chunk_text.strip()
                        if content:
                            renderables.append(self._render_markdown(content))
                elif response_content:
                    response_syntax = self._render_markdown(response_content)
                    renderables.append(reply_header)
                    if merge_history:
                        renderables.extend(
                            _render_merged_attempt_history(
                                agent,
                                self._render_markdown,
                            )
                        )
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
                        renderables_other.extend(
                            _render_merged_attempt_history(
                                agent,
                                self._render_markdown,
                            )
                        )
                    for ts, chunk_text in chunks:
                        renderables_other.append(render_timestamp_divider(ts))
                        content = chunk_text.strip()
                        if content:
                            renderables_other.append(self._render_markdown(content))
                elif live_reply:
                    reply_syntax = self._render_markdown(live_reply)
                    renderables_other.append(reply_header)
                    if merge_history:
                        renderables_other.extend(
                            _render_merged_attempt_history(
                                agent,
                                self._render_markdown,
                            )
                        )
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
        and the archived ``live_reply.md`` for the attempt. Tools/files
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
            renderables.append(self._render_markdown(prompt_content))
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
                    renderables.append(self._render_markdown(content))
        else:
            reply = record.get_reply_content()
            if reply and reply.strip():
                renderables.append(self._render_markdown(reply))
            else:
                renderables.append(
                    Text("(no partial reply captured)\n", style="dim italic")
                )

        self.update(Group(*renderables))  # type: ignore[attr-defined]

    def show_empty(self) -> None:
        """Show empty state."""
        current_worker = getattr(self, "_agent_bead_display_worker", None)
        if current_worker is not None and getattr(current_worker, "is_running", False):
            current_worker.cancel()
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

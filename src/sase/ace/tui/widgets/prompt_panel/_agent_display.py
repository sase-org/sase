"""Agent display mixin for the agent prompt panel."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from rich.console import Group
from rich.syntax import Syntax
from rich.text import Text

from ...models.agent import Agent, AgentType
from ._helpers import (
    append_model_field,
    extract_meta_fields,
    format_embedded_workflows,
    format_output,
    load_embedded_workflows,
)


class AgentDisplayMixin:
    """Mixin providing agent-specific display methods for AgentPromptPanel."""

    def update_display(self, agent: Agent) -> None:
        """Update with agent information and prompt.

        Args:
            agent: The Agent to display.
        """
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

        header_text, error_tb_syntax = self._build_header_text(agent)

        # Check if this is a bash/python workflow step - display differently
        if agent.is_workflow_child and agent.step_type in ("bash", "python"):
            self._update_bash_python_display(agent, header_text, error_tb_syntax)
            return

        # Check if this is a parallel workflow step - show output only, no prompt
        if agent.is_workflow_child and agent.step_type == "parallel":
            self._update_parallel_display(agent, header_text, error_tb_syntax)
            return

        # AGENT XPROMPT section (only shown while agent is running/waiting)
        if agent.status not in ("DONE", "FAILED"):
            raw_xprompt = agent.get_raw_xprompt_content()
            if raw_xprompt:
                header_text.append("AGENT XPROMPT\n", style="bold #D7AF5F underline")
                header_text.append("\n")
                header_text.append(f"{raw_xprompt}\n")
                header_text.append("\n")
                header_text.append("─" * 50 + "\n", style="dim")
                header_text.append("\n")

        # AGENT PROMPT section
        header_text.append("AGENT PROMPT\n", style="bold #D7AF5F underline")
        header_text.append("\n")

        # Get and display prompt content
        prompt_content = self._get_prompt_content(agent)
        if prompt_content:
            # Render markdown with syntax highlighting
            prompt_syntax = Syntax(
                prompt_content,
                "markdown",
                theme="monokai",
                word_wrap=True,
            )

            # For completed or failed agents/steps, also show the response
            if agent.status in ("DONE", "FAILED"):
                reply_header = Text()
                reply_header.append("\n")
                reply_header.append("─" * 50 + "\n", style="dim")
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

                renderables: list[Text | Syntax] = [header_text]
                if error_tb_syntax:
                    renderables.append(error_tb_syntax)
                renderables.append(prompt_syntax)

                chunks = agent.get_timestamped_reply_chunks()
                if chunks:
                    renderables.append(reply_header)
                    for ts, chunk_text in chunks:
                        renderables.append(self._render_timestamp_divider(ts))
                        content = chunk_text.strip()
                        if content:
                            renderables.append(
                                Syntax(
                                    content, "markdown", theme="monokai", word_wrap=True
                                )
                            )
                elif response_content:
                    response_syntax = Syntax(
                        response_content,
                        "markdown",
                        theme="monokai",
                        word_wrap=True,
                    )
                    renderables.extend([reply_header, response_syntax])
                else:
                    reply_header.append("No response file found.\n", style="dim italic")
                    renderables.append(reply_header)

                # Aggregate follow-up replies for main plan entries
                if self._is_main_plan_entry(agent):
                    related = self._collect_related_agents(agent)
                    if related:
                        renderables.extend(self._render_followup_renderables(related))

                self.update(Group(*renderables))  # type: ignore[attr-defined]
            else:
                renderables_other: list[Text | Syntax] = [header_text]
                if error_tb_syntax:
                    renderables_other.append(error_tb_syntax)
                renderables_other.append(prompt_syntax)

                # AGENT REPLY section for running agents
                reply_header = Text()
                reply_header.append("\n")
                reply_header.append("─" * 50 + "\n", style="dim")
                reply_header.append("\n")
                reply_header.append("AGENT REPLY\n", style="bold #D7AF5F underline")
                reply_header.append("\n")

                live_reply = agent.get_live_reply_content()
                chunks = agent.get_timestamped_reply_chunks()
                if chunks:
                    renderables_other.append(reply_header)
                    for ts, chunk_text in chunks:
                        renderables_other.append(self._render_timestamp_divider(ts))
                        content = chunk_text.strip()
                        if content:
                            renderables_other.append(
                                Syntax(
                                    content,
                                    "markdown",
                                    theme="monokai",
                                    word_wrap=True,
                                )
                            )
                elif live_reply:
                    reply_syntax = Syntax(
                        live_reply,
                        "markdown",
                        theme="monokai",
                        word_wrap=True,
                    )
                    renderables_other.extend([reply_header, reply_syntax])
                else:
                    reply_header.append(
                        "Waiting for agent response...\n",
                        style="dim italic",
                    )
                    renderables_other.append(reply_header)

                # Aggregate follow-up replies for main plan entries
                if self._is_main_plan_entry(agent):
                    related = self._collect_related_agents(agent)
                    if related:
                        renderables_other.extend(
                            self._render_followup_renderables(related)
                        )

                self.update(Group(*renderables_other))  # type: ignore[attr-defined]
        else:
            header_text.append("No prompt file found.\n", style="dim italic")
            if error_tb_syntax:
                self.update(Group(header_text, error_tb_syntax))  # type: ignore[attr-defined]
            else:
                self.update(header_text)  # type: ignore[attr-defined]

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
        from ._file_path_hints import (
            append_text_with_file_hints,
            resolve_agent_workspace_dir,
        )

        # Workflow top-level or bash/python/parallel: no hint support
        if (
            agent.agent_type == AgentType.WORKFLOW
            and not agent.is_workflow_child
            and not agent.appears_as_agent
        ):
            self.update_display(agent)
            return {}

        if agent.is_workflow_child and agent.step_type in (
            "bash",
            "python",
            "parallel",
        ):
            self.update_display(agent)
            return {}

        workspace_dir = resolve_agent_workspace_dir(
            agent.effective_workspace_num, agent.project_file
        )
        hint_counter = 1
        hint_mappings: dict[int, str] = {}

        # Build header (same structured fields as normal display)
        header_text, _ = self._build_header_text(agent)

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
        if agent.status not in ("DONE", "FAILED"):
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
                header_text.append("─" * 50 + "\n", style="dim")
                header_text.append("\n")

        # AGENT PROMPT section (with file path hints, Text instead of Syntax)
        header_text.append("AGENT PROMPT\n", style="bold #D7AF5F underline")
        header_text.append("\n")

        prompt_content = self._get_prompt_content(agent)
        if prompt_content:
            hint_counter = append_text_with_file_hints(
                header_text,
                prompt_content + "\n",
                hint_counter,
                hint_mappings,
                workspace_dir,
            )

            # AGENT CHAT section for completed agents (with hints)
            if agent.status in ("DONE", "FAILED"):
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
                header_text.append("─" * 50 + "\n", style="dim")
                header_text.append("\n")
                header_text.append("AGENT CHAT\n", style="bold #D7AF5F underline")
                header_text.append("\n")

                chunks = agent.get_timestamped_reply_chunks()
                if chunks:
                    for ts, chunk_text in chunks:
                        header_text.append_text(self._render_timestamp_divider(ts))
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

                # Aggregate follow-up replies for main plan entries (with hints)
                if self._is_main_plan_entry(agent):
                    related = self._collect_related_agents(agent)
                    if related:
                        hint_counter = self._render_followup_hints(
                            related,
                            header_text,
                            hint_counter,
                            hint_mappings,
                            workspace_dir,
                        )
            else:
                # AGENT REPLY section for running agents (with hints)
                header_text.append("\n")
                header_text.append("─" * 50 + "\n", style="dim")
                header_text.append("\n")
                header_text.append("AGENT REPLY\n", style="bold #D7AF5F underline")
                header_text.append("\n")

                live_reply = agent.get_live_reply_content()
                chunks = agent.get_timestamped_reply_chunks()
                if chunks:
                    for ts, chunk_text in chunks:
                        header_text.append_text(self._render_timestamp_divider(ts))
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

                # Aggregate follow-up replies for main plan entries (with hints)
                if self._is_main_plan_entry(agent):
                    related = self._collect_related_agents(agent)
                    if related:
                        hint_counter = self._render_followup_hints(
                            related,
                            header_text,
                            hint_counter,
                            hint_mappings,
                            workspace_dir,
                        )
        else:
            header_text.append("No prompt file found.\n", style="dim italic")

        self.update(header_text)  # type: ignore[attr-defined]
        return hint_mappings

    @staticmethod
    def _render_timestamp_divider(iso_timestamp: str) -> Text:
        """Create a styled timestamp divider: ``─── HH:MM:SS ───…───``."""
        try:
            dt = datetime.fromisoformat(iso_timestamp)
            local_dt = dt.astimezone()
            time_str = local_dt.strftime("%H:%M:%S")
        except (ValueError, OSError):
            time_str = "??:??:??"
        prefix = f"─── {time_str} "
        suffix_len = 50 - len(prefix)
        divider = Text()
        divider.append(prefix + "─" * suffix_len + "\n", style="dim #D7D7FF")
        return divider

    def _build_header_text(self, agent: Agent) -> tuple[Text, Syntax | None]:
        """Build the AGENT DETAILS header section with trailing separator.

        Contains agent metadata (name, workspace, model, timestamps, etc.),
        error information, and a trailing separator line.

        Args:
            agent: The Agent to build the header for.

        Returns:
            Tuple of (header_text, error_traceback_syntax).
        """
        header_text = Text()

        # Header - AGENT DETAILS
        header_text.append("AGENT DETAILS\n", style="bold #D7AF5F underline")
        header_text.append("\n")

        # Extract meta_* overrides from step_output
        meta_project = None
        meta_changespec = None
        if agent.step_output and isinstance(agent.step_output, dict):
            meta_project = agent.step_output.get("meta_project")
            meta_changespec = agent.step_output.get("meta_changespec")

        # For workflow step agents, show "Step" instead of "ChangeSpec"
        if agent.is_workflow_child and agent.step_name:
            header_text.append("Step: ", style="bold #87D7FF")
            header_text.append(f"{agent.step_name}\n", style="#00D7AF")
        elif meta_changespec:
            header_text.append("ChangeSpec: ", style="bold #87D7FF")
            header_text.append(f"{meta_changespec}", style="#00D7AF")
            if agent.cl_num:
                header_text.append(" (")
                header_text.append(agent.cl_num, style="bold underline #569CD6")
                header_text.append(")")
            header_text.append("\n")
        elif meta_project:
            header_text.append("Project: ", style="bold #87D7FF")
            header_text.append(f"{meta_project}\n", style="#00D7AF")
        elif agent.is_project_agent:
            header_text.append("Project: ", style="bold #87D7FF")
            header_text.append(f"{agent.cl_name}\n", style="#00D7AF")
        else:
            # ChangeSpec name
            header_text.append("ChangeSpec: ", style="bold #87D7FF")
            header_text.append(f"{agent.cl_name}", style="#00D7AF")
            if agent.cl_num:
                header_text.append(" (")
                header_text.append(agent.cl_num, style="bold underline #569CD6")
                header_text.append(")")
            header_text.append("\n")

        # Workspace (if available)
        # Hide workspace for deferred-workspace agents (workspace_num=0 means
        # no workspace allocated yet, used by WAITING agents)
        workspace_num = agent.effective_workspace_num
        if workspace_num is not None and workspace_num > 0:
            header_text.append("Workspace: ", style="bold #87D7FF")
            header_text.append(f"#{workspace_num}\n", style="#5FD7FF")

        # Workflow (if available) — only for multi-step workflows, not
        # appears-as-agent workflows (which are embedded, not standalone)
        if agent.workflow and not agent.appears_as_agent:
            header_text.append("Workflow: ", style="bold #87D7FF")
            header_text.append(f"{agent.workflow}\n")

        # Embedded Workflows (if available) - only for agent/prompt steps
        if agent.step_type not in ("bash", "python", "parallel"):
            embedded_workflows = load_embedded_workflows(agent)
            if embedded_workflows:
                header_text.append("Embedded Workflows: ", style="bold #87D7FF")
                header_text.append(f"{format_embedded_workflows(embedded_workflows)}\n")

        # Model (with provider-themed styling)
        append_model_field(header_text, agent.model, agent.llm_provider)

        # VCS provider
        if agent.vcs_provider:
            header_text.append("VCS: ", style="bold #87D7FF")
            header_text.append(f"{agent.vcs_provider}\n", style="#5FD7AF")

        # Mode (autonomous agents)
        if agent.approve:
            header_text.append("Mode: ", style="bold #87D7FF")
            header_text.append("⚡ Auto-Approve\n", style="bold #00FFFF")

        # PID (if available)
        if agent.pid:
            header_text.append("PID: ", style="bold #87D7FF")
            header_text.append(f"{agent.pid}\n", style="#FF87D7 bold")

        # BUG field (if available)
        if agent.bug:
            header_text.append("BUG: ", style="bold #87D7FF")
            header_text.append(f"{agent.bug}\n", style="bold underline #569CD6")

        # Agent name (when assigned via %name directive or manual TUI naming)
        if agent.agent_name:
            header_text.append("Name: ", style="bold #87D7FF")
            header_text.append(f"@{agent.agent_name}\n", style="#FF87D7")

        # Waiting info (when agent is waiting for dependencies)
        if agent.waiting_for:
            header_text.append("Waiting for: ", style="bold #87D7FF")
            header_text.append(f"{', '.join(agent.waiting_for)}\n", style="#FF87D7")

        # Retry info (for agents that have retried or are using fallback)
        if agent.retry_count > 0 or agent.using_fallback:
            header_text.append("Retries: ", style="bold #87D7FF")
            header_text.append(
                f"{agent.retry_count}/{agent.max_retries}\n", style="#FF8700"
            )
            if agent.fallback_model:
                header_text.append("Fallback: ", style="bold #87D7FF")
                if agent.using_fallback:
                    header_text.append(
                        f"{agent.fallback_model}\n", style="bold #FF8700"
                    )
                else:
                    header_text.append(f"{agent.fallback_model}\n", style="dim #FF8700")

        # Timestamp(s)
        header_text.append("Timestamps: ", style="bold #87D7FF")
        header_text.append(f"{agent.timestamps_display}\n", style="#D7D7FF")

        # Meta fields from step output
        if agent.step_output and isinstance(agent.step_output, dict):
            meta_fields = extract_meta_fields(agent.step_output)
            if meta_fields:
                header_text.append("\n")
                for name, value in meta_fields:
                    header_text.append(f"{name}: ", style="bold #87D7FF")
                    header_text.append(f"{value}\n", style="#5FD75F")

        # Error message (for failed agents)
        if agent.error_message:
            header_text.append("\n")
            header_text.append("ERROR\n", style="bold #FF5F5F underline")
            header_text.append(f"{agent.error_message}\n", style="bold #FF5F5F")
            if agent.output_path:
                header_text.append("Output: ", style="bold #87D7FF")
                header_text.append(f"{agent.output_path}\n", style="dim")

        # Compute traceback renderable for ERROR section (included in all paths)
        error_tb_syntax: Syntax | None = None
        if agent.error_traceback:
            error_tb_syntax = Syntax(
                agent.error_traceback,
                "pytb",
                theme="monokai",
                word_wrap=True,
            )

        # Separator
        header_text.append("\n")
        header_text.append("─" * 50 + "\n", style="dim")
        header_text.append("\n")

        return header_text, error_tb_syntax

    def _get_prompt_content(self, agent: Agent) -> str | None:
        """Get the prompt content for the agent.

        Args:
            agent: The agent to get prompt for.

        Returns:
            Prompt content, or None if not found.
        """
        artifacts_dir = agent.get_artifacts_dir()
        if artifacts_dir is None:
            return None

        artifacts_path = Path(artifacts_dir)

        # Look for any *_prompt.md file
        prompt_files = list(artifacts_path.glob("*_prompt.md"))

        if not prompt_files:
            return None

        # For workflow child agents, filter to the step-specific prompt file.
        # All workflow steps share the same artifacts_dir, so without filtering
        # we'd always show the most recently modified prompt (usually the last
        # step).
        if agent.is_workflow_child and agent.step_name:
            step_specific = [
                p
                for p in prompt_files
                if p.name.endswith(f"-{agent.step_name}_prompt.md")
            ]
            if step_specific:
                prompt_files = step_specific

        # Sort by modification time to get the most recent
        prompt_files.sort(key=lambda p: p.stat().st_mtime, reverse=True)

        try:
            with open(prompt_files[0], encoding="utf-8") as f:
                return f.read()
        except Exception:
            return None

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

        source_content: Syntax | Text
        if agent.step_source:
            source_content = Syntax(
                agent.step_source, syntax_lang, theme="monokai", word_wrap=True
            )
        else:
            source_content = Text("No source available.\n", style="dim italic")

        # Show output section
        output_header = Text()
        output_header.append("\n")
        output_header.append("─" * 50 + "\n", style="dim")
        output_header.append("\n")
        output_header.append("STEP OUTPUT\n", style="bold #D7AF5F underline")
        output_header.append("\n")

        renderables: list[Text | Syntax] = [header_text]
        if error_tb_syntax:
            renderables.append(error_tb_syntax)
        renderables.append(source_content)

        if agent.step_output:
            output_str = format_output(agent.step_output)
            output_syntax = Syntax(output_str, "json", theme="monokai", word_wrap=True)
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

        renderables: list[Text | Syntax] = [header_text]
        if error_tb_syntax:
            renderables.append(error_tb_syntax)

        if agent.step_output:
            output_str = format_output(agent.step_output)
            output_syntax = Syntax(output_str, "json", theme="monokai", word_wrap=True)
            renderables.append(output_syntax)
        else:
            renderables.append(Text("No output available.\n", style="dim italic"))

        self.update(Group(*renderables))  # type: ignore[attr-defined]

    # ------------------------------------------------------------------
    # Follow-up reply aggregation (planner rounds + coder)
    # ------------------------------------------------------------------

    @staticmethod
    def _is_main_plan_entry(agent: Agent) -> bool:
        """Check if *agent* is a top-level plan entry eligible for aggregation."""
        return (
            agent.role_suffix == ".plan"
            and not agent.is_workflow_child
            and agent.raw_suffix is not None
        )

    def _collect_related_agents(self, agent: Agent) -> list[Agent]:
        """Return follow-up agents for a main plan entry, sorted by start time.

        Related agents share ``parent_timestamp == agent.raw_suffix`` and have
        no ``parent_workflow`` (they are follow-up children, not workflow steps).
        """
        target_ts = agent.raw_suffix
        if target_ts is None:
            return []

        # Prefer the pre-fold list so folded children are still found.
        app = getattr(self, "app", None)
        candidates: list[Agent] = []
        if app is not None:
            candidates = getattr(app, "_agents_with_children", None) or []
            if not candidates:
                candidates = getattr(app, "_agents", None) or []

        related: list[Agent] = []
        for a in candidates:
            if (
                a.parent_timestamp == target_ts
                and a.parent_workflow is None
                and a is not agent
            ):
                related.append(a)

        # Sort by effective start time (ascending) for chronological reading.
        related.sort(key=lambda a: a.start_time or datetime.min)
        return related

    @staticmethod
    def _role_label(agent: Agent) -> str:
        """Compact role label for a follow-up agent (e.g. ``Planner (.2)``)."""
        suffix = agent.role_suffix or agent.raw_suffix or "?"
        if suffix == ".code":
            return f"Coder ({suffix})"
        return f"Planner ({suffix})"

    @staticmethod
    def _status_label(agent: Agent) -> str:
        """Short status string for the sub-section header."""
        if agent.status in ("DONE", "FAILED"):
            return agent.status
        return "running"

    def _render_followup_renderables(
        self,
        related: list[Agent],
    ) -> list[Text | Syntax]:
        """Build Rich renderables for each follow-up agent sub-section."""
        parts: list[Text | Syntax] = []
        for rel in related:
            # Divider + label
            label_text = Text()
            label_text.append("\n")
            label_text.append("─" * 50 + "\n", style="dim")
            label_text.append("\n")

            role = self._role_label(rel)
            status = self._status_label(rel)
            time_str = rel.start_time_short
            label_text.append(
                f"{role}  {status}  {time_str}\n",
                style="bold #87D7FF",
            )
            label_text.append("\n")

            # Content: prefer timestamped chunks, then live/response, else placeholder
            chunks = rel.get_timestamped_reply_chunks()
            if chunks:
                parts.append(label_text)
                for ts, chunk_text in chunks:
                    parts.append(self._render_timestamp_divider(ts))
                    content = chunk_text.strip()
                    if content:
                        parts.append(
                            Syntax(content, "markdown", theme="monokai", word_wrap=True)
                        )
            else:
                reply: str | None = None
                if rel.status in ("DONE", "FAILED"):
                    reply = rel.get_response_content()
                else:
                    reply = rel.get_live_reply_content()
                if reply:
                    parts.append(label_text)
                    parts.append(
                        Syntax(reply, "markdown", theme="monokai", word_wrap=True)
                    )
                else:
                    if rel.status in ("DONE", "FAILED"):
                        label_text.append(
                            "No response file found.\n", style="dim italic"
                        )
                    else:
                        label_text.append(
                            "Waiting for agent response...\n",
                            style="dim italic",
                        )
                    parts.append(label_text)
        return parts

    def _render_followup_hints(
        self,
        related: list[Agent],
        header_text: Text,
        hint_counter: int,
        hint_mappings: dict[int, str],
        workspace_dir: str | None,
    ) -> int:
        """Append follow-up agent content as plain text with file-path hints."""
        from ._file_path_hints import append_text_with_file_hints

        for rel in related:
            header_text.append("\n")
            header_text.append("─" * 50 + "\n", style="dim")
            header_text.append("\n")

            role = self._role_label(rel)
            status = self._status_label(rel)
            time_str = rel.start_time_short
            header_text.append(
                f"{role}  {status}  {time_str}\n",
                style="bold #87D7FF",
            )
            header_text.append("\n")

            chunks = rel.get_timestamped_reply_chunks()
            if chunks:
                for ts, chunk_text in chunks:
                    header_text.append_text(self._render_timestamp_divider(ts))
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
            else:
                reply: str | None = None
                if rel.status in ("DONE", "FAILED"):
                    reply = rel.get_response_content()
                else:
                    reply = rel.get_live_reply_content()
                if reply:
                    hint_counter = append_text_with_file_hints(
                        header_text,
                        reply + "\n",
                        hint_counter,
                        hint_mappings,
                        workspace_dir,
                    )
                else:
                    if rel.status in ("DONE", "FAILED"):
                        header_text.append(
                            "No response file found.\n", style="dim italic"
                        )
                    else:
                        header_text.append(
                            "Waiting for agent response...\n",
                            style="dim italic",
                        )
        return hint_counter

    def show_empty(self) -> None:
        """Show empty state."""
        text = Text("No agent selected", style="dim italic")
        self.update(text)  # type: ignore[attr-defined]

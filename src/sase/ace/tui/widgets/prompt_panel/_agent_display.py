"""Agent display mixin for the agent prompt panel."""

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

        header_text = Text()

        # Header - AGENT DETAILS
        header_text.append("AGENT DETAILS\n", style="bold #D7AF5F underline")
        header_text.append("\n")

        # Extract meta_* overrides from step_output
        meta_project = None
        meta_changespec = None
        meta_workspace = None
        if agent.step_output and isinstance(agent.step_output, dict):
            meta_project = agent.step_output.get("meta_project")
            meta_changespec = agent.step_output.get("meta_changespec")
            meta_workspace = agent.step_output.get("meta_workspace")

        # For workflow step agents, show "Step" instead of "ChangeSpec"
        if agent.is_workflow_child and agent.step_name:
            header_text.append("Step: ", style="bold #87D7FF")
            header_text.append(f"{agent.step_name}\n", style="#00D7AF")
        elif meta_project:
            header_text.append("Project: ", style="bold #87D7FF")
            header_text.append(f"{meta_project}\n", style="#00D7AF")
        elif meta_changespec:
            header_text.append("ChangeSpec: ", style="bold #87D7FF")
            header_text.append(f"{meta_changespec}", style="#00D7AF")
            if agent.cl_num:
                header_text.append(" (")
                header_text.append(agent.cl_num, style="bold underline #569CD6")
                header_text.append(")")
            header_text.append("\n")
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

        # Workspace (if available) - check meta_workspace first, then agent field
        workspace_num = meta_workspace or agent.workspace_num
        if workspace_num is not None:
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

        # Waiting info (when agent is waiting for dependencies)
        if agent.waiting_for:
            header_text.append("Waiting for: ", style="bold #87D7FF")
            header_text.append(f"{', '.join(agent.waiting_for)}\n", style="#FF87D7")

        # Timestamp (when agent started)
        header_text.append("Timestamp: ", style="bold #87D7FF")
        header_text.append(f"{agent.start_time_display}\n", style="#D7D7FF")

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

        # Separator
        header_text.append("\n")
        header_text.append("─" * 50 + "\n", style="dim")
        header_text.append("\n")

        # Check if this is a bash/python workflow step - display differently
        if agent.is_workflow_child and agent.step_type in ("bash", "python"):
            self._update_bash_python_display(agent, header_text)
            return

        # Check if this is a parallel workflow step - show output only, no prompt
        if agent.is_workflow_child and agent.step_type == "parallel":
            self._update_parallel_display(agent, header_text)
            return

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
                if (
                    response_content is None
                    and agent.is_workflow_child
                    and agent.step_output
                ):
                    response_content = format_output(agent.step_output)

                renderables: list[Text | Syntax] = [header_text, prompt_syntax]

                if response_content:
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

                # Show traceback section for failed agents
                if agent.error_traceback:
                    tb_header = Text()
                    tb_header.append("\n")
                    tb_header.append("─" * 50 + "\n", style="dim")
                    tb_header.append("\n")
                    tb_header.append("TRACEBACK\n", style="bold #D7AF5F underline")
                    tb_header.append("\n")
                    tb_syntax = Syntax(
                        agent.error_traceback,
                        "pytb",
                        theme="monokai",
                        word_wrap=True,
                    )
                    renderables.extend([tb_header, tb_syntax])

                self.update(Group(*renderables))  # type: ignore[attr-defined]
            else:
                self.update(Group(header_text, prompt_syntax))  # type: ignore[attr-defined]
        else:
            header_text.append("No prompt file found.\n", style="dim italic")
            self.update(header_text)  # type: ignore[attr-defined]

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

    def _update_bash_python_display(self, agent: Agent, header_text: Text) -> None:
        """Display bash command or python code with output.

        Args:
            agent: The workflow step agent to display.
            header_text: The Text object with header content to append to.
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

        if agent.step_output:
            output_str = format_output(agent.step_output)
            output_syntax = Syntax(output_str, "json", theme="monokai", word_wrap=True)
            self.update(  # type: ignore[attr-defined]
                Group(header_text, source_content, output_header, output_syntax)
            )
        else:
            output_header.append("No output available.\n", style="dim italic")
            self.update(Group(header_text, source_content, output_header))  # type: ignore[attr-defined]

    def _update_parallel_display(self, agent: Agent, header_text: Text) -> None:
        """Display output for a parallel workflow step (no prompt section).

        Args:
            agent: The workflow step agent to display.
            header_text: The Text object with header content to append to.
        """
        header_text.append("STEP OUTPUT\n", style="bold #D7AF5F underline")
        header_text.append("\n")

        if agent.step_output:
            output_str = format_output(agent.step_output)
            output_syntax = Syntax(output_str, "json", theme="monokai", word_wrap=True)
            self.update(Group(header_text, output_syntax))  # type: ignore[attr-defined]
        else:
            header_text.append("No output available.\n", style="dim italic")
            self.update(header_text)  # type: ignore[attr-defined]

    def show_empty(self) -> None:
        """Show empty state."""
        text = Text("No agent selected", style="dim italic")
        self.update(text)  # type: ignore[attr-defined]

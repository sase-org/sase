"""Prompt input bar management and event handlers for agent workflow."""

from __future__ import annotations

import os

from sase.ace.tui.widgets.prompt_text_area import PromptTextArea

from ._types import PromptContext


class PromptBarMixin:
    """Mixin providing prompt input bar management and event handlers."""

    # State for prompt input
    _prompt_context: PromptContext | None = None

    def _show_prompt_input_bar(
        self,
        project_name: str | None,
        cl_name: str | None,
        update_target: str,
        history_sort_key: str,
    ) -> None:
        """Show prompt input bar for agent workflow.

        Args:
            project_name: The project name.
            cl_name: The selected CL name (or None for project-only).
            update_target: What to checkout (CL name or "p4head").
            history_sort_key: Branch/CL name to sort prompt history by.
        """
        from sase.workflows.commit.project_file_utils import create_project_file
        from sase.sase_utils import generate_timestamp
        from sase.running_field import (
            get_first_available_axe_workspace,
            get_workspace_directory_for_num,
        )

        from ...widgets import PromptInputBar

        if project_name is None:
            self.notify("No project selected", severity="error")  # type: ignore[attr-defined]
            return

        project_file = os.path.expanduser(
            f"~/.sase/projects/{project_name}/{project_name}.gp"
        )

        # Create project file if it doesn't exist
        if not os.path.isfile(project_file):
            if not create_project_file(project_name):
                self.notify(  # type: ignore[attr-defined]
                    f"Failed to create project file: {project_file}",
                    severity="error",
                )
                return

        timestamp = generate_timestamp()
        workflow_name = f"ace(run)-{timestamp}"
        display_name = cl_name or project_name

        # For bulk runs, skip workspace resolution here;
        # _launch_bulk_agents() resolves workspaces per-changespec.
        if self._bulk_changespecs:  # type: ignore[attr-defined]
            workspace_num = 0
            workspace_dir = ""
        else:
            workspace_num = get_first_available_axe_workspace(project_file)
            try:
                workspace_dir, _ = get_workspace_directory_for_num(
                    workspace_num, project_name
                )
            except RuntimeError as e:
                self.notify(f"Failed to get workspace: {e}", severity="error")  # type: ignore[attr-defined]
                return

        # Store context for when prompt is submitted
        self._prompt_context = PromptContext(
            project_name=project_name,
            cl_name=cl_name,
            project_file=project_file,
            workspace_dir=workspace_dir,
            workspace_num=workspace_num,
            workflow_name=workflow_name,
            timestamp=timestamp,
            history_sort_key=history_sort_key,
            display_name=display_name,
            update_target=update_target,
        )

        # Remove any existing prompt bar before mounting a new one
        self._unmount_prompt_bar()
        # Immediately show prompt input bar (workspace prep happens in runner)
        self.mount(PromptInputBar(id="prompt-input-bar"))  # type: ignore[attr-defined]

    def _unmount_prompt_bar(self) -> None:
        """Unmount the prompt input bar if present."""
        from ...widgets import PromptInputBar

        try:
            bar = self.query_one("#prompt-input-bar", PromptInputBar)  # type: ignore[attr-defined]
        except Exception:
            return  # Bar not present
        # Synchronously detach from parent's node list so the ID is freed
        # immediately. Without this, bar.remove() only schedules async
        # removal and a subsequent mount() would hit DuplicateIds.
        parent = bar._parent
        if parent is not None:
            parent._nodes._remove(bar)
        bar.remove()

    def _setup_home_prompt_context(
        self,
        display_name: str = "~",
        history_sort_key: str = "home",
    ) -> None:
        """Set up prompt context for home directory mode without showing UI.

        Args:
            display_name: Display name shown in the prompt context.
            history_sort_key: Key used to sort/filter prompt history.
        """
        from pathlib import Path

        from sase.sase_utils import generate_timestamp

        timestamp = generate_timestamp()
        workflow_name = f"ace(run)-{timestamp}"

        self._prompt_context = PromptContext(
            project_name="home",
            cl_name=None,
            project_file=os.path.expanduser("~/.sase/projects/home/home.gp"),
            workspace_dir=str(Path.home()),
            workspace_num=0,
            workflow_name=workflow_name,
            timestamp=timestamp,
            history_sort_key=history_sort_key,
            display_name=display_name,
            update_target="",
            is_home_mode=True,
        )

    def _show_prompt_input_bar_for_home(
        self,
        initial_text: str = "",
        display_name: str = "~",
        history_sort_key: str = "home",
    ) -> None:
        """Show prompt input bar for home directory mode.

        This skips CL name and bug modals, running the agent from the user's
        home directory without version control or workspace management.

        Args:
            initial_text: Pre-populated text for the prompt input bar.
            display_name: Display name shown in the prompt context.
            history_sort_key: Key used to sort/filter prompt history.
        """
        from ...widgets import PromptInputBar

        self._setup_home_prompt_context(
            display_name=display_name,
            history_sort_key=history_sort_key,
        )

        # Remove any existing prompt bar before mounting a new one
        self._unmount_prompt_bar()
        # Show prompt input bar
        self.mount(PromptInputBar(initial_value=initial_text, id="prompt-input-bar"))  # type: ignore[attr-defined]

    def _select_and_open_editor_for_home(
        self,
        initial_text: str = "",
        display_name: str = "~",
        history_sort_key: str = "home",
    ) -> None:
        """Set up home-mode prompt context and open editor directly.

        Combines ``_show_prompt_input_bar_for_home`` + ``ctrl+g`` into a
        single step so the user never sees the prompt input bar.

        Args:
            initial_text: Pre-populated text for the editor.
            display_name: Display name shown in the prompt context.
            history_sort_key: Key used to sort/filter prompt history.
        """
        self._setup_home_prompt_context(
            display_name=display_name,
            history_sort_key=history_sort_key,
        )

        prompt = self._open_editor_for_agent_prompt(initial_text)  # type: ignore[attr-defined]
        if prompt:
            self._finish_agent_launch(prompt)  # type: ignore[attr-defined]
        else:
            self.notify("No prompt from editor - cancelled", severity="warning")  # type: ignore[attr-defined]
            self._prompt_context = None

    def on_prompt_input_bar_submitted(self, event: object) -> None:
        """Handle prompt submission from the input bar."""
        from ...widgets import PromptInputBar

        if not isinstance(event, PromptInputBar.Submitted):
            return

        prompt = event.value
        if not prompt:
            self.notify("Empty prompt - cancelled", severity="warning")  # type: ignore[attr-defined]
            self._unmount_prompt_bar()
            self._prompt_context = None
            return

        self._finish_agent_launch(prompt)  # type: ignore[attr-defined]

    def on_prompt_input_bar_cancelled(self, event: object) -> None:
        """Handle cancellation from the input bar."""
        from ...widgets import PromptInputBar

        if not isinstance(event, PromptInputBar.Cancelled):
            return

        # Save cancelled prompt to history so it can be recovered via "@ " filter
        if event.cancelled_text and self._prompt_context:
            from sase.history.prompt import add_or_update_prompt

            add_or_update_prompt(
                event.cancelled_text,
                project_name=self._prompt_context.project_name,
                branch_or_workspace=self._prompt_context.history_sort_key,
                cancelled=True,
            )

        self.notify("Prompt input cancelled")  # type: ignore[attr-defined]
        self._unmount_prompt_bar()
        self._prompt_context = None

    def on_prompt_input_bar_editor_requested(self, event: object) -> None:
        """Handle request to open external editor (Ctrl+G)."""
        from ...widgets import PromptInputBar

        if not isinstance(event, PromptInputBar.EditorRequested):
            return

        if self._prompt_context is None:
            return

        # Suspend TUI and open editor with current text
        prompt = self._open_editor_for_agent_prompt(  # type: ignore[attr-defined]
            event.current_text,
            cursor_row=event.cursor_row,
            cursor_col=event.cursor_col,
        )
        if prompt:
            self._finish_agent_launch(prompt)  # type: ignore[attr-defined]
        else:
            self.notify("No prompt from editor - cancelled", severity="warning")  # type: ignore[attr-defined]
            self._unmount_prompt_bar()
            self._prompt_context = None

    def on_prompt_input_bar_history_requested(self, event: object) -> None:
        """Handle request to show prompt history picker ('.')."""
        from ...widgets import PromptInputBar

        if not isinstance(event, PromptInputBar.HistoryRequested):
            return

        if self._prompt_context is None:
            return

        from ...modals import (
            PromptHistoryAction,
            PromptHistoryModal,
            PromptHistoryResult,
        )

        vcs_prefix = event.vcs_prefix

        def _build_prompt(prompt_text: str) -> str:
            """Replace embedded VCS workflow tags with the current VCS prefix.

            Finds all VCS workflow tags in the prompt (including in
            multi-prompt segments and after ``%directive`` tokens) and
            replaces each with *vcs_prefix*.  This handles cross-VCS
            reuse and avoids tag doubling.
            """
            if vcs_prefix:
                from sase.xprompt import replace_vcs_workflow_tags

                return replace_vcs_workflow_tags(prompt_text, vcs_prefix)
            return prompt_text

        def on_history_select(result: PromptHistoryResult | None) -> None:
            if result is None:
                self.notify("No prompt from history - cancelled", severity="warning")  # type: ignore[attr-defined]
                self._unmount_prompt_bar()
                self._prompt_context = None
                return

            if result.action == PromptHistoryAction.SUBMIT:
                # Direct submit - skip editor
                self._finish_agent_launch(_build_prompt(result.prompt_text))  # type: ignore[attr-defined]
            elif result.action == PromptHistoryAction.LOAD:
                # Load into prompt input widget for inline editing
                from ...widgets import PromptInputBar

                try:
                    bar = self.query_one("#prompt-input-bar", PromptInputBar)  # type: ignore[attr-defined]
                    text_area = bar.query_one("#prompt-input", PromptTextArea)
                    text_area.load_text(_build_prompt(result.prompt_text))
                    text_area.focus()
                except Exception:
                    pass
            else:
                # Edit first - open editor with selected prompt
                prompt_for_editor = _build_prompt(result.prompt_text)
                edited_prompt = self._open_editor_for_agent_prompt(prompt_for_editor)  # type: ignore[attr-defined]
                if edited_prompt:
                    self._finish_agent_launch(edited_prompt)  # type: ignore[attr-defined]
                else:
                    self.notify("No prompt from editor - cancelled", severity="warning")  # type: ignore[attr-defined]
                    self._unmount_prompt_bar()
                    self._prompt_context = None

        self.push_screen(  # type: ignore[attr-defined]
            PromptHistoryModal(
                sort_by=self._prompt_context.history_sort_key,
                workspace=self._prompt_context.project_name,
                show_cancelled=event.show_cancelled,
            ),
            on_history_select,
        )

    def on_prompt_input_bar_snippet_requested(self, event: object) -> None:
        """Handle request to show snippet modal ('#@')."""
        from ...widgets import PromptInputBar

        if not isinstance(event, PromptInputBar.SnippetRequested):
            return

        from ...modals import XPromptSelectModal

        def on_xprompt_select(result: str | None) -> None:
            if result:
                # Insert xprompt name into the input bar
                try:
                    bar = self.query_one("#prompt-input-bar", PromptInputBar)  # type: ignore[attr-defined]
                    bar.insert_snippet(result)
                except Exception:
                    pass

        # Get project from prompt context if available.
        # In home mode, let auto-detection resolve the actual project name
        # from CWD rather than passing "home" as the project.
        ctx = self._prompt_context
        if ctx and not ctx.is_home_mode:
            project = ctx.project_name
        else:
            project = None
        self.push_screen(XPromptSelectModal(project=project), on_xprompt_select)  # type: ignore[attr-defined]

    def on_prompt_input_bar_workflow_editor_requested(self, event: object) -> None:
        """Handle request to open workflow YAML editor (Ctrl+Y)."""
        from ...widgets import PromptInputBar

        if not isinstance(event, PromptInputBar.WorkflowEditorRequested):
            return

        if self._prompt_context is None:
            return

        result = self._open_workflow_yaml_editor()  # type: ignore[attr-defined]
        if result:
            workflow_name, _file_path = result
            self._finish_agent_launch(f"#{workflow_name}")  # type: ignore[attr-defined]
        else:
            self.notify("No workflow from editor - cancelled", severity="warning")  # type: ignore[attr-defined]
            self._unmount_prompt_bar()
            self._prompt_context = None

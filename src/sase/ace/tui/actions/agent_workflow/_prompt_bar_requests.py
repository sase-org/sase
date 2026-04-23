"""Editor/history/snippet/workflow-editor request handlers for the prompt bar."""

from __future__ import annotations

from sase.ace.tui.widgets.prompt_text_area import PromptTextArea

from ._prompt_bar_mount import has_edit_directive
from ._types import PromptContext


class PromptBarRequestsMixin:
    """Handlers for editor, history, snippet, and workflow-editor requests."""

    _prompt_context: PromptContext | None

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
            has_edit, cleaned = has_edit_directive(prompt)
            if has_edit:
                self._load_prompt_into_bar(cleaned)  # type: ignore[attr-defined]
            else:
                self._finish_agent_launch(prompt)  # type: ignore[attr-defined]
        else:
            self.notify("No prompt from editor - cancelled", severity="warning")  # type: ignore[attr-defined]
            self._unmount_prompt_bar()  # type: ignore[attr-defined]
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
                self._unmount_prompt_bar()  # type: ignore[attr-defined]
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
                    has_edit, cleaned = has_edit_directive(edited_prompt)
                    if has_edit:
                        self._load_prompt_into_bar(cleaned)  # type: ignore[attr-defined]
                    else:
                        self._finish_agent_launch(edited_prompt)  # type: ignore[attr-defined]
                else:
                    self.notify("No prompt from editor - cancelled", severity="warning")  # type: ignore[attr-defined]
                    self._unmount_prompt_bar()  # type: ignore[attr-defined]
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

        # Detect VCS tag in current prompt text to load that project's
        # local xprompts (e.g. #gh:sase → load sase's sase.yml xprompts).
        extra_prompts = None
        try:
            bar = self.query_one("#prompt-input-bar", PromptInputBar)  # type: ignore[attr-defined]
            prompt_text = bar.query_one("#prompt-input", PromptTextArea).text
            if prompt_text:
                from sase.xprompt._parsing import (
                    extract_project_from_vcs_tag,
                    extract_vcs_workflow_tag,
                )
                from sase.xprompt.loader import (
                    get_known_project_workspaces,
                    load_project_local_xprompts,
                )
                from sase.xprompt.models import xprompt_to_workflow

                vcs_tag = extract_vcs_workflow_tag(prompt_text)
                if vcs_tag:
                    vcs_project = extract_project_from_vcs_tag(vcs_tag)
                    if vcs_project:
                        workspaces = get_known_project_workspaces()
                        ws_dir = workspaces.get(vcs_project)
                        if ws_dir:
                            xprompts = load_project_local_xprompts(ws_dir, vcs_project)
                            if xprompts:
                                extra_prompts = {
                                    name: xprompt_to_workflow(xp)
                                    for name, xp in xprompts.items()
                                }
        except Exception:
            pass

        self.push_screen(  # type: ignore[attr-defined]
            XPromptSelectModal(project=project, extra_prompts=extra_prompts),
            on_xprompt_select,
        )

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
            self._unmount_prompt_bar()  # type: ignore[attr-defined]
            self._prompt_context = None

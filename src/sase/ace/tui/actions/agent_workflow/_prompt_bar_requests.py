"""Editor/history/snippet/workflow-editor request handlers for the prompt bar."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ._prompt_bar_mount import has_edit_directive
from ._types import PromptContext

if TYPE_CHECKING:
    from sase.ace.tui.widgets import PromptInputBar


class PromptBarRequestsMixin:
    """Handlers for editor, history, snippet, and workflow-editor requests."""

    _prompt_context: PromptContext | None

    def on_prompt_input_bar_editor_requested(self, event: object) -> None:
        """Handle the single-pane editor request (``Ctrl+G`` on a solo bar).

        A multi-pane stack reaches the editor via :meth:`AllEditorRequested`
        instead, so this normally fires only for a single-pane bar.  The stacked
        branch below stays as defensive coverage for any programmatic caller that
        posts :class:`EditorRequested` while the bar holds multiple panes: the
        editor result is loaded back into the active pane without launching or
        disturbing the rest of the stack.
        """
        from ...widgets import PromptInputBar

        if not isinstance(event, PromptInputBar.EditorRequested):
            return

        if self._prompt_context is None:
            return

        # Capture the stacked state before suspending the TUI for the editor.
        stacked_bar = self._stacked_prompt_bar()

        # Suspend TUI and open editor with current text
        prompt = self._open_editor_for_agent_prompt(  # type: ignore[attr-defined]
            event.current_text,
            cursor_row=event.cursor_row,
            cursor_col=event.cursor_col,
        )
        if prompt:
            has_edit, cleaned = has_edit_directive(prompt)
            if stacked_bar is not None:
                stacked_bar.update_active_pane(cleaned if has_edit else prompt)
            elif has_edit:
                self._load_editor_markdown_into_bar(cleaned)  # type: ignore[attr-defined]
            else:
                self._finish_agent_launch(prompt)  # type: ignore[attr-defined]
        elif stacked_bar is not None:
            # An empty editor return on a multi-pane stack is a no-op edit: keep
            # the stack mounted and just refocus the pane being edited.
            try:
                stacked_bar.active_text_area().focus()
            except Exception:
                pass
        else:
            self.notify("No prompt from editor - cancelled", severity="warning")  # type: ignore[attr-defined]
            self._unmount_prompt_bar()  # type: ignore[attr-defined]
            self._prompt_context = None

    def on_prompt_input_bar_all_editor_requested(self, event: object) -> None:
        """Handle the whole-stack editor request (``Ctrl+G`` on a multi-pane bar)."""
        from ...widgets import PromptInputBar

        if not isinstance(event, PromptInputBar.AllEditorRequested):
            return

        if self._prompt_context is None:
            return

        try:
            bar = self.query_one("#prompt-input-bar", PromptInputBar)  # type: ignore[attr-defined]
        except Exception:
            return

        # The bar owns serializing its live panes + frontmatter to xprompt
        # markdown; capture it before suspending the TUI for the editor.
        markdown = bar.xprompt_markdown_for_editor()
        prompt = self._open_editor_for_agent_prompt(markdown)  # type: ignore[attr-defined]

        if prompt:
            # Strip a ``%edit`` directive for parity with the other editor-return
            # paths, then reload the whole bar from the edited markdown. The
            # all-stack editor never launches — it only re-stacks the bar.
            has_edit, cleaned = has_edit_directive(prompt)
            bar.load_stack_from_xprompt_markdown(cleaned if has_edit else prompt)
        else:
            # Empty editor return is a no-op edit: keep the bar mounted and
            # refocus the active pane, matching the stacked ``^G`` behavior.
            try:
                bar.active_text_area().focus()
            except Exception:
                pass

    def _stacked_prompt_bar(self) -> PromptInputBar | None:
        """Return the mounted prompt bar when it holds more than one pane.

        Used by the editor-return path to decide whether ``^G`` edits a single
        pane of a stack (keep the bar, update that pane) versus the legacy
        single-pane behavior (load/launch the whole bar).
        """
        from ...widgets import PromptInputBar

        try:
            bar = self.query_one("#prompt-input-bar", PromptInputBar)  # type: ignore[attr-defined]
        except Exception:
            return None
        return bar if bar.is_stacked() else None

    def on_prompt_input_bar_history_requested(self, event: object) -> None:
        """Handle request to show prompt history picker."""
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
                if event.preserve_prompt_bar:
                    try:
                        bar = self.query_one("#prompt-input-bar", PromptInputBar)  # type: ignore[attr-defined]
                        bar.active_text_area().focus()
                    except Exception:
                        pass
                    return
                self.notify("No prompt from history - cancelled", severity="warning")  # type: ignore[attr-defined]
                self._unmount_prompt_bar()  # type: ignore[attr-defined]
                self._prompt_context = None
                return

            if result.action == PromptHistoryAction.SUBMIT:
                # Direct submit - skip editor
                self._finish_agent_launch(_build_prompt(result.prompt_text))  # type: ignore[attr-defined]
            elif result.action == PromptHistoryAction.LOAD:
                # Load into the prompt bar for inline editing.  A multi-prompt
                # history entry renders as stacked panes; a single entry stays
                # one pane (canonical split decides).
                try:
                    bar = self.query_one("#prompt-input-bar", PromptInputBar)  # type: ignore[attr-defined]
                    bar.load_stack_from_text(_build_prompt(result.prompt_text))
                except Exception:
                    pass
            else:
                # Edit first - open editor with selected prompt
                prompt_for_editor = _build_prompt(result.prompt_text)
                edited_prompt = self._open_editor_for_agent_prompt(prompt_for_editor)  # type: ignore[attr-defined]
                if edited_prompt:
                    has_edit, cleaned = has_edit_directive(edited_prompt)
                    if has_edit:
                        self._load_editor_markdown_into_bar(cleaned)  # type: ignore[attr-defined]
                    else:
                        self._finish_agent_launch(edited_prompt)  # type: ignore[attr-defined]
                else:
                    self.notify("No prompt from editor - cancelled", severity="warning")  # type: ignore[attr-defined]
                    self._unmount_prompt_bar()  # type: ignore[attr-defined]
                    self._prompt_context = None

        self.push_screen(  # type: ignore[attr-defined]
            PromptHistoryModal(
                show_cancelled=event.show_cancelled,
                initial_filter=event.initial_filter,
            ),
            on_history_select,
        )

    def on_prompt_input_bar_snippet_requested(self, event: object) -> None:
        """Handle request to show snippet modal ('#@')."""
        from ...widgets import PromptInputBar

        if not isinstance(event, PromptInputBar.SnippetRequested):
            return

        from ...modals import XPromptSelectModal
        from ...modals.xprompt_select_modal import XPromptSelection

        def on_xprompt_select(result: XPromptSelection | str | None) -> None:
            if result:
                # Insert xprompt name into the input bar
                try:
                    bar = self.query_one("#prompt-input-bar", PromptInputBar)  # type: ignore[attr-defined]
                    if isinstance(result, XPromptSelection):
                        bar.insert_snippet(result.suffix, result.entry)
                    else:
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
            prompt_text = bar.active_text()
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

"""Editor/history/snippet/workflow-editor request handlers for the prompt bar."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ._prompt_bar_mount import strip_editor_review_markers
from ._types import PromptContext

if TYPE_CHECKING:
    from sase.ace.tui.widgets import PromptInputBar
    from sase.xprompt.models import XPrompt
    from sase.xprompt.workflow_models import Workflow

log = logging.getLogger(__name__)


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
            marked, cleaned = strip_editor_review_markers(prompt)
            if stacked_bar is not None:
                stacked_bar.update_active_pane(cleaned if marked else prompt)
            elif marked:
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
            # Strip ` @` review markers for parity with the other editor-return
            # paths, then reload the whole bar from the edited markdown. The
            # all-stack editor never launches — it only re-stacks the bar.
            marked, cleaned = strip_editor_review_markers(prompt)
            bar.load_stack_from_xprompt_markdown(cleaned if marked else prompt)
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
                # Load inline into the pane the modal was opened from, preserving
                # every other pane's draft. A multi-agent entry grows the stack
                # with new panes below the origin; a single entry replaces just
                # that pane. A frontmatter clash prompts before overwriting the
                # staged xprompt properties (see :meth:`_load_history_selection`).
                self._load_history_selection(event, _build_prompt(result.prompt_text))
            else:
                # Edit first - open editor with selected prompt
                prompt_for_editor = _build_prompt(result.prompt_text)
                edited_prompt = self._open_editor_for_agent_prompt(prompt_for_editor)  # type: ignore[attr-defined]
                if edited_prompt:
                    marked, cleaned = strip_editor_review_markers(edited_prompt)
                    if marked:
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

    def _load_history_selection(self, event: object, built: str) -> None:
        """Load a selected history entry inline into its origin pane.

        *built* is the VCS-substituted entry text. The load targets the exact
        pane the history modal was opened from (``event`` carries its captured
        origin), so every other pane keeps its draft; a stale origin discards
        the selection with a warning instead of touching any prompt. When the
        entry carries xprompt frontmatter that would overwrite properties
        already staged on the stack, a y/n confirmation is shown first --
        declining aborts the load and refocuses the origin pane, leaving the bar
        and its panes untouched.
        """
        from sase.ace.tui.widgets.prompt_stack import split_frontmatter

        from ...widgets import PromptInputBar

        origin_bar = getattr(event, "origin_bar", None)
        if isinstance(origin_bar, PromptInputBar) and origin_bar.is_mounted:
            bar = origin_bar
            target_text_area = getattr(event, "origin_text_area", None)
            pane_id = getattr(event, "origin_pane_id", "")
        else:
            # Defensive fallback for a programmatic caller that carried no live
            # origin: target the mounted bar's active pane (an empty pane_id
            # lets ``_resolve_pane_target`` fall back to that text area).
            try:
                bar = self.query_one("#prompt-input-bar", PromptInputBar)  # type: ignore[attr-defined]
            except Exception:
                return
            target_text_area = bar.active_text_area()
            pane_id = ""

        def _apply() -> None:
            if not bar.load_prompt_into_pane(target_text_area, pane_id, built):
                # Stale origin pane: leave every prompt unchanged (never unmount
                # the bar) and surface the same UX as the ``#@`` selector.
                self.notify(  # type: ignore[attr-defined]
                    "Prompt pane is no longer available - selection discarded",
                    severity="warning",
                )

        incoming_fm, _ = split_frontmatter(built)
        conflict = (
            bool(incoming_fm)
            and bar.has_frontmatter_properties()
            and incoming_fm != bar.current_frontmatter()
        )
        if not conflict:
            _apply()
            return

        from ...modals import ConfirmActionModal, ConfirmKind

        def _on_confirm(confirmed: bool | None) -> None:
            if confirmed:
                _apply()
                return
            # Declined: abort the load entirely -- nothing changes -- and return
            # focus to the origin pane (same refocus pattern the cancel branch
            # uses, but pinned to the captured origin).
            try:
                if target_text_area is not None and getattr(
                    target_text_area, "is_mounted", False
                ):
                    target_text_area.focus()
                else:
                    bar.active_text_area().focus()
            except Exception:
                pass

        self.push_screen(  # type: ignore[attr-defined]
            ConfirmActionModal(
                "Replace xprompt properties?",
                "Loading this prompt will replace your current xprompt properties.",
                kind=ConfirmKind.DANGER,
            ),
            _on_confirm,
        )

    def on_prompt_input_bar_snippet_requested(self, event: object) -> None:
        """Handle request to show snippet modal ('#@')."""
        from ...widgets import PromptInputBar

        if not isinstance(event, PromptInputBar.SnippetRequested):
            return

        from ...modals import XPromptSelectModal
        from ...modals.xprompt_select_modal import XPromptSelection

        # The trigger pane captured its own origin (Phase 1), so target it
        # directly instead of re-querying the generic ``#prompt-input-bar`` after
        # the modal closes — that lookup could land on a different active pane in
        # a multi-pane stack.
        origin_bar = (
            event.origin_bar if isinstance(event.origin_bar, PromptInputBar) else None
        )
        origin_text_area = event.origin_text_area
        origin_pane_id = event.origin_pane_id
        trigger_range = event.trigger_range

        def on_xprompt_select(result: XPromptSelection | str | None) -> None:
            if not result or origin_bar is None:
                return
            suffix = result.suffix if isinstance(result, XPromptSelection) else result
            entry = result.entry if isinstance(result, XPromptSelection) else None
            inserted = origin_bar.insert_snippet_at_target(
                origin_text_area,
                origin_pane_id,
                trigger_range,
                suffix,
                entry,
            )
            if not inserted:
                # Target-staleness guard: the originating pane/bar was unmounted
                # before the user chose, so leave every prompt unchanged.
                self.notify(  # type: ignore[attr-defined]
                    "Prompt pane is no longer available - selection discarded",
                    severity="warning",
                )

        # Get project from prompt context if available.
        # In home mode, let auto-detection resolve the actual project name
        # from CWD rather than passing "home" as the project.
        ctx = self._prompt_context
        if ctx and not ctx.is_home_mode:
            project = ctx.project_name
        else:
            project = None

        # Phase 5: build the selector's extra catalog entries from two local
        # sources, merged lowest-priority-first so the more specific source wins
        # a name collision:
        #   1. project-local xprompts from the leading VCS tag, then
        #   2. live frontmatter ``xprompts:`` the user authored on this prompt.
        # The frontmatter locals are also kept as real ``XPrompt`` objects
        # (``local_xprompts``) so the ``Ctrl+I`` expansion helper can resolve a
        # selected local helper -- or a global xprompt that references one --
        # the same way the launch path would.
        from sase.xprompt.models import xprompt_to_workflow

        extra_prompts: dict[str, Workflow] = {}
        local_xprompts: dict[str, XPrompt] = {}

        # 1. Project-local xprompts from a VCS tag in the originating pane's
        #    text (e.g. #gh:sase → load sase's sase.yml xprompts). Read from the
        #    captured origin pane so detection follows the pane that opened #@.
        try:
            prompt_text = ""
            if origin_text_area is not None:
                prompt_text = getattr(origin_text_area, "text", "") or ""
            elif origin_bar is not None:
                prompt_text = origin_bar.active_text()
            if prompt_text:
                from sase.xprompt._parsing import (
                    extract_project_from_vcs_tag,
                    extract_vcs_workflow_tag,
                )
                from sase.xprompt.loader import load_project_local_xprompts
                from sase.xprompt.project_identity import (
                    canonical_xprompt_project,
                    known_project_namespaces,
                )

                vcs_tag = extract_vcs_workflow_tag(prompt_text)
                if vcs_tag:
                    # The tag names the project however the user spelled it, so
                    # canonicalize before the namespace lookup: the namespace map
                    # is keyed by the user-facing ``PROJECT_NAME``, which differs
                    # from the ProjectSpec directory key for ``#gh:`` projects.
                    vcs_project = canonical_xprompt_project(
                        extract_project_from_vcs_tag(vcs_tag)
                    )
                    if vcs_project:
                        ws_dir = known_project_namespaces().get(vcs_project)
                        if ws_dir:
                            xprompts = load_project_local_xprompts(ws_dir, vcs_project)
                            for name, xp in xprompts.items():
                                extra_prompts[name] = xprompt_to_workflow(xp)
        except Exception:
            # The selector still opens without project-local entries, but a
            # silent swallow here is indistinguishable from "the project has no
            # xprompts" -- which is exactly how this path has failed before.
            log.exception("Failed to load project-local xprompts for the selector")

        # 2. Live frontmatter locals authored on this prompt. These take
        #    precedence over project-local entries and feed the expansion
        #    helper. An invalid / mid-edit block yields ``{}`` (locals omitted)
        #    rather than crashing the selector.
        if origin_bar is not None:
            try:
                local_xprompts = origin_bar.local_xprompts()
                for name, xp in local_xprompts.items():
                    extra_prompts[name] = xprompt_to_workflow(xp)
            except Exception:
                local_xprompts = {}

        def on_xprompt_expand(name: str, workflow: object) -> str | None:
            """Inline-expand *name* into the originating pane (modal ``Ctrl+I``).

            Decides whether the selected entry can be rendered as plain text and
            returns ``None`` on success or a user-facing error message. The modal
            notifies and stays open on error, and dismisses on success.
            """
            from sase.ace.tui.widgets.xprompt_inline_expansion import (
                expand_inline_xprompt,
            )
            from sase.xprompt.workflow_models import Workflow

            if origin_bar is None or not origin_bar.is_mounted:
                return "Prompt pane is no longer available - selection discarded"
            if not isinstance(workflow, Workflow):
                return f"Could not inline-expand #{name}."

            # Pass the live frontmatter locals so a selected local helper (or a
            # global xprompt that references one) resolves recursively the same
            # way it would at launch (Phase 5 catalog parity).
            result = expand_inline_xprompt(
                name, workflow, local_xprompts=local_xprompts, project=project
            )
            if result.error is not None:
                return result.error
            # Apply the rendered body to the originating pane as one undoable
            # edit: it replaces the literal ``#`` trigger, so prompt NORMAL-mode
            # ``u`` restores the exact pre-expansion text. A stale target (the
            # pane was unmounted/rebuilt while the modal was open) leaves every
            # prompt untouched and surfaces a recoverable error.
            #
            # Capture the pane text before the splice so a successful expansion
            # that also stages inputs can register a transaction coupling those
            # auto-staged inputs to this body edit -- undoing the splice then
            # unstages them, and redo restages them (Phase: undo-staged-inputs).
            before_text = getattr(origin_text_area, "text", "") or ""
            applied = origin_bar.expand_xprompt_at_target(
                origin_text_area,
                origin_pane_id,
                trigger_range,
                result.expanded_text or "",
            )
            if not applied:
                return "Prompt pane is no longer available - selection discarded"
            if result.inputs:
                added = origin_bar.merge_frontmatter_inputs(result.inputs)
                origin_bar.register_inline_expansion(
                    origin_text_area,
                    origin_pane_id,
                    before_text,
                    result.inputs,
                    added,
                )
            return None

        self.push_screen(  # type: ignore[attr-defined]
            XPromptSelectModal(
                project=project,
                extra_prompts=extra_prompts,
                expand_callback=on_xprompt_expand,
            ),
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

"""Prompt input bar widget for agent workflow in the ace TUI."""

from typing import Any

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.dom import NoScreen
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Static, TextArea

from sase.ace.tui.widgets.directive_completion import DirectiveCompletionMetadata
from sase.ace.tui.widgets.file_completion import MAX_VISIBLE, CompletionCandidate
from sase.ace.tui.widgets.prompt_completion import PromptSoftCompletion
from sase.ace.tui.widgets.prompt_stack import (
    PromptStackItem,
    PromptStackState,
    split_prompt_text,
)
from sase.ace.tui.widgets.xprompt_arg_assist import (
    ActiveXPromptArgHint,
    XPromptAssistEntry,
    append_input_hints,
    detect_xprompt_arg_hint_at_cursor,
    xprompt_completion_suffix_skeleton,
)

from sase.ace.tui.widgets.prompt_text_area import PromptTextArea

# Inactive panes never grow past this many content rows so the active pane
# keeps the room.  Phase 2 height rule: active grows most, inactive compact.
_INACTIVE_PANE_MAX_ROWS = 4


class PromptInputBar(Static):
    """Prompt input bar for agent workflow, positioned at bottom of screen."""

    class Submitted(Message):
        """Message sent when prompt is submitted."""

        def __init__(self, value: str, mode: str = "prompt") -> None:
            super().__init__()
            self.value = value
            self.mode = mode

    class Cancelled(Message):
        """Message sent when input is cancelled."""

        def __init__(self, cancelled_text: str = "", mode: str = "prompt") -> None:
            super().__init__()
            self.cancelled_text = cancelled_text
            self.mode = mode

    class EditorRequested(Message):
        """Message sent when user requests external editor (Ctrl+G)."""

        def __init__(
            self,
            current_text: str = "",
            cursor_row: int = 0,
            cursor_col: int = 0,
        ) -> None:
            super().__init__()
            self.current_text = current_text
            self.cursor_row = cursor_row
            self.cursor_col = cursor_col

    class HistoryRequested(Message):
        """Message sent when user requests the prompt history picker."""

        def __init__(
            self,
            vcs_prefix: str = "",
            show_cancelled: bool = False,
            initial_filter: str = "",
            preserve_prompt_bar: bool = False,
        ) -> None:
            super().__init__()
            self.vcs_prefix = vcs_prefix
            self.show_cancelled = show_cancelled
            self.initial_filter = initial_filter
            self.preserve_prompt_bar = preserve_prompt_bar

    class SnippetRequested(Message):
        """Message sent when user requests snippet modal ('#@')."""

        pass

    class WorkflowEditorRequested(Message):
        """Message sent when user requests workflow YAML editor (Ctrl+Y)."""

        pass

    BINDINGS = []  # type: ignore[assignment]

    def __init__(
        self, initial_value: str = "", mode: str = "prompt", **kwargs: Any
    ) -> None:
        super().__init__(**kwargs)
        self._initial_value = initial_value
        self._mode = mode
        self._completion_visible = False
        self._completion_line_count = 0
        self._mode_subtitle = "[Enter] send  [Esc] normal  [^C] cancel"
        self._soft_completion_visible = False
        # Monotonic per-rebuild id namespace so a fresh stack mounted while the
        # previous panes are still being detached never collides on widget ids.
        self._generation = 0
        self._placeholder = ""
        self._stack = self._state_from_text(initial_value)

    @property
    def _base_title(self) -> str:
        """Return the base border title based on mode."""
        if self._mode == "feedback":
            return "Plan Feedback"
        if self._mode == "approve_prompt":
            return "Coder Prompt"
        return "Prompt"

    def compose(self) -> ComposeResult:
        """Compose the input bar: a shared completion panel + the prompt stack."""
        self._placeholder = self._compute_placeholder()
        yield Static("", id="prompt-completion", classes="hidden")
        with Vertical(id="prompt-stack"):
            yield from self._build_pane_widgets()

    def _compute_placeholder(self) -> str:
        """Return the empty-pane placeholder text for the current mode."""
        if self._mode == "feedback":
            return "Type plan feedback...  [^G] editor  [^J] newline"
        if self._mode == "approve_prompt":
            return "Type coder prompt...  [^G] editor  [^J] newline"
        return (
            "Type prompt  [^K] history  [^T] complete  [^R] find  "
            "[^G] editor  [^Y] workflow  [^J] newline"
        )

    def on_mount(self) -> None:
        """Focus the active pane on mount and position its cursor at end."""
        text_area = self.active_text_area()
        text_area.focus()
        self._cursor_to_end(text_area)

        # Border title and subtitle
        self.border_title = self._base_title
        self.set_prompt_mode_subtitle("[Enter] send  [Esc] normal  [^C] cancel")
        if self._mode in ("feedback", "approve_prompt"):
            self.add_class("feedback-mode")
        text_area._warm_current_xprompt_assist_entries()
        text_area._on_prompt_completion_context_changed()
        self._apply_active_classes()
        self._schedule_height_update()

    # -- stack model + rendering ---------------------------------------------

    def _state_from_text(self, text: str) -> PromptStackState:
        """Build stack state from *text*, splitting only real multi-prompts.

        Feedback / approve-prompt modes are never multi-agent surfaces, so they
        stay single-pane.  In prompt mode the canonical parser decides: text
        with real ``---`` separators (outside fences/frontmatter) splits into
        panes; anything else stays a single verbatim pane so single-prompt
        rendering — including leading YAML frontmatter — is unchanged.
        """
        if self._mode in ("feedback", "approve_prompt"):
            return PromptStackState.single(text)
        if len(split_prompt_text(text)) > 1:
            return PromptStackState.from_text(text)
        return PromptStackState.single(text)

    def _pane_id(self, item: PromptStackItem) -> str:
        """Stable, generation-scoped widget id for *item*'s text area."""
        return f"prompt-input-g{self._generation}-{item.item_id}"

    def _sep_id(self, item: PromptStackItem) -> str:
        """Stable, generation-scoped widget id for *item*'s separator row."""
        return f"prompt-sep-g{self._generation}-{item.item_id}"

    def _build_pane_widgets(self) -> list[Widget]:
        """Build the separator + text-area widgets for the current stack."""
        widgets: list[Widget] = []
        multi = len(self._stack) > 1
        for index, item in enumerate(self._stack.items):
            if multi:
                active = index == self._stack.selected_index
                state = "active" if active else "inactive"
                widgets.append(
                    Static(
                        f"agent {index + 1}",
                        id=self._sep_id(item),
                        classes=f"prompt-stack-separator {state}",
                    )
                )
            widgets.append(
                PromptTextArea(
                    item.text,
                    language="markdown",
                    soft_wrap=True,
                    show_line_numbers=item.text.count("\n") > 0,
                    highlight_cursor_line=False,
                    id=self._pane_id(item),
                    placeholder=self._placeholder,
                    classes=self._pane_classes(index, multi),
                )
            )
        return widgets

    def _pane_classes(self, index: int, multi: bool) -> str:
        """Return the CSS classes for the pane at *index*."""
        if not multi:
            return "prompt-input solo"
        state = "active" if index == self._stack.selected_index else "inactive"
        return f"prompt-input prompt-pane {state}"

    def _rebuild_stack(self) -> None:
        """Re-render the prompt stack to match ``self._stack`` from scratch.

        Used by deliberate whole-stack replacements (``load_stack_from_text``).
        Bumps the generation so freshly mounted panes never share ids with the
        panes still being detached asynchronously.
        """
        self._generation += 1
        try:
            container = self.query_one("#prompt-stack", Vertical)
        except Exception:
            return
        container.remove_children()
        container.mount(*self._build_pane_widgets())
        self.call_after_refresh(self._after_rebuild)

    def _after_rebuild(self) -> None:
        """Focus + style the active pane once a rebuilt stack has mounted."""
        try:
            text_area = self.active_text_area()
        except Exception:
            return
        text_area.focus()
        self._cursor_to_end(text_area)
        text_area._warm_current_xprompt_assist_entries()
        text_area._on_prompt_completion_context_changed()
        self._apply_active_classes()
        self._schedule_height_update()

    @staticmethod
    def _cursor_to_end(text_area: PromptTextArea) -> None:
        """Move *text_area*'s cursor to the end of its document."""
        if not text_area.text:
            return
        doc = text_area.document
        last_line = doc.line_count - 1
        text_area.cursor_location = (last_line, len(doc.get_line(last_line)))

    def _apply_active_classes(self) -> None:
        """Sync each pane/separator's active/inactive class with the selection."""
        multi = len(self._stack) > 1
        for index, item in enumerate(self._stack.items):
            active = index == self._stack.selected_index
            try:
                text_area = self.query_one(f"#{self._pane_id(item)}", PromptTextArea)
            except Exception:
                continue
            text_area.set_class(active, "active")
            text_area.set_class(not active, "inactive")
            if not multi:
                continue
            try:
                separator = self.query_one(f"#{self._sep_id(item)}", Static)
            except Exception:
                continue
            separator.set_class(active, "active")
            separator.set_class(not active, "inactive")

    # -- stack-aware public API ----------------------------------------------

    def active_text_area(self) -> PromptTextArea:
        """Return the ``PromptTextArea`` for the currently active pane."""
        item = self._stack.selected_item
        return self.query_one(f"#{self._pane_id(item)}", PromptTextArea)

    def active_text(self) -> str:
        """Return the active pane's text verbatim."""
        return self.active_text_area().text

    def all_prompt_texts(self) -> list[str]:
        """Return every pane's live text, top-to-bottom launch order."""
        self._sync_state_from_widgets()
        return list(self._stack.texts)

    def current_prompt_text(self) -> str:
        """Return the whole stack joined into one canonical multi-prompt string.

        Mirrors the whole-stack submit contract: empty panes are dropped and
        non-empty panes are joined with ``\\n---\\n`` (re-attaching frontmatter).
        For a single pane this is just that pane's stripped text, so existing
        single-prompt submit/cancel behavior is unchanged.
        """
        self._sync_state_from_widgets()
        return self._stack.join()

    def load_stack_from_text(self, text: str) -> None:
        """Replace the whole stack with panes parsed from *text*.

        Real ``---`` separators render as stacked panes; anything else loads as
        a single pane.  Used by deliberate whole-bar loads (editor return,
        history load) rather than active-pane edits.
        """
        self._stack = self._state_from_text(text)
        self._rebuild_stack()

    def focus_item(self, index: int) -> int:
        """Focus the pane at *index* (clamped); return the clamped index."""
        self._stack.focus(index)
        self._apply_active_classes()
        self.active_text_area().focus()
        self._schedule_height_update()
        return self._stack.selected_index

    def _sync_state_from_widgets(self) -> None:
        """Copy each mounted pane's live text back into the stack model."""
        for item in self._stack.items:
            try:
                text_area = self.query_one(f"#{self._pane_id(item)}", PromptTextArea)
            except Exception:
                continue
            item.text = text_area.text

    def on_descendant_focus(self, event: object) -> None:
        """Track the active pane when focus moves between panes."""
        widget = getattr(event, "widget", None)
        if widget is None or len(self._stack) <= 1:
            return
        for index, item in enumerate(self._stack.items):
            try:
                text_area = self.query_one(f"#{self._pane_id(item)}", PromptTextArea)
            except Exception:
                continue
            if text_area is widget and index != self._stack.selected_index:
                self._stack.selected_index = index
                self._apply_active_classes()
                self._schedule_height_update()
                return

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        """Update height and line numbers when text changes."""
        text_area = event.text_area
        if not isinstance(text_area, PromptTextArea):
            text_area = self.active_text_area()
        text_area.show_line_numbers = text_area.document.line_count > 1
        text_area._on_prompt_completion_context_changed()
        self._schedule_height_update()

    def on_text_area_selection_changed(self, event: TextArea.SelectionChanged) -> None:
        """Refresh soft completion when the prompt cursor moves."""
        if isinstance(event.text_area, PromptTextArea):
            event.text_area._on_prompt_completion_context_changed()

    @staticmethod
    def _text_area_visual_rows(text_area: PromptTextArea) -> int:
        """Count *text_area*'s rendered rows using Textual's wrapped document."""
        wrapped_document = getattr(text_area, "wrapped_document", None)
        wrapped_height = getattr(wrapped_document, "height", None)
        if isinstance(wrapped_height, int) and wrapped_height > 0:
            return wrapped_height
        return max(1, text_area.document.line_count)

    def _get_visual_line_count(self) -> int:
        """Count rendered text rows of the active pane."""
        try:
            text_area = self.active_text_area()
        except Exception:
            return 1
        return self._text_area_visual_rows(text_area)

    def _update_height(self) -> None:
        """Auto-grow the bar based on content, up to the full screen height."""
        if not self.is_mounted:
            return
        try:
            screen_height = self.screen.size.height
        except NoScreen:
            return
        max_height = screen_height - 2
        completion_rows = self._completion_line_count if self._completion_visible else 0
        if len(self._stack) <= 1:
            # Single pane: identical formula to the pre-stack bar. +2 for the
            # bar's top/bottom border, plus the completion panel when visible.
            visual_lines = self._get_visual_line_count()
            new_height = min(max(visual_lines + 2 + completion_rows, 3), max_height)
            self.styles.height = new_height
            return
        self._apply_multi_pane_heights(max_height, completion_rows)

    def _apply_multi_pane_heights(self, max_height: int, completion_rows: int) -> None:
        """Size each pane so the stack fits the screen, active pane growing most.

        Inactive panes compact to at most ``_INACTIVE_PANE_MAX_ROWS`` rows first;
        the active pane takes whatever budget remains.  If the panes still cannot
        fit, inactive panes shrink toward one row before the active pane does.
        """
        items = self._stack.items
        try:
            panes = [
                self.query_one(f"#{self._pane_id(item)}", PromptTextArea)
                for item in items
            ]
        except Exception:
            return
        count = len(panes)
        active = self._stack.selected_index
        # Reserve: bar border (2) + completion panel + one separator row/pane.
        reserve = 2 + completion_rows + count
        content_budget = max(count, max_height - reserve)

        desired = [max(1, self._text_area_visual_rows(pane)) for pane in panes]
        alloc = [
            1
            if index == active
            else max(1, min(desired[index], _INACTIVE_PANE_MAX_ROWS))
            for index in range(count)
        ]
        inactive_used = sum(alloc) - alloc[active]
        alloc[active] = max(1, min(desired[active], content_budget - inactive_used))

        overflow = sum(alloc) - content_budget
        if overflow > 0:
            for index in range(count):
                if overflow <= 0:
                    break
                if index == active:
                    continue
                take = min(alloc[index] - 1, overflow)
                alloc[index] -= take
                overflow -= take
            if overflow > 0:
                alloc[active] -= min(alloc[active] - 1, overflow)

        for pane, height in zip(panes, alloc, strict=True):
            pane.styles.height = height
        bar_height = min(reserve + sum(alloc), max_height)
        self.styles.height = max(bar_height, 3)

    def _schedule_height_update(self) -> None:
        """Update now and once more after Textual has refreshed wrapping."""
        self._update_height()
        self.call_after_refresh(self._update_height)

    def on_resize(self) -> None:
        """Recalculate height when the terminal is resized."""
        self._schedule_height_update()

    def show_file_completions(
        self,
        token: str,
        rows: list[CompletionCandidate],
        selected_index: int,
        scroll_offset: int = 0,
        completion_kind: str = "file",
    ) -> None:
        """Show the path/xprompt completion panel with Rich styling.

        Args:
            token: Current token being completed.
            rows: Completion entries.
            selected_index: Highlighted row index.
            scroll_offset: First visible entry index for scrolling.
            completion_kind: "file" for path completion, "xprompt" for xprompt.
        """
        panel = self.query_one("#prompt-completion", Static)
        total = len(rows)
        visible = rows[scroll_offset : scroll_offset + MAX_VISIBLE]

        is_xprompt = completion_kind == "xprompt"
        is_directive = completion_kind == "directive"
        is_history = completion_kind == "file_history"
        is_arg_completion = completion_kind in ("xprompt_arg_name", "xprompt_arg_value")
        content = Text()
        for i, candidate in enumerate(visible):
            actual_idx = scroll_offset + i
            is_selected = actual_idx == selected_index

            if is_selected:
                content.append("\u25b8 ", style="bold")
            else:
                content.append("  ")

            if is_xprompt:
                self._append_xprompt_completion_row(content, candidate, is_selected)
            elif is_directive:
                self._append_directive_completion_row(content, candidate, is_selected)
            elif is_arg_completion:
                content.append(
                    candidate.display,
                    style="bold yellow" if is_selected else "yellow",
                )
            elif candidate.is_dir:
                content.append("\U0001f4c1 ")
                content.append(
                    candidate.display, style="bold cyan" if is_selected else "cyan"
                )
            else:
                content.append("\U0001f4c4 ")
                content.append(candidate.display, style="bold" if is_selected else "")

            if i < len(visible) - 1:
                content.append("\n")

        remaining = total - (scroll_offset + len(visible))
        if remaining > 0:
            content.append(f"\n  \u2193 {remaining} more\u2026", style="dim")

        # Border title: "xprompts" for xprompt completion, "recent files"
        # for file-history completion, directory for file.
        if is_xprompt:
            panel.border_title = "xprompts"
        elif is_directive:
            panel.border_title = "directives"
        elif completion_kind == "xprompt_arg_name":
            panel.border_title = "xprompt arg names"
        elif completion_kind == "xprompt_arg_value":
            panel.border_title = "xprompt arg values"
        elif completion_kind == "xprompt_arg_path":
            panel.border_title = "xprompt path"
        elif is_history:
            panel.border_title = "recent files"
        elif "/" in token:
            panel.border_title = token[: token.rindex("/") + 1]
        else:
            panel.border_title = token

        if is_history:
            panel.border_subtitle = "[^L] accept  [^D] delete"
        else:
            panel.border_subtitle = ""

        panel.update(content)
        panel.remove_class("hidden")
        self._completion_visible = True
        line_count = len(content.plain.splitlines()) if content.plain else 0
        self._completion_line_count = line_count + 3  # +3 for panel border + margin
        self._update_height()

    def _append_xprompt_completion_row(
        self,
        content: Text,
        candidate: CompletionCandidate,
        is_selected: bool,
    ) -> None:
        """Append one xprompt completion row using assist metadata when present."""
        content.append(
            candidate.display,
            style="bold green" if is_selected else "green",
        )
        entry = (
            candidate.metadata
            if isinstance(candidate.metadata, XPromptAssistEntry)
            else None
        )
        if entry is None:
            return

        kind = "skill" if entry.is_skill else entry.kind
        content.append(f"  {kind}", style="dim")
        if entry.description:
            content.append(f"  {entry.description}", style="dim")
        append_input_hints(content, entry.inputs)

    def _append_directive_completion_row(
        self,
        content: Text,
        candidate: CompletionCandidate,
        is_selected: bool,
    ) -> None:
        """Append one prompt directive completion row."""
        content.append(
            candidate.display,
            style="bold magenta" if is_selected else "magenta",
        )
        metadata = (
            candidate.metadata
            if isinstance(candidate.metadata, DirectiveCompletionMetadata)
            else None
        )
        if metadata is None:
            return

        details: list[str] = []
        if metadata.argument_hint:
            details.append(metadata.argument_hint)
        if metadata.aliases:
            details.append(
                "alias " + ", ".join(f"%{alias}" for alias in metadata.aliases)
            )
        if metadata.description:
            details.append(metadata.description)
        if details:
            content.append(f"  {'  '.join(details)}", style="dim")

    def hide_file_completions(self) -> None:
        """Hide the path completion panel."""
        panel = self.query_one("#prompt-completion", Static)
        panel.update("")
        panel.add_class("hidden")
        self._completion_visible = False
        self._completion_line_count = 0
        self._update_height()

    def set_prompt_mode_subtitle(self, subtitle: str) -> None:
        """Set the prompt mode subtitle, preserving any visible soft suggestion."""
        self._mode_subtitle = subtitle
        if not self._soft_completion_visible:
            self.border_subtitle = subtitle

    def show_soft_completion(self, suggestion: PromptSoftCompletion) -> None:
        """Render a soft completion in the prompt bar subtitle."""
        display = suggestion.display.replace("\n", " ").strip()
        if len(display) > 48:
            display = f"{display[:45]}..."
        self._soft_completion_visible = True
        self.border_subtitle = f"[^L] accept {display}"

    def hide_soft_completion(self) -> None:
        """Restore the mode subtitle when no soft completion is visible."""
        if not self._soft_completion_visible:
            return
        self._soft_completion_visible = False
        self.border_subtitle = self._mode_subtitle

    def show_xprompt_arg_hint(self, hint: ActiveXPromptArgHint) -> None:
        """Show the post-accept xprompt argument hint panel."""
        panel = self.query_one("#prompt-completion", Static)
        content = Text()
        content.append(hint.reference_text, style="bold green")
        content.append(" arguments", style="dim")
        append_input_hints(
            content,
            hint.entry.inputs,
            active_index=hint.active_input_index,
            include_descriptions=True,
        )

        panel.border_title = "xprompt args"
        panel.border_subtitle = "[:] colon  [(] named args"
        panel.update(content)
        panel.remove_class("hidden")
        self._completion_visible = True
        line_count = len(content.plain.splitlines()) if content.plain else 0
        self._completion_line_count = line_count + 3
        self._update_height()

    def _handle_text_submission(self, _text: str) -> None:
        """Process text submission from a pane's TextArea.

        Phase 2 preserves the pre-stack contract: ``<enter>`` submits the whole
        prompt.  The whole stack is joined back into one canonical multi-prompt
        string so dispatch splits it exactly as it did when the bar was a single
        text box.  (Per-pane submit semantics arrive in Phase 4.)
        """
        self.post_message(self.Submitted(self.current_prompt_text(), mode=self._mode))

    def action_cancel(self) -> None:
        """Cancel the input bar."""
        text_area = self.active_text_area()
        text_area._clear_soft_completion(cancel_timer=True)
        text_area._clear_xprompt_arg_hint()
        self.post_message(
            self.Cancelled(cancelled_text=self.current_prompt_text(), mode=self._mode)
        )

    def insert_snippet(
        self,
        snippet_name: str,
        entry: XPromptAssistEntry | None = None,
    ) -> None:
        """Insert a snippet reference at the cursor position.

        The '#' from the '#@' trigger is already in the input
        ('@' was prevented), so we just append the snippet name.

        Args:
            snippet_name: The snippet name to insert (without #)
            entry: Optional selected xprompt metadata for smart argument insertion.
        """
        text_area = self.active_text_area()
        start, end = text_area.selection
        if entry is not None and self._insert_xprompt_smart_snippet(
            text_area,
            entry,
            start,
            end,
        ):
            text_area.focus()
            return

        reference_start = max(0, text_area._absolute_offset(start) - 1)
        text_area._replace_via_keyboard(snippet_name, start, end)
        reference_end = reference_start + 1 + len(snippet_name)
        text_area._maybe_show_inserted_xprompt_arg_hint(reference_start, reference_end)
        text_area.focus()

    def _insert_xprompt_smart_snippet(
        self,
        text_area: PromptTextArea,
        entry: XPromptAssistEntry,
        start: tuple[int, int],
        end: tuple[int, int],
    ) -> bool:
        """Insert a selected xprompt using the Ctrl+T completion skeleton."""
        skeleton = xprompt_completion_suffix_skeleton(entry)
        if not text_area._expand_snippet_template_at_range(skeleton, start, end):
            return False

        cursor_offset = text_area._absolute_offset(text_area.cursor_location)
        hint = detect_xprompt_arg_hint_at_cursor(
            text_area.text,
            cursor_offset,
            [entry],
        )
        if hint is None:
            text_area._clear_xprompt_arg_hint()
            return True

        text_area._active_xprompt_arg_hint = hint
        text_area._show_xprompt_arg_hint(hint)
        return True

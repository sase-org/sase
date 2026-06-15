"""Prompt input bar widget for agent workflow in the ace TUI."""

from typing import Any

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.dom import NoScreen
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Static, TextArea

from sase.ace.tui.widgets._prompt_input_bar_actions import (
    PromptInputBarActionsMixin,
)
from sase.ace.tui.widgets._prompt_input_bar_completion import (
    PromptInputBarCompletionMixin,
)
from sase.ace.tui.widgets._prompt_input_bar_stack_actions import (
    PromptInputBarStackActionsMixin,
)
from sase.ace.tui.widgets.prompt_stack import (
    PromptStackItem,
    PromptStackState,
    split_prompt_text,
)
from sase.ace.tui.widgets.prompt_text_area import PromptTextArea

# Inactive panes never grow past this many content rows so the active pane
# keeps the room.  Phase 2 height rule: active grows most, inactive compact.
_INACTIVE_PANE_MAX_ROWS = 4


class PromptInputBar(
    PromptInputBarStackActionsMixin,
    PromptInputBarActionsMixin,
    PromptInputBarCompletionMixin,
    Static,
):
    """Prompt input bar for agent workflow, positioned at bottom of screen."""

    class Submitted(Message):
        """Message sent when prompt is submitted.

        Phase 4 distinguishes the two stack submit shapes:

        - ``whole_stack`` is set when the whole stack was joined into one
          multi-prompt string (``<shift+enter>`` / ``<ctrl+s>``); the app
          unmounts the bar and routes ``value`` through the existing
          multi-prompt launch rules.
        - ``keep_bar`` is set when only the selected pane was submitted while
          other panes remain; the app launches ``value`` but leaves the bar
          mounted so the remaining panes can be submitted next.
        """

        def __init__(
            self,
            value: str,
            mode: str = "prompt",
            *,
            whole_stack: bool = False,
            keep_bar: bool = False,
        ) -> None:
            super().__init__()
            self.value = value
            self.mode = mode
            self.whole_stack = whole_stack
            self.keep_bar = keep_bar

    class Cancelled(Message):
        """Message sent when input is cancelled.

        ``keep_bar`` is set when only the selected pane was cancelled while
        other panes remain; the app records ``cancelled_text`` as cancelled
        history but leaves the bar mounted.  Without it the whole bar is being
        dismissed, as before.
        """

        def __init__(
            self,
            cancelled_text: str = "",
            mode: str = "prompt",
            *,
            keep_bar: bool = False,
        ) -> None:
            super().__init__()
            self.cancelled_text = cancelled_text
            self.mode = mode
            self.keep_bar = keep_bar

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
        # Guards against piling up deferred live-split passes while the user
        # keeps typing past a freshly completed ``---`` separator line.
        self._live_split_pending = False
        self._stack = self._state_from_text(initial_value)

    @property
    def _base_title(self) -> str:
        """Return the base border title based on mode."""
        if self._mode == "feedback":
            return "Plan Feedback"
        if self._mode == "approve_prompt":
            return "Coder Prompt"
        return "Prompt"

    def insert_mode_subtitle(self) -> str:
        """Return the insert-mode subtitle, advertising ``^S`` when stacked.

        ``<enter>`` submits only the selected pane, so a multi-pane stack adds a
        ``[^S] all`` hint for the whole-stack submit (the portable fallback for
        ``<shift+enter>``).
        """
        base = "[Enter] send  [Esc] normal  [^C] cancel"
        if self._mode == "prompt" and len(self._stack) > 1:
            return f"{base}  [^S] all"
        return base

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
        self.set_prompt_mode_subtitle(self.insert_mode_subtitle())
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

    def _rebuild_stack(self, enter_mode: str | None = None) -> None:
        """Re-render the prompt stack to match ``self._stack`` from scratch.

        Used by deliberate whole-stack replacements (``load_stack_from_text``)
        and by the Phase 3 structural keymaps (reorder, add pane, live split).
        Bumps the generation so freshly mounted panes never share ids with the
        panes still being detached asynchronously.  *enter_mode* optionally puts
        the rebuilt active pane into vim ``"normal"`` or ``"insert"`` mode once
        it has mounted, so reorder keeps the user in normal mode while adding /
        splitting drops them into the new pane ready to type.
        """
        self._generation += 1
        try:
            container = self.query_one("#prompt-stack", Vertical)
        except Exception:
            return
        container.remove_children()
        container.mount(*self._build_pane_widgets())
        self.call_after_refresh(lambda: self._after_rebuild(enter_mode))

    def _after_rebuild(self, enter_mode: str | None = None) -> None:
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
        if enter_mode == "normal":
            text_area._enter_normal_mode()
        elif enter_mode == "insert":
            text_area._enter_insert_mode()
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

    def is_stacked(self) -> bool:
        """True when the bar currently holds more than one prompt pane."""
        return len(self._stack) > 1

    def load_stack_from_text(self, text: str) -> None:
        """Replace the whole stack with panes parsed from *text*.

        Real ``---`` separators render as stacked panes; anything else loads as
        a single pane.  Used by deliberate whole-bar loads (history load, or an
        editor return when the bar is a single pane) rather than active-pane
        edits.
        """
        self._stack = self._state_from_text(text)
        self._rebuild_stack()

    def update_active_pane(self, text: str) -> None:
        """Replace only the active pane's text with *text* (the ``^G`` path).

        Used when the external editor is opened on one pane of a multi-pane
        stack: the edit applies to that pane alone, leaving the rest of the
        stack — and its order — intact.  The edited text is loaded verbatim
        (embedded ``---`` is left in the pane and resolved by the launch parser
        on a later whole-stack submit), and the pane is re-focused for typing.
        """
        self._sync_state_from_widgets()
        self._stack.selected_item.text = text
        self._rebuild_stack(enter_mode="insert")

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
        self._maybe_live_split(text_area)

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

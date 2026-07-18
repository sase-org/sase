"""Prompt stack rendering, focus, and sizing behavior for ``PromptInputBar``."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from rich.cells import cell_len
from rich.text import Text
from textual.containers import Vertical
from textual.dom import NoScreen
from textual.widget import Widget
from textual.widgets import Static, TextArea

from sase.ace.tui.widgets.prompt_stack import (
    PromptStackItem,
    PromptStackState,
    XPromptBinding,
    split_frontmatter,
    split_prompt_text,
)
from sase.ace.tui.widgets.prompt_text_area import PromptTextArea
from sase.xprompt.prompt_frontmatter import PromptFrontmatter

if TYPE_CHECKING:
    from textual.widgets import Static as _MixinBase
else:
    _MixinBase = object

# Inactive panes never grow past this many content rows so the active pane keeps
# the room.  Phase 2 height rule: active grows most, inactive compact.
_INACTIVE_PANE_MAX_ROWS = 4
_STACK_SEPARATOR_RULE = "─"
_STACK_SEPARATOR_ACTIVE_MARKER = "▍"


class _PromptStackSeparator(Static):
    """Width-aware separator row for one prompt-stack pane."""

    def __init__(
        self, agent_number: int, *, active: bool = False, **kwargs: Any
    ) -> None:
        super().__init__("", **kwargs)
        self.agent_number = agent_number
        self.active = active

    def set_active(self, active: bool) -> None:
        """Update active state and refresh the rendered rule when it changes."""
        if self.active == active:
            return
        self.active = active
        self.refresh()

    def render(self) -> Text:
        """Render a centered agent label connected by full-width hairline rules."""
        width = max(0, int(self.size.width))
        label = f"agent {self.agent_number}"
        if self.active:
            label = f"{_STACK_SEPARATOR_ACTIVE_MARKER} {label}"
        padded_label = f" {label} "
        label_width = cell_len(padded_label)
        label_style = "bold" if self.active else "dim"

        if width <= label_width:
            text = Text(padded_label.strip(), no_wrap=True, overflow="ellipsis")
            text.truncate(width, overflow="ellipsis")
            text.stylize(label_style)
            return text

        rule_width = width - label_width
        left_width = rule_width // 2
        right_width = rule_width - left_width
        text = Text(no_wrap=True, overflow="crop")
        text.append(_STACK_SEPARATOR_RULE * left_width, style="dim")
        text.append(padded_label, style=label_style)
        text.append(_STACK_SEPARATOR_RULE * right_width, style="dim")
        return text


class PromptInputBarStackRenderingMixin(_MixinBase):
    """Prompt stack model, rendering, focus, and height helpers."""

    if TYPE_CHECKING:
        _completion_line_count: int
        _completion_visible: bool
        _generation: int
        _g_prefix_hints_line_count: int
        _g_prefix_hints_visible: bool
        _mode: str
        _placeholder: str
        _search_command_line_count: int
        _search_command_visible: bool
        _stack: PromptStackState
        _title_mode_suffix: str

        @property
        def _base_title(self) -> str: ...
        def _active_jinja_chip_markup(self) -> str: ...
        def _clear_active_completion_state(self) -> None: ...
        def _frontmatter_panel_reserved_rows(self) -> int: ...
        def _refresh_title(self, mode_suffix: str = "") -> None: ...
        def _resolve_pane_target(
            self, target_text_area: object, pane_id: str
        ) -> PromptTextArea | None: ...
        def refresh_frontmatter_panel_from_stack(self) -> None: ...
        def show_jinja_diagnostics(self, diagnostics: object) -> None: ...

    # -- stack model + rendering ---------------------------------------------

    def _state_from_text(self, text: str) -> PromptStackState:
        """Build stack state from *text*, splitting only real multi-prompts.

        Feedback / approve-prompt modes are never multi-agent surfaces, so they
        stay single-pane.  In prompt mode the canonical parser decides: text
        with real ``---`` separators (outside fences/frontmatter) splits into
        panes; anything else stays a single pane.  A leading YAML frontmatter
        block is lifted onto the stack in prompt mode so the structured panel
        and launch payload share the same source of truth.
        """
        if self._mode in ("feedback", "approve_prompt"):
            return PromptStackState.single(text)
        if len(split_prompt_text(text)) > 1:
            return PromptStackState.from_text(text)
        return PromptStackState.single(text, lift_frontmatter=True)

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
                    _PromptStackSeparator(
                        index + 1,
                        active=active,
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

        Used by deliberate whole-stack replacements
        (``load_stack_from_xprompt_markdown``), the inline history load
        (``load_prompt_into_pane``), and the structural keymaps (reorder, add
        pane).  Bumps the generation so freshly mounted panes never share ids
        with the panes still being detached asynchronously.  *enter_mode*
        optionally puts the rebuilt
        active pane into vim ``"normal"`` or ``"insert"`` mode once it has
        mounted, so reorder keeps the user in normal mode while adding a pane
        drops them into the new pane ready to type.
        """
        self._generation += 1
        self._refresh_title()
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
        text_area._warm_vcs_project_completion_catalog()
        text_area._warm_history_word_completion_cache()
        text_area._on_prompt_completion_context_changed()
        self._apply_active_classes()
        self._refresh_title()
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
                separator = self.query_one(
                    f"#{self._sep_id(item)}", _PromptStackSeparator
                )
            except Exception:
                continue
            separator.set_class(active, "active")
            separator.set_class(not active, "inactive")
            separator.set_active(active)

    # -- stack-aware public API ----------------------------------------------

    def active_text_area(self) -> PromptTextArea:
        """Return the ``PromptTextArea`` for the currently active pane."""
        item = self._stack.selected_item
        return self.query_one(f"#{self._pane_id(item)}", PromptTextArea)

    def active_text(self) -> str:
        """Return the active pane's text verbatim."""
        return self.active_text_area().text

    def is_multi_pane(self) -> bool:
        """Return ``True`` when the bar holds more than one prompt pane.

        Used by the prompt text area to decide whether the normal-mode pane
        controls move panes: ``K``/``J`` focus and ``Up``/``Down`` reorder act
        only on a real multi-pane stack.  A single-pane bar has no pane to focus
        or reorder, so it swallows bare ``K``/``J`` as a no-op (keeping them off
        the app-level Agents-tab bindings) and leaves ``Up``/``Down`` for
        normal-mode cursor movement.
        """
        return len(self._stack) > 1

    def all_prompt_texts(self) -> list[str]:
        """Return every pane's live text, top-to-bottom launch order."""
        self._sync_state_from_widgets()
        return list(self._stack.texts)

    def current_prompt_text(self) -> str:
        """Return the whole stack joined into one canonical multi-prompt string.

        Mirrors the whole-stack submit contract: empty panes are dropped and
        non-empty panes are joined with ``\\n---\\n`` (re-attaching
        frontmatter).  A single pane without frontmatter remains just that
        pane's stripped text.
        """
        self._sync_state_from_widgets()
        return self._stack.join()

    def is_stacked(self) -> bool:
        """True when the bar currently holds more than one prompt pane."""
        return len(self._stack) > 1

    def xprompt_markdown_for_editor(self) -> str:
        """Return the whole stack as spaced xprompt markdown for the all-pane editor.

        Syncs the live panes into the model first, then renders them in launch
        order with blank-line-padded ``---`` segment separators
        (``\\n\\n---\\n\\n``), re-attaching the canonical frontmatter followed by
        a blank line only when properties are set (so an empty frontmatter
        leaves no stray ``---\\n---`` block).  This editor-friendly spacing is
        scoped to the buffer multi-pane ``^G`` opens; the launch payload from
        :meth:`current_prompt_text` keeps the compact ``\\n---\\n`` form.  The
        edited result is reloaded via :meth:`load_stack_from_xprompt_markdown`,
        whose splitter drops the surrounding blank segments.  Leading
        frontmatter lives on the stack and is re-attached here, not kept inside
        a body pane.
        """
        self._sync_state_from_widgets()
        return self._stack.editor_markdown()

    def load_stack_from_xprompt_markdown(
        self, text: str, *, binding: XPromptBinding | None = None
    ) -> None:
        """Reload the whole bar from edited xprompt markdown (the multi-pane ``^G`` return).

        This always treats *text* as xprompt markdown via
        :meth:`PromptStackState.from_text`, lifting leading frontmatter into the
        shared stack frontmatter and splitting real ``---`` separators into
        panes.  The frontmatter panel is re-synced so the lifted frontmatter
        shows in the structured panel state.  Unlike the inline history load
        (:meth:`load_prompt_into_pane`), this replaces the whole stack and
        normalizes a lone body pane through the canonical splitter instead of
        keeping the body text verbatim.
        """
        self._stack = PromptStackState.from_text(text)
        if binding is not None:
            self._stack.bind(binding, source_markdown=text)
        self._rebuild_stack()
        self.refresh_frontmatter_panel_from_stack()

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

    def load_prompt_into_pane(
        self, target_text_area: object, pane_id: str, text: str
    ) -> bool:
        """Load a history entry into the origin pane, preserving the rest of the stack.

        The inline ``Ctrl+I`` history-load path: unlike a whole-stack replace,
        *text* (the VCS-substituted history entry) loads into the exact pane the
        user opened the history modal from -- resolved through the same staleness
        guard the ``#@`` selector uses -- while every other pane keeps its live
        text and relative order.

        A single-segment body replaces just that pane's text (kept verbatim, the
        ``lift_frontmatter=True`` single-pane path, so an xprompt-swarm
        invocation or a plain prompt stays one pane); a multi-segment body (real
        ``---`` separators outside fences/frontmatter) replaces the pane with its
        first stripped segment and inserts one new pane per remaining segment
        directly below, in order.  Leading frontmatter is lifted: a non-empty
        block overwrites the stack's frontmatter (the conflict confirmation runs
        in the app layer *before* this is called); an incoming-empty block leaves
        the current frontmatter untouched.

        Returns ``False`` without touching any pane when the captured target is
        stale (its pane or bar was unmounted/rebuilt while the modal was open),
        so the caller can notify and leave every prompt unchanged.
        """
        text_area = self._resolve_pane_target(target_text_area, pane_id)
        if text_area is None:
            return False

        # Sync live edits from every pane back into the model first (like
        # ``update_active_pane``), so panes the user touched while the modal was
        # open survive the rebuild.
        self._sync_state_from_widgets()

        index = self._pane_index_for(text_area)
        if index is None:
            return False

        frontmatter, body = split_frontmatter(text)
        segments = split_prompt_text(body)
        if len(segments) <= 1:
            # A single-segment body is kept verbatim rather than stripped,
            # matching ``PromptStackState.single(lift_frontmatter=True)``.
            segments = [body]

        self._stack.load_segments_at(index, segments)
        if frontmatter:
            self._stack.frontmatter = frontmatter

        self._rebuild_stack(enter_mode="insert")
        self.refresh_frontmatter_panel_from_stack()
        return True

    def _pane_index_for(self, text_area: PromptTextArea) -> int | None:
        """Return the stack index whose pane widget is *text_area*, else ``None``."""
        for index, item in enumerate(self._stack.items):
            if self._pane_id(item) == text_area.id:
                return index
        return None

    def has_frontmatter_properties(self) -> bool:
        """True when the stack currently carries non-empty xprompt properties.

        Drives the history-load conflict check: an incoming entry with its own
        frontmatter must not silently clobber properties the user already
        staged.  A non-empty frontmatter string that parses to a non-``is_empty``
        :class:`PromptFrontmatter` counts; a non-empty string that fails to parse
        (mid-edit YAML) is conservatively treated as properties present, so a
        confirmation is shown rather than silently overwriting the draft.
        """
        raw = self._stack.frontmatter
        if not raw:
            return False
        try:
            return not PromptFrontmatter.parse(raw).is_empty
        except Exception:
            return True

    def current_frontmatter(self) -> str:
        """Return the stack's current raw frontmatter string (``""`` when unset)."""
        return self._stack.frontmatter

    def focus_item(self, index: int) -> int:
        """Focus the pane at *index* (clamped); return the clamped index."""
        self._clear_active_completion_state()
        self._stack.focus(index)
        self._apply_active_classes()
        self.active_text_area().focus()
        self._refresh_title()
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
                self._clear_active_completion_state()
                self._stack.selected_index = index
                self._apply_active_classes()
                self._schedule_height_update()
                return

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        """Update height and line numbers when text changes.

        Purely passive: a typed ``---`` is left as literal text in the pane.  The
        properties panel and extra panes are reached only through explicit
        prompt NORMAL-mode ``g=`` and ``g-`` controls.
        """
        text_area = event.text_area
        if not isinstance(text_area, PromptTextArea):
            text_area = self.active_text_area()
        text_area.show_line_numbers = text_area.document.line_count > 1
        text_area._on_prompt_completion_context_changed()
        self._sync_state_from_widgets()
        self._refresh_title(self._title_mode_suffix)
        self._schedule_height_update()

    def on_text_area_selection_changed(self, event: TextArea.SelectionChanged) -> None:
        """Refresh soft completion when the prompt cursor moves."""
        if isinstance(event.text_area, PromptTextArea):
            event.text_area._on_prompt_completion_context_changed()

    def _maybe_show_active_jinja_diagnostics(self) -> None:
        """Restore active Jinja diagnostics after a higher-priority panel hides."""
        try:
            text_area = self.active_text_area()
        except Exception:
            return
        diagnostics = getattr(text_area, "_jinja_diagnostics", None)
        if diagnostics is None:
            return
        has_jinja = bool(getattr(diagnostics, "has_jinja", False))
        ok = bool(getattr(diagnostics, "ok", True))
        unknown = tuple(getattr(diagnostics, "unknown_variables", ()) or ())
        if has_jinja and (not ok or unknown):
            self.show_jinja_diagnostics(diagnostics)

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
        frontmatter_rows = self._frontmatter_panel_reserved_rows()
        g_prefix_rows = (
            self._g_prefix_hints_line_count if self._g_prefix_hints_visible else 0
        )
        search_rows = (
            self._search_command_line_count if self._search_command_visible else 0
        )
        panel_rows = completion_rows + frontmatter_rows + g_prefix_rows + search_rows
        if len(self._stack) <= 1:
            # Single pane: identical formula to the pre-stack bar. +2 for the
            # bar's top/bottom border, plus transient panels when visible.
            visual_lines = self._get_visual_line_count()
            new_height = min(
                max(visual_lines + 2 + panel_rows, 3),
                max_height,
            )
            self.styles.height = new_height
            return
        self._apply_multi_pane_heights(max_height, panel_rows)

    def _apply_multi_pane_heights(self, max_height: int, completion_rows: int) -> None:
        """Size each pane so the stack fits the screen, active pane growing most.

        Inactive panes compact to at most ``_INACTIVE_PANE_MAX_ROWS`` rows first;
        the active pane takes whatever budget remains.  If the panes still
        cannot fit, inactive panes shrink toward one row before the active pane
        does.
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
        self._scroll_active_pane_visible()

    def _scroll_active_pane_visible(self) -> None:
        """Keep the focused pane reachable if the stack overflows vertically."""
        try:
            self.active_text_area().scroll_visible(animate=False)
        except Exception:
            pass

    def _schedule_height_update(self) -> None:
        """Update now and once more after Textual has refreshed wrapping."""
        self._update_height()
        self.call_after_refresh(self._update_height)

    def on_resize(self) -> None:
        """Recalculate height when the terminal is resized."""
        self._schedule_height_update()

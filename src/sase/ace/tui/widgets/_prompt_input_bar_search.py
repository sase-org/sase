"""Prompt search command-line panel for ``PromptInputBar``."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from rich.cells import cell_len
from rich.text import Text
from textual.widgets import Static

from sase.ace.tui.widgets._prompt_search_readout import (
    PromptSearchReadout,
    SearchOperatorPalette,
    format_search_count_segment,
    search_operator_palette,
    stack_match_position,
)
from sase.ace.tui.widgets._vim_search import (
    PromptSearchQuery,
    SearchDirection,
    SearchSelection,
    SearchSpan,
    find_search_matches,
)
from sase.ace.tui.widgets.prompt_text_area import PromptTextArea
from sase.ace.tui.widgets.search_command_line import render_search_command_line

if TYPE_CHECKING:
    from sase.ace.tui.widgets.frontmatter_panel import FrontmatterPanel
    from sase.ace.tui.widgets.prompt_stack import PromptStackItem, PromptStackState
    from textual.widgets import Static as _MixinBase
else:
    _MixinBase = object


@dataclass(frozen=True)
class _PromptSearchPaneSnapshot:
    """One mounted prompt pane and its matches in stack order."""

    stack_index: int
    text_area: PromptTextArea
    text: str
    spans: tuple[SearchSpan, ...]


@dataclass(frozen=True)
class _PromptSearchDestination:
    """A globally resolved match plus whole-stack wrap state."""

    pane: _PromptSearchPaneSnapshot
    local_match_index: int
    ordinal: int
    total: int
    wrapped: bool


class PromptInputBarSearchMixin(_MixinBase):
    """Transient Vim-style search command line for the prompt body."""

    if TYPE_CHECKING:
        _completion_line_count: int
        _completion_panel_kind: str | None
        _completion_visible: bool
        _stack: PromptStackState
        _search_command_line_count: int
        _search_command_visible: bool
        _subtitle_base: str

        def _pane_id(self, item: PromptStackItem) -> str: ...
        def _render_subtitle(self, base: str) -> Text: ...
        def _schedule_height_update(self) -> None: ...
        def _frontmatter_panel(self) -> FrontmatterPanel | None: ...
        def focus_item(self, index: int) -> int: ...
        def hide_soft_completion(self) -> None: ...
        def hide_g_prefix_hints(self) -> None: ...

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self._prompt_search_register: PromptSearchQuery | None = None
        super().__init__(*args, **kwargs)

    def record_prompt_search(
        self,
        query: str,
        direction: SearchDirection,
        *,
        whole_word: bool = False,
        smartcase: bool = True,
    ) -> None:
        """Record the last successful search shared by this bar's panes."""
        self._prompt_search_register = PromptSearchQuery(
            query=query,
            direction=direction,
            whole_word=whole_word,
            smartcase=smartcase,
        )

    def prompt_search_register(self) -> PromptSearchQuery | None:
        """Return the last successful search shared by this bar's panes."""
        return self._prompt_search_register

    def repeat_prompt_search(
        self,
        origin: PromptTextArea,
        *,
        reverse: bool = False,
        count: int = 1,
    ) -> bool:
        """Repeat the shared search through every mounted pane in stack order."""
        search_register = self._prompt_search_register
        if search_register is None:
            origin._show_prompt_search_feedback("no previous search")
            return True

        direction = (
            self._invert_search_direction(search_register.direction)
            if reverse
            else search_register.direction
        )
        panes = self._prompt_search_pane_snapshot(
            search_register.query,
            whole_word=search_register.whole_word,
            smartcase=search_register.smartcase,
        )
        destination = self._resolve_prompt_search_destination(
            panes,
            origin,
            direction,
            count=max(1, count),
        )
        if destination is None:
            for pane in panes:
                pane.text_area._clear_prompt_search_result()
            origin._show_prompt_search_feedback("pattern not found")
            return True

        target = destination.pane.text_area
        origin._clear_prompt_search_result()
        if target is not origin:
            self.focus_item(destination.pane.stack_index)
            target._enter_normal_mode()

        selection = SearchSelection(
            index=destination.local_match_index,
            wrapped=destination.wrapped,
        )
        readout = PromptSearchReadout(
            query=search_register.query,
            direction=search_register.direction,
            whole_word=search_register.whole_word,
            ordinal=destination.ordinal,
            total=destination.total,
            pane_text=destination.pane.text,
        )
        target._apply_prompt_search_result(
            destination.pane.spans,
            selection,
            readout=readout,
        )
        if target is not origin:
            target.scroll_cursor_visible()
            self._schedule_height_update()
        if destination.wrapped:
            origin._show_prompt_search_feedback(self._wrap_feedback_message(direction))
        return True

    def _prompt_search_pane_snapshot(
        self,
        query: str,
        *,
        whole_word: bool = False,
        smartcase: bool = True,
    ) -> tuple[_PromptSearchPaneSnapshot, ...]:
        """Capture mounted panes and their matches, in stack order."""
        panes: list[_PromptSearchPaneSnapshot] = []
        for stack_index, item in enumerate(self._stack.items):
            if item.is_auxiliary_pane:
                continue
            try:
                text_area = self.query_one(
                    f"#{self._pane_id(item)}",
                    PromptTextArea,
                )
            except Exception:
                continue
            text = text_area.text
            panes.append(
                _PromptSearchPaneSnapshot(
                    stack_index=stack_index,
                    text_area=text_area,
                    text=text,
                    spans=find_search_matches(
                        text,
                        query,
                        whole_word=whole_word,
                        smartcase=smartcase,
                    ),
                )
            )
        return tuple(panes)

    @staticmethod
    def _resolve_prompt_search_destination(
        panes: tuple[_PromptSearchPaneSnapshot, ...],
        origin: PromptTextArea,
        direction: SearchDirection,
        *,
        count: int,
    ) -> _PromptSearchDestination | None:
        """Resolve a counted repeat against the whole ordered pane snapshot."""
        origin_pane = next(
            (pane for pane in panes if pane.text_area is origin),
            None,
        )
        if origin_pane is None:
            return None

        candidates = [
            (pane, local_index, span)
            for pane in panes
            for local_index, span in enumerate(pane.spans)
        ]
        if not candidates:
            return None

        origin_offset = origin._absolute_offset(origin.cursor_location)
        if direction == "forward":
            base_index = next(
                (
                    index
                    for index, (pane, _local_index, (start, _end)) in enumerate(
                        candidates
                    )
                    if pane.stack_index > origin_pane.stack_index
                    or (
                        pane.stack_index == origin_pane.stack_index
                        and start > origin_offset
                    )
                ),
                0,
            )
            initially_wrapped = not any(
                pane.stack_index > origin_pane.stack_index
                or (
                    pane.stack_index == origin_pane.stack_index
                    and start > origin_offset
                )
                for pane, _local_index, (start, _end) in candidates
            )
            steps = count - 1
            destination_index = (base_index + steps) % len(candidates)
            wrapped = initially_wrapped or base_index + steps >= len(candidates)
        else:
            reverse_base = next(
                (
                    index
                    for index in range(len(candidates) - 1, -1, -1)
                    if candidates[index][0].stack_index < origin_pane.stack_index
                    or (
                        candidates[index][0].stack_index == origin_pane.stack_index
                        and candidates[index][2][0] < origin_offset
                    )
                ),
                len(candidates) - 1,
            )
            initially_wrapped = not any(
                pane.stack_index < origin_pane.stack_index
                or (
                    pane.stack_index == origin_pane.stack_index
                    and start < origin_offset
                )
                for pane, _local_index, (start, _end) in candidates
            )
            steps = count - 1
            destination_index = (reverse_base - steps) % len(candidates)
            wrapped = initially_wrapped or reverse_base - steps < 0

        pane, local_match_index, _span = candidates[destination_index]
        return _PromptSearchDestination(
            pane=pane,
            local_match_index=local_match_index,
            ordinal=destination_index + 1,
            total=len(candidates),
            wrapped=wrapped,
        )

    def prompt_search_stack_position(
        self,
        origin: PromptTextArea,
        local_spans: tuple[SearchSpan, ...],
        local_index: int | None,
        query: str,
        *,
        whole_word: bool,
        smartcase: bool,
    ) -> tuple[int | None, int]:
        """Return the stack-global match position for an active typing preview."""
        counts: list[int] = []
        origin_position: int | None = None
        for item in self._stack.items:
            if item.is_auxiliary_pane:
                continue
            try:
                text_area = self.query_one(
                    f"#{self._pane_id(item)}",
                    PromptTextArea,
                )
            except Exception:
                continue
            if text_area is origin:
                origin_position = len(counts)
                counts.append(len(local_spans))
                continue
            counts.append(
                len(
                    find_search_matches(
                        text_area.text,
                        query,
                        whole_word=whole_word,
                        smartcase=smartcase,
                    )
                )
            )

        if origin_position is None:
            return stack_match_position((len(local_spans),), 0, local_index)
        return stack_match_position(counts, origin_position, local_index)

    @staticmethod
    def _invert_search_direction(direction: SearchDirection) -> SearchDirection:
        """Return the opposite search direction."""
        return "reverse" if direction == "forward" else "forward"

    @staticmethod
    def _wrap_feedback_message(direction: SearchDirection) -> str:
        """Return Vim-style whole-stack wrap feedback for *direction*."""
        if direction == "forward":
            return "search hit BOTTOM, continuing at TOP"
        return "search hit TOP, continuing at BOTTOM"

    def prepare_search_command_line(self) -> None:
        """Hide other transient prompt panels before search opens."""
        self._hide_completion_panel_for_search()
        try:
            self.hide_g_prefix_hints()
        except Exception:
            pass
        frontmatter = None
        try:
            frontmatter = self._frontmatter_panel()
        except Exception:
            pass
        if frontmatter is not None and not frontmatter.has_class("hidden"):
            frontmatter.add_class("hidden")
            self._schedule_height_update()

    def _hide_completion_panel_for_search(self) -> None:
        """Hide completion/Jinja panels without restoring diagnostics."""
        try:
            self.hide_soft_completion()
        except Exception:
            pass
        try:
            panel = self.query_one("#prompt-completion", Static)
        except Exception:
            return
        panel.update("")
        panel.border_title = ""
        panel.border_subtitle = ""
        panel.remove_class("jinja-diagnostics")
        panel.remove_class("jinja-error")
        panel.remove_class("jinja-warning")
        panel.add_class("hidden")
        self._completion_visible = False
        self._completion_panel_kind = None
        self._completion_line_count = 0
        self._schedule_height_update()

    def show_search_command_line(
        self,
        *,
        direction: SearchDirection,
        query: str,
        readout: PromptSearchReadout | None,
        operator: Any | None = None,
    ) -> None:
        """Render and reveal the search command line."""
        try:
            panel = self.query_one("#prompt-search-command", Static)
        except Exception:
            return

        if operator is None:
            panel.border_title = "search"
            panel.border_subtitle = Text(
                "[enter] accept  [esc/^c] cancel", no_wrap=True
            )
            panel.remove_class("operator-destructive")
            panel.remove_class("operator-yank")
            panel.remove_class("operator-transform")
        else:
            verb = str(getattr(operator, "verb", "operate"))
            if direction == "forward":
                panel.border_title = f"{verb} to match"
            else:
                panel.border_title = f"{verb} back to match"
            panel.border_subtitle = Text(
                f"[enter] {verb}  [esc/^c] cancel", no_wrap=True
            )
            panel.remove_class("operator-destructive")
            panel.remove_class("operator-yank")
            panel.remove_class("operator-transform")
            family = str(getattr(operator, "family", "transform"))
            if family == "destructive":
                panel.add_class("operator-destructive")
            elif family == "yank":
                panel.add_class("operator-yank")
            else:
                panel.add_class("operator-transform")
        panel.update(
            self._render_search_command_line(
                direction=direction,
                query=query,
                readout=readout,
                operator=operator,
            )
        )
        panel.remove_class("hidden")

        was_visible = self._search_command_visible
        old_line_count = self._search_command_line_count
        self._search_command_visible = True
        self._search_command_line_count = 4
        self.refresh_search_readout()
        if not was_visible or old_line_count != self._search_command_line_count:
            self._schedule_height_update()

    def hide_search_command_line(self) -> None:
        """Hide the search command line."""
        if not self._search_command_visible:
            return
        try:
            panel = self.query_one("#prompt-search-command", Static)
        except Exception:
            return

        panel.update("")
        panel.border_title = ""
        panel.border_subtitle = ""
        panel.remove_class("operator-destructive")
        panel.remove_class("operator-yank")
        panel.remove_class("operator-transform")
        panel.add_class("hidden")
        self._search_command_visible = False
        self._search_command_line_count = 0
        self.refresh_search_readout()
        self._schedule_height_update()

    def _render_search_command_line(
        self,
        *,
        direction: SearchDirection,
        query: str,
        readout: PromptSearchReadout | None,
        operator: Any | None = None,
    ) -> Text:
        width = max(0, int(getattr(self.size, "width", 0)) - 4)
        if operator is None:
            current_index = (
                readout.ordinal - 1
                if readout is not None and readout.ordinal is not None
                else None
            )
            total = readout.total if readout is not None else 0
            return render_search_command_line(
                direction=direction,
                query=query,
                current_index=current_index,
                total=total,
                width=width,
                status=self._search_command_status(query, readout),
            )
        prefix = self._operator_command_prefix(operator)
        status = self._operator_command_status(operator, prefix, query, width)
        # The operator status already carries the pane-local count; suppress the
        # renderer's own count so it never duplicates or overrides it. An empty
        # Text (rather than None) also suppresses the renderer's own
        # "pattern not found" fallback when degradation drops the status.
        status_arg = status if status is not None else Text(no_wrap=True)
        return render_search_command_line(
            direction=direction,
            query=query,
            current_index=None,
            total=0,
            width=width,
            status=status_arg,
            prefix=prefix,
        )

    def _operator_command_prefix(self, operator: Any) -> Text | None:
        """Return the operator chip drawn before the search sigil."""
        op = str(getattr(operator, "operator", ""))
        if not op:
            return None
        count = int(getattr(operator, "count", 1) or 1)
        family = str(getattr(operator, "family", "transform"))
        try:
            variables = self.app.theme_variables
        except Exception:
            variables = None
        palette: SearchOperatorPalette = search_operator_palette(family, variables)
        text = Text(no_wrap=True, overflow="crop")
        label = f"{count}{op}" if count > 1 else op
        text.append(f"{label} ", palette.chip)
        return text

    def _operator_command_status(
        self, operator: Any, prefix: Text | None, query: str, width: int
    ) -> Text | None:
        """Compose the operator status with narrow-width degradation."""
        effect = getattr(operator, "effect", None)
        miss = getattr(operator, "miss", None)
        ordinal = getattr(operator, "ordinal", None)
        total = int(getattr(operator, "total", 0) or 0)
        family = str(getattr(operator, "family", "transform"))
        try:
            variables = self.app.theme_variables
        except Exception:
            variables = None
        sigil = "?" if getattr(operator, "direction", "forward") == "reverse" else "/"
        prefix_plain = prefix.plain if prefix is not None else ""
        left_len = cell_len(f"{prefix_plain}{sigil}{query} ")
        gap = 2
        if effect:
            palette: SearchOperatorPalette = search_operator_palette(family, variables)
            full = Text(no_wrap=True, overflow="crop")
            full.append(str(effect), palette.effect)
            count = format_search_count_segment(ordinal, total, variables=variables)
            if count.plain:
                full.append_text(count)
            if not width or left_len + cell_len(full.plain) + gap <= width:
                return full
            count_only = format_search_count_segment(
                ordinal, total, variables=variables
            )
            if count_only.plain and (
                not width or left_len + cell_len(count_only.plain) + gap <= width
            ):
                return count_only
            return None
        if miss:
            text = Text(str(miss), style="dim", no_wrap=True)
            if not width or left_len + cell_len(text.plain) + gap <= width:
                return text
            return None
        return None

    def _search_command_status(
        self,
        query: str,
        readout: PromptSearchReadout | None,
    ) -> Text | None:
        if not query or readout is None:
            return None
        theme = self.app.current_theme
        if readout.ordinal is not None and readout.total > 0:
            return format_search_count_segment(
                readout.ordinal,
                readout.total,
                variables=self.app.theme_variables,
            )
        if readout.total > 0:
            warning = getattr(theme, "warning", "#FFA62B") or "#FFA62B"
            warning_text = getattr(warning, "hex", str(warning))
            return Text(
                f"no match in this pane · {readout.total} in stack",
                style=f"dim {warning_text}",
                no_wrap=True,
            )
        return Text("pattern not found", style="dim #FF5F5F", no_wrap=True)

    def refresh_search_readout(self) -> None:
        """Refresh the prompt bar subtitle after search readout state changes."""
        render = getattr(self, "_render_subtitle", None)
        if callable(render):
            self.border_subtitle = render(self._subtitle_base)

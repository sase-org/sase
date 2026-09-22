"""Operator + search-motion mixin for ``PromptTextArea``."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from textual.events import Key

from sase.ace.tui.widgets._vim_normal_state import SearchMotionMutation
from sase.ace.tui.widgets._vim_search import SearchDirection
from sase.ace.tui.widgets._vim_search_motion import (
    SEARCH_MOTION_MUTATING_OPERATORS,
    SearchMotionRange,
    SearchMotionResolution,
    SearchOperatorPreview,
    SearchOperatorRequest,
    describe_search_motion_effect,
    resolve_search_motion,
    search_motion_miss_message,
    search_operator_family,
    search_operator_verb,
)
from sase.ace.tui.widgets.vim_search_controller import line_start_offsets

if TYPE_CHECKING:
    from textual.widgets import TextArea as _MixinBase
else:
    _MixinBase = object


class PromptSearchOperatorMixin(_MixinBase):
    """NORMAL-mode operator search motions (``d/foo``, ``dn``) for prompts."""

    if TYPE_CHECKING:
        _search_active: bool
        _search_query: str
        _search_direction: SearchDirection
        _search_origin_cursor: tuple[int, int]
        _search_origin_offset: int
        _search_operator: SearchOperatorRequest | None
        _search_operator_preview: SearchOperatorPreview | None
        _search_current_selection: Any
        _mutation_key_buffer: list[str]
        _replaying_dot: bool
        _vim_mode: str
        _last_mutation_insert: str | None
        _last_search_motion_mutation: SearchMotionMutation | None
        _search_operator_region: tuple[int, int, str] | None

        def _absolute_offset(self, location: tuple[int, int]) -> int: ...
        def _location_from_absolute(self, offset: int) -> tuple[int, int]: ...
        def _find_prompt_bar(self) -> Any: ...
        def _set_search_highlights(
            self,
            spans: Any,
            current_index: int | None = None,
            *,
            refresh: bool = True,
            readout: Any | None = None,
        ) -> None: ...
        def _set_search_operator_region(
            self, start: int, end: int, family: str, *, refresh: bool = True
        ) -> None: ...
        def _clear_search_highlights(self, *, refresh: bool = True) -> None: ...
        def _cancel_prompt_search(self) -> None: ...
        def _render_prompt_search_command_line(self) -> None: ...
        def _hide_prompt_search_command_line(self) -> None: ...
        def _update_count_display(self) -> None: ...
        def _show_prompt_search_feedback(self, message: str) -> None: ...
        def _record_prompt_search_query(
            self,
            query: str,
            direction: SearchDirection,
            *,
            whole_word: bool,
            smartcase: bool,
        ) -> None: ...
        def _execute_charwise_operator(
            self, start: tuple[int, int], end: tuple[int, int], op: str
        ) -> None: ...
        def _execute_linewise_operator(
            self, first_row: int, last_row: int, op: str
        ) -> None: ...
        def _insert_replayed_text_and_return_normal(self, payload: str) -> None: ...
        def _open_prompt_search(
            self, direction: SearchDirection, operator: Any | None
        ) -> None: ...

    def _start_prompt_search_operator(
        self, direction: SearchDirection, operator: str, count: int
    ) -> bool:
        """Open an operator search motion for *operator* with total *count*."""
        self._open_prompt_search(
            direction, SearchOperatorRequest(operator, max(1, count))
        )
        return True

    def _update_prompt_search_operator_preview(self) -> None:
        """Refresh the operator preview region, cursor, and command line."""
        request = self._search_operator
        if request is None:
            return
        op = request.operator
        wanted = max(1, request.count)
        family = search_operator_family(op)
        verb = search_operator_verb(op)
        query = self._search_query
        direction = self._search_direction
        text = self.text
        origin_offset = self._search_origin_offset

        if not query:
            self.cursor_location = self._search_origin_cursor
            self._search_operator_region = None
            self._set_search_highlights((), current_index=None, readout=None)
            self._search_operator_preview = SearchOperatorPreview(
                operator=op,
                count=wanted,
                direction=direction,
                family=family,
                verb=verb,
                effect=None,
                miss=None,
                ordinal=None,
                total=0,
            )
            self._render_prompt_search_command_line()
            return

        resolution: SearchMotionResolution = resolve_search_motion(
            text,
            origin_offset,
            query,
            direction,
            count=wanted,
            whole_word=False,
            smartcase=True,
        )
        if resolution.motion_range is not None and resolution.target_index is not None:
            motion_range = resolution.motion_range
            if motion_range.linewise or op in {">", "<"}:
                starts = line_start_offsets(text)
                first = motion_range.first_row
                last = motion_range.last_row
                region_start = (
                    starts[first] if 0 <= first < len(starts) else motion_range.start
                )
                if 0 <= last + 1 < len(starts):
                    region_end = starts[last + 1]
                else:
                    region_end = len(text)
            else:
                region_start = motion_range.start
                region_end = motion_range.end
            self._set_search_operator_region(
                region_start, region_end, family, refresh=False
            )
        else:
            self._search_operator_region = None

        if resolution.target_index is not None:
            match_start, _match_end = resolution.spans[resolution.target_index]
            self.cursor_location = self._location_from_absolute(match_start)
            effect = describe_search_motion_effect(op, resolution.motion_range)  # type: ignore[arg-type]
            preview = SearchOperatorPreview(
                operator=op,
                count=wanted,
                direction=direction,
                family=family,
                verb=verb,
                effect=effect,
                miss=None,
                ordinal=resolution.target_index + 1,
                total=len(resolution.spans),
            )
        else:
            self.cursor_location = self._search_origin_cursor
            miss = search_motion_miss_message(resolution, direction, wanted, query)
            preview = SearchOperatorPreview(
                operator=op,
                count=wanted,
                direction=direction,
                family=family,
                verb=verb,
                effect=None,
                miss=miss,
                ordinal=None,
                total=len(resolution.spans),
            )
        self._set_search_highlights(
            resolution.spans,
            current_index=resolution.target_index,
            readout=None,
        )
        self._search_operator_preview = preview
        self._render_prompt_search_command_line()

    def _confirm_prompt_search_operator(self) -> None:
        """Commit an operator search motion against the live text."""
        request = self._search_operator
        if request is None:
            return
        op = request.operator
        wanted = max(1, request.count)
        query = self._search_query
        direction = self._search_direction
        origin_cursor = self._search_origin_cursor
        origin_offset = self._search_origin_offset

        # Empty query cancels without feedback.
        if not query:
            self._search_active = False
            self._hide_prompt_search_command_line()
            self._clear_search_highlights()
            self.cursor_location = origin_cursor
            self._search_query = ""
            self._search_current_selection = None
            self._search_operator = None
            self._search_operator_preview = None
            self._mutation_key_buffer.clear()
            self._update_count_display()
            return

        resolution: SearchMotionResolution = resolve_search_motion(
            self.text,
            origin_offset,
            query,
            direction,
            count=wanted,
            whole_word=False,
            smartcase=True,
        )

        # Tear the search UI down before editing so delete()/replace hooks
        # find nothing active.
        self._search_active = False
        self._hide_prompt_search_command_line()
        self._clear_search_highlights()
        self.cursor_location = origin_cursor
        self._search_query = ""
        self._search_current_selection = None
        self._search_operator = None
        self._search_operator_preview = None

        if resolution.motion_range is None or resolution.target_index is None:
            miss = search_motion_miss_message(resolution, direction, wanted, query)
            if not resolution.spans:
                self._show_prompt_search_feedback(f"pattern not found: {query}")
            else:
                self._show_prompt_search_feedback(miss)
            self._mutation_key_buffer.clear()
            self._update_count_display()
            return

        self._record_prompt_search_query(
            query, direction, whole_word=False, smartcase=True
        )
        self._run_search_motion_operator(op, resolution.motion_range)
        if op in SEARCH_MOTION_MUTATING_OPERATORS:
            self._last_search_motion_mutation = SearchMotionMutation(
                operator=op,
                count=wanted,
                query=query,
                direction=direction,
            )
        self._update_count_display()

    def _run_search_motion_operator(
        self, op: str, motion_range: SearchMotionRange
    ) -> None:
        """Dispatch an operator over *motion_range* through existing helpers."""
        if motion_range.linewise or op in {">", "<"}:
            self._execute_linewise_operator(
                motion_range.first_row, motion_range.last_row, op
            )
            return
        start = self._location_from_absolute(motion_range.start)
        end = self._location_from_absolute(motion_range.end)
        self._execute_charwise_operator(start, end, op)

    def _operate_to_search_register(
        self, operator: str, count: int, *, reverse: bool
    ) -> bool:
        """Operate from the cursor to the shared search register (``dn``)."""
        bar = None
        try:
            bar = self._find_prompt_bar()
        except Exception:
            bar = None
        register = None
        if bar is not None:
            getter = getattr(bar, "prompt_search_register", None)
            if callable(getter):
                try:
                    register = getter()
                except Exception:
                    register = None
        if register is None:
            self._show_prompt_search_feedback("no previous search")
            self._mutation_key_buffer.clear()
            self._update_count_display()
            return True

        query = str(getattr(register, "query", ""))
        recorded_direction = getattr(register, "direction", "forward")
        whole_word = bool(getattr(register, "whole_word", False))
        smartcase = bool(getattr(register, "smartcase", True))
        if reverse:
            direction: SearchDirection = (
                "reverse" if recorded_direction == "forward" else "forward"
            )
        else:
            direction = "reverse" if recorded_direction == "reverse" else "forward"
        if not query:
            self._show_prompt_search_feedback("no previous search")
            self._mutation_key_buffer.clear()
            self._update_count_display()
            return True

        origin = self._absolute_offset(self.cursor_location)
        resolution: SearchMotionResolution = resolve_search_motion(
            self.text,
            origin,
            query,
            direction,
            count=max(1, count),
            whole_word=whole_word,
            smartcase=smartcase,
        )
        if resolution.motion_range is None:
            miss = search_motion_miss_message(
                resolution, direction, max(1, count), query
            )
            if not resolution.spans:
                self._show_prompt_search_feedback(f"pattern not found: {query}")
            else:
                self._show_prompt_search_feedback(miss)
            self._mutation_key_buffer.clear()
            self._update_count_display()
            return True

        self._clear_search_highlights()
        self._run_search_motion_operator(operator, resolution.motion_range)
        self._update_count_display()
        return True

    def _replay_search_motion_mutation(
        self, mutation: SearchMotionMutation, count: int, has_count: bool
    ) -> None:
        """Dot-repeat an operator search motion from the current cursor."""
        effective = max(1, count) if has_count else max(1, mutation.count)
        origin = self._absolute_offset(self.cursor_location)
        resolution: SearchMotionResolution = resolve_search_motion(
            self.text,
            origin,
            mutation.query,
            mutation.direction,
            count=effective,
            whole_word=False,
            smartcase=True,
        )
        if resolution.motion_range is None:
            miss = search_motion_miss_message(
                resolution,
                mutation.direction,
                effective,
                mutation.query,
            )
            if not resolution.spans:
                self._show_prompt_search_feedback(
                    f"pattern not found: {mutation.query}"
                )
            else:
                self._show_prompt_search_feedback(miss)
            return

        insert_text = self._last_mutation_insert
        self._replaying_dot = True
        try:
            self._record_prompt_search_query(
                mutation.query,
                mutation.direction,
                whole_word=False,
                smartcase=True,
            )
            self._run_search_motion_operator(mutation.operator, resolution.motion_range)
            if (
                mutation.operator == "c"
                and insert_text is not None
                and self._vim_mode == "insert"
            ):
                self._insert_replayed_text_and_return_normal(insert_text)
        finally:
            self._replaying_dot = False
        self._update_count_display()

    def _handle_prompt_search_key(self, event: Key) -> bool:  # type: ignore[override]
        """Route operator-search keys to the operator preview path.

        This override lives on the operator mixin so the MRO dispatches here
        before :class:`PromptSearchMixin`. Plain searches fall through to the
        sibling implementation.
        """
        if getattr(self, "_search_operator", None) is not None:
            if not getattr(self, "_search_active", False):
                return False
            if event.key in {"escape", "ctrl+c"}:
                self._cancel_prompt_search()
                return True
            if event.key == "enter":
                # Enter never submits the prompt from inside a search motion.
                self._confirm_prompt_search_operator()
                return True
            if event.key in {"backspace", "ctrl+h"}:
                if self._search_query:
                    self._search_query = self._search_query[:-1]
                    self._update_prompt_search_operator_preview()
                return True
            char = event.character
            if char is not None and len(char) == 1 and event.key != "tab":
                self._search_query += char
                self._update_prompt_search_operator_preview()
                return True
            return True
        parent = getattr(super(), "_handle_prompt_search_key", None)
        if callable(parent):
            return bool(parent(event))
        return False


__all__ = ["PromptSearchOperatorMixin"]

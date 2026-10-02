"""Change navigation for the ``PagerScreen`` diff views.

Owns the ``[``/``]`` change jumps in both views and the scroll helpers
that move the body to a target line. View toggling and rendering live
in ``_screen_diff_view``; fold expansion lives in
``_screen_diff_folds``; this module never imports those siblings
except for the shared public task-registry name.
"""

from __future__ import annotations

from typing import Any

from sase.ace.tui.util.pump_tasks import spawn_pump_free_task
from sase.pager._line_mark import reading_scroll_y
from sase.pager._screen_diff_view import HISTORY_TASK_ATTR
from sase.pager.document import PagerSection
from sase.pager.history.diff import build_diff_body, read_view_change_lines

__all__ = ["PagerDiffNavigateMixin"]


class PagerDiffNavigateMixin:
    """Jump between changes in the read and diff views."""

    document: Any
    _body: Any | None
    _history_states: dict[str, Any]

    def action_history_prev_change(self: Any) -> None:
        """Jump to the previous change in either view."""
        self._jump_to_change(-1)

    def action_history_next_change(self: Any) -> None:
        """Jump to the next change in either view."""
        self._jump_to_change(1)

    def _jump_to_change(self: Any, direction: int) -> None:
        try:
            section = self._current_section()
        except Exception:
            return
        identity = section.identity
        state = self._history_states.get(identity)
        if state is None:
            if self._history_supported.get(identity) is False:
                self.notify("No history for this section.", severity="information")
                return
            self.notify("History still loading — try again.", severity="information")
            self._start_history_discovery_after_paint()
            return
        if self._effective_view(section, state) == "diff":
            lines = self._diff_change_lines(identity, section, state)
        else:
            lines = self._read_change_lines(identity, section, state)
        if lines is None:
            return
        if not lines:
            if self._current_ordinal(section, state) <= 0:
                self.notify(
                    "Open a past version to walk its changes.",
                    severity="information",
                )
            else:
                self.notify("No changes in this version.", severity="information")
            return
        try:
            index = next(
                i
                for i, s in enumerate(self.document.sections)
                if s.identity == identity
            )
        except StopIteration:
            return
        current = self._current_body_line(index)
        if direction < 0:
            candidates = [line for line in lines if line < current]
            if not candidates:
                self.notify("Already at the first change.", severity="information")
                return
            goal = max(candidates)
        else:
            candidates = [line for line in lines if line > current]
            if not candidates:
                self.notify("Already at the last change.", severity="information")
                return
            goal = min(candidates)
        self._scroll_to_body_line(index, goal)

    def _read_change_lines(
        self: Any, identity: str, section: PagerSection, state: Any
    ) -> tuple[int, ...] | None:
        ordinal = self._current_ordinal(section, state)
        if ordinal <= 0:
            return ()
        # Read-view change marks skip hidden versions: the base is the
        # newest steppable version below the target, not ordinal - 1.
        try:
            visible = tuple(getattr(state, "visible_ordinals", ()) or ())
            below = [int(v or 0) for v in visible if int(v or 0) < ordinal]
            base = max(below) if below else 0
        except Exception:
            base = ordinal - 1
        comparison = state.comparison_cache.get((base, ordinal))
        if comparison is None and base != 0:
            comparison = state.comparison_cache.get((0, ordinal))
        if not isinstance(comparison, dict):
            task = spawn_pump_free_task(
                self,
                self._load_one_comparison(
                    identity,
                    base,
                    ordinal,
                    self.document,
                    self._history_generation,
                ),
                name="sase-pager-history-compare",
                registry_attr=HISTORY_TASK_ATTR,
            )
            if task is None:
                self.notify("History worker unavailable.", severity="warning")
            else:
                self.notify("Loading changes — press again.", severity="information")
            return None
        return read_view_change_lines(comparison)

    def _diff_change_lines(
        self: Any, identity: str, section: PagerSection, state: Any
    ) -> tuple[int, ...] | None:
        endpoints = self._diff_endpoints_for(section, state)
        if endpoints is None:
            return ()
        base, target = endpoints
        comparison = state.comparison_cache.get((base, target))
        if not isinstance(comparison, dict):
            self._ensure_diff_view(identity)
            self.notify("Loading diff — press again.", severity="information")
            return None
        read_section = self._diff_read_section(identity, state, target)
        if read_section is None:
            return ()
        try:
            styles_fn = getattr(self, "_history_styles", None)
            styles = styles_fn() if callable(styles_fn) else None
            rendered = build_diff_body(
                comparison,
                read_section.plain_text,
                expanded=frozenset(state.expanded_folds),
                history_styles=styles,
            )
        except Exception:
            return ()
        return rendered.change_lines

    def _current_body_line(self: Any, section_index: int) -> int:
        try:
            body = self._body
            scroll = self._body_scroll()
            if body is None:
                return 1
            section_offset = body.section_offsets[section_index]
            top = max(int(scroll.scroll_y) - section_offset, 0)
            rows = body.section_line_rows[section_index]
            line = 1
            for number, row in enumerate(rows, start=1):
                if row <= top:
                    line = number
                else:
                    break
            return line
        except Exception:
            return 1

    def _scroll_to_body_line(self: Any, section_index: int, line: int) -> None:
        try:
            body = self._body
            scroll = self._body_scroll()
            if body is None:
                return
            rows = body.section_line_rows[section_index]
            if not rows:
                return
            clamped = max(1, min(line, len(rows)))
            start_row = rows[clamped - 1]
            if clamped < len(rows):
                end_row = rows[clamped] - 1
            elif section_index + 1 < len(body.section_offsets):
                end_row = body.section_offsets[section_index + 1] - 1
            else:
                end_row = max(body.total_height - 1, start_row)
            viewport = max(int(scroll.size.height), 1)
            goal = reading_scroll_y(
                start_row=start_row,
                end_row=max(end_row, start_row),
                viewport_height=viewport,
                max_scroll_y=scroll.max_scroll_y,
            )
            scroll.scroll_to(y=goal, animate=False, immediate=True)
            self._after_scroll()
        except Exception:
            pass

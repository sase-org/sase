"""``@`` timeline picker wiring for ``PagerScreen``.

Builds picker rows from the current section's loaded timeline (the
memory-side builder is imported lazily so pager core never depends on
memory modules), pushes the modal, and applies its result: ``⏎``
pushes a trail entry and jumps, ``=`` sets a two-point comparison
base against the open version. Small ``(``/``)`` steps never touch
the trail; picker jumps always do.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import replace
from typing import Any

from sase.ace.tui.util.pump_tasks import spawn_pump_free_task
from sase.pager._timeline_picker import TimelinePickerScreen

_HISTORY_TASK_ATTR = "_pump_free_history_tasks"

_PSEUDO_CLASSES = ("uncommitted", "staged")


class PagerTimelineMixin:
    """Own the ``@`` timeline picker for one screen."""

    document: Any
    _history_states: dict[str, Any]
    _history_generation: int
    _history_supported: dict[str, bool]
    _history_pending: dict[str, str]
    _history_view_sticky: Any

    def action_history_timeline(self: Any) -> None:
        """Open the timeline picker for the current section."""
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
        rows = self._timeline_picker_rows(identity)
        if rows is None:
            self.notify("History load failed — keeping live.", severity="warning")
            return
        if not rows:
            self.notify("No committed versions.", severity="information")
            return
        title, summary, cursor = self._timeline_picker_chrome(identity, rows)
        pin = state.current_pin or section.version_pin
        current_ordinal = int(getattr(pin, "ordinal", 0) or 0)
        current_class = self._timeline_current_class(state, current_ordinal)
        document = self.document
        generation = self._history_generation
        picker = TimelinePickerScreen(
            title=title,
            rows=rows,
            current_ordinal=current_ordinal,
            current_class=current_class,
            hidden_summary=summary,
            initial_cursor=cursor,
        )
        self.app.push_screen(
            picker,
            lambda result: self._on_timeline_picker_result(
                identity, result, document, generation
            ),
        )

    def _timeline_picker_rows(self: Any, identity: str) -> tuple[Any, ...] | None:
        """Build picker rows for *identity*, or ``None`` on failure."""
        from sase.memory.history.timeline_picker import build_picker_rows

        state = self._history_states.get(identity)
        if state is None:
            return None
        try:
            timeline = {"versions": list(state.timeline)}
            return build_picker_rows(timeline, now_epoch=int(time.time()))
        except Exception:
            return None

    def _timeline_picker_chrome(
        self: Any, identity: str, rows: tuple[Any, ...]
    ) -> tuple[str, str, int]:
        """Return ``(title, hidden_summary, initial_cursor)`` for *rows*."""
        from sase.memory.history.timeline_picker import (
            filter_picker_rows,
            hidden_picker_rows,
            hidden_summary_text,
            picker_header_text,
            visible_picker_rows,
        )

        try:
            section = next(s for s in self.document.sections if s.identity == identity)
            subject_display = section.title
        except StopIteration:
            subject_display = identity
        state = self._history_states.get(identity)
        pin = state.current_pin if state is not None else None
        if pin is None:
            try:
                pin = next(
                    s for s in self.document.sections if s.identity == identity
                ).version_pin
            except StopIteration:
                pin = None
        current_ordinal = int(getattr(pin, "ordinal", 0) or 0)
        current_class = self._timeline_current_class(state, current_ordinal)
        total_committed = sum(1 for row in rows if not bool(row.get("pseudo", False)))
        hidden_rows = hidden_picker_rows(rows)
        summary = hidden_summary_text(hidden_rows)
        header = picker_header_text(
            subject_display=subject_display,
            total_committed=total_committed,
            hidden_count=len(hidden_rows),
            show_hidden=False,
            query="",
        )
        listed = visible_picker_rows(rows, show_hidden=False)
        selectable = filter_picker_rows(listed, "")
        cursor = 0
        for index, row in enumerate(selectable):
            try:
                ordinal = int(row.get("ordinal", -1))
            except (TypeError, ValueError):
                continue
            if ordinal != current_ordinal:
                continue
            if ordinal == 0 and str(row.get("class", "")) != current_class:
                continue
            cursor = index
            break
        return (header, summary, cursor)

    def _timeline_current_class(self: Any, state: Any, ordinal: int) -> str:
        """Return the picker class identifying the open version."""
        if ordinal != 0:
            return ""
        status = str(getattr(state, "status", "") or "")
        if status == "dirty-now":
            return "uncommitted"
        return ""

    def _on_timeline_picker_result(
        self: Any,
        identity: str,
        result: dict[str, Any] | None,
        document: Any,
        generation: int,
    ) -> None:
        if not isinstance(result, dict):
            return
        action = str(result.get("action", "") or "")
        try:
            ordinal = int(result.get("ordinal", 0) or 0)
        except (TypeError, ValueError):
            return
        klass = str(result.get("class", "") or "")
        if action == "open":
            self._timeline_jump(identity, ordinal, klass, document, generation)
        elif action == "compare":
            self._timeline_compare(identity, ordinal, klass, document, generation)

    def _timeline_jump(
        self: Any,
        identity: str,
        ordinal: int,
        klass: str,
        document: Any,
        generation: int,
    ) -> None:
        state = self._history_states.get(identity)
        if state is None:
            return
        pin = state.current_pin
        current = int(getattr(pin, "ordinal", 0) or 0) if pin is not None else 0
        target = ordinal
        if klass in _PSEUDO_CLASSES:
            if klass == "staged":
                self.notify(
                    "Staged content has no preview — showing worktree.",
                    severity="information",
                )
            target = 0
        if target == current and (target != 0 or klass in _PSEUDO_CLASSES):
            if target != 0 or self._timeline_current_class(state, 0) == klass:
                self.notify("Already at that version.", severity="information")
                return
        self._push_trail_entry()
        task = spawn_pump_free_task(
            self,
            self._load_and_swap_version(identity, target, document, generation),
            name="sase-pager-history-step",
            registry_attr=_HISTORY_TASK_ATTR,
        )
        if task is None:
            self.notify("History worker unavailable.", severity="warning")

    def _timeline_compare(
        self: Any,
        identity: str,
        ordinal: int,
        klass: str,
        document: Any,
        generation: int,
    ) -> None:
        state = self._history_states.get(identity)
        if state is None:
            return
        pin = state.current_pin
        current = int(getattr(pin, "ordinal", 0) or 0) if pin is not None else 0
        if klass in _PSEUDO_CLASSES:
            if current == 0:
                self.notify("Already at the worktree.", severity="information")
                return
            if klass == "staged":
                self.notify(
                    "Staged content has no preview — comparing worktree.",
                    severity="information",
                )
            self._push_trail_entry()
            task = spawn_pump_free_task(
                self,
                self._timeline_compare_with_now(
                    identity, current, document, generation
                ),
                name="sase-pager-history-diff",
                registry_attr=_HISTORY_TASK_ATTR,
            )
            if task is None:
                self.notify("History worker unavailable.", severity="warning")
            return
        if ordinal == current:
            self.notify(
                "Same version — pick another row to compare.", severity="information"
            )
            return
        if pin is None:
            return
        try:
            state.current_pin = replace(pin, compare_base=ordinal, explicit_base=True)
        except Exception:
            return
        self._history_view_sticky = "diff"
        ensure = getattr(self, "_ensure_diff_view", None)
        if callable(ensure):
            ensure(identity)

    async def _timeline_compare_with_now(
        self: Any, identity: str, base: int, document: Any, generation: int
    ) -> None:
        await self._load_and_swap_version(identity, 0, document, generation)
        if self.document is not document:
            return
        state = self._history_states.get(identity)
        if state is None:
            return
        pin = state.current_pin
        if pin is None:
            return
        try:
            state.current_pin = replace(pin, compare_base=base, explicit_base=True)
        except Exception:
            return
        self._history_view_sticky = "diff"
        ensure = getattr(self, "_ensure_diff_view", None)
        if callable(ensure):
            ensure(identity)
        await asyncio.sleep(0)


__all__ = ["PagerTimelineMixin"]

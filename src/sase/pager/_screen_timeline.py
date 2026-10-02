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

#: Ordinal-0 row classes: the dirty worktree, staged content, and the
#: synthesized clean-now row (which carries an empty class).
_PSEUDO_CLASSES = ("uncommitted", "staged", "")


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
        title, summary, cursor, open_style = self._timeline_picker_chrome(
            identity, rows
        )
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
            open_style=open_style,
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
            from sase.pager.history.moment import moment_for_state

            moment = moment_for_state(state)
        except Exception:
            moment = None
        try:
            timeline = {"versions": list(state.timeline)}
            return build_picker_rows(
                timeline,
                now_epoch=int(time.time()),
                now_matches_newest=bool(
                    moment is not None and moment.now_matches_newest
                ),
                newest=int(moment.newest) if moment is not None else None,
            )
        except Exception:
            return None

    def _timeline_picker_chrome(
        self: Any, identity: str, rows: tuple[Any, ...]
    ) -> tuple[str, str, int, str]:
        """Return ``(title, hidden_summary, initial_cursor, open_style)``."""
        from sase.memory.history.timeline_picker import (
            filter_picker_rows,
            hidden_picker_rows,
            hidden_summary_text,
            picker_header_text,
            picker_pill_text,
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
        try:
            from sase.pager.history.moment import moment_for_state

            moment = moment_for_state(state) if state is not None else None
        except Exception:
            moment = None
        if moment is not None:
            # Counts come from the moment, so the header matches the
            # subject line: N is the newest committed ordinal, hidden
            # versions included.
            total_committed = int(moment.newest)
            pill = picker_pill_text(moment.kind, moment.ordinal, moment.newest)
            open_style = self._timeline_open_style(
                moment.kind if isinstance(moment.kind, str) else ""
            )
        else:
            total_committed = sum(
                1 for row in rows if not bool(row.get("pseudo", False))
            )
            pill = ""
            open_style = self._timeline_open_style("")
        hidden_rows = hidden_picker_rows(rows)
        summary = hidden_summary_text(hidden_rows)
        header = picker_header_text(
            subject_display=subject_display,
            total_committed=total_committed,
            hidden_count=len(hidden_rows),
            show_hidden=False,
            query="",
            pill_text=pill,
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
        return (header, summary, cursor, open_style)

    def _timeline_open_style(self: Any, kind: str) -> str:
        """Return the theme-aware style for the open version's label."""
        from sase.pager._timeline_picker import _CURRENT_STYLE

        try:
            styles_fn = getattr(self, "_history_styles", None)
            styles = styles_fn() if callable(styles_fn) else None
        except Exception:
            styles = None
        if styles is None:
            return _CURRENT_STYLE
        try:
            if kind == "past":
                return str(styles.past)
            if kind == "now_dirty":
                return str(styles.uncommitted)
            if kind == "deleted":
                return str(styles.tombstone)
            if kind == "now":
                return str(styles.foreground)
        except Exception:
            pass
        return _CURRENT_STYLE

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
        canonicalized = False
        try:
            from sase.pager.history.moment import (
                canonical_ordinal,
                moment_for_state,
            )

            moment = moment_for_state(state)
            if moment is not None:
                # Opening the newest version of a now ≡ vN subject reads
                # the live section instead of a byte-identical copy.
                target = canonical_ordinal(target, moment)
                canonicalized = target != ordinal
        except Exception:
            pass
        if klass in _PSEUDO_CLASSES:
            if klass == "staged":
                self.notify(
                    "Staged content has no preview — showing worktree.",
                    severity="information",
                )
            target = 0
        if target == current and (
            target != 0 or klass in _PSEUDO_CLASSES or canonicalized
        ):
            if (
                target != 0
                or canonicalized
                or self._timeline_current_class(state, 0) == klass
            ):
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
        # A compare against the ≡ now alias of an open now is byte-identical:
        # canonicalize the cursor the way jumps do and do nothing.
        try:
            from sase.pager.history.moment import canonical_ordinal, moment_for_state

            moment = moment_for_state(state)
            if moment is not None:
                canonical = canonical_ordinal(ordinal, moment)
                if canonical != ordinal and canonical == current:
                    self.notify(
                        "Same version — pick another row to compare.",
                        severity="information",
                    )
                    return
        except Exception:
            pass
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
        if current > 0 and ordinal > current:
            # The cursor is newer than the open version. Comparisons
            # always read older → newer, so the cursor's version becomes
            # the shown target and the open version becomes the base —
            # pushing a trail entry, as a picker jump does today.
            self._push_trail_entry()
            task = spawn_pump_free_task(
                self,
                self._timeline_compare_with_jump(
                    identity, ordinal, current, document, generation
                ),
                name="sase-pager-history-diff",
                registry_attr=_HISTORY_TASK_ATTR,
            )
            if task is None:
                self.notify("History worker unavailable.", severity="warning")
            return
        try:
            state.current_pin = replace(pin, compare_base=ordinal, explicit_base=True)
        except Exception:
            return
        self._history_view_sticky = "diff"
        ensure = getattr(self, "_ensure_diff_view", None)
        if callable(ensure):
            ensure(identity)

    async def _timeline_compare_with_jump(
        self: Any, identity: str, target: int, base: int, document: Any, generation: int
    ) -> None:
        await self._load_and_swap_version(identity, target, document, generation)
        state = self._history_states.get(identity)
        if state is None:
            return
        pin = state.current_pin
        if pin is None:
            return
        try:
            from sase.pager.history.moment import (
                canonical_ordinal,
                moment_for_state,
            )

            moment = moment_for_state(state)
            expected = (
                canonical_ordinal(target, moment) if moment is not None else target
            )
        except Exception:
            expected = target
        try:
            landed = int(getattr(pin, "ordinal", 0) or 0)
        except (TypeError, ValueError):
            return
        if landed != expected:
            # The user navigated away while the target loaded; leave
            # the new position alone instead of rerouting its compare.
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

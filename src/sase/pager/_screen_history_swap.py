"""History swap, prefetch, and anchor logic for ``PagerScreen``.

Owns gutter-mark computation, parent-comparison and neighbour
prefetching, the active-section swap with anchor preservation, and the
history-aware refresh. Discovery and stepping live in the sibling
``_screen_history_*`` modules.
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import Any

from sase.ace.tui.util.pump_tasks import spawn_pump_free_task
from sase.pager.document import PagerDocument, PagerSection
from sase.pager.history.models import SectionTimeState, live_pin_for_subject
from sase.pager.history.provider import history_provider_for_section

__all__ = ["PagerHistorySwapMixin"]

_HISTORY_TASK_ATTR = "_pump_free_history_tasks"
_HISTORY_CACHE_LIMIT = 50


class PagerHistorySwapMixin:
    """Swap active sections while preserving scroll, search, and marks."""

    document: PagerDocument
    _body: Any | None
    _label_layer: Any | None
    _history_states: dict[str, SectionTimeState]
    _history_generation: int

    def _history_marks_for_body(
        self: Any,
    ) -> tuple[dict[int, dict[int, str]] | None, dict[int, set[int]] | None]:
        states = getattr(self, "_history_states", None)
        if not states:
            return (None, None)
        try:
            from sase.memory.history.pager_provider import (
                history_marks_from_comparison,
            )
        except Exception:
            return (None, None)
        change_marks: dict[int, dict[int, str]] = {}
        removal_anchors: dict[int, set[int]] = {}
        sticky = getattr(self, "_history_view_sticky", None)
        for index, section in enumerate(self.document.sections):
            state = states.get(section.identity)
            if state is None:
                continue
            pin = state.current_pin or section.version_pin
            # The diff view carries its own word styling; read-view gutter
            # marks are target-line addressed and would misalign here.
            effective_view = (
                sticky if sticky is not None else getattr(pin, "view", "read")
            )
            if effective_view == "diff":
                continue
            ordinal = pin.ordinal if pin is not None else 0
            if ordinal <= 0:
                continue
            # Change marks skip hidden versions: the base is the newest
            # steppable version below the target.
            try:
                visible = tuple(getattr(state, "visible_ordinals", ()) or ())
                below = [int(v or 0) for v in visible if int(v or 0) < ordinal]
                mark_base = max(below) if below else 0
            except Exception:
                mark_base = ordinal - 1
            comparison = state.comparison_cache.get((mark_base, ordinal))
            if comparison is None and mark_base != 0:
                # v1 falls back to the empty-base comparison when present.
                comparison = state.comparison_cache.get((0, ordinal))
            if comparison is None or not isinstance(comparison, dict):
                continue
            marks, anchors = history_marks_from_comparison(comparison)
            if marks:
                change_marks[index] = marks
            if anchors:
                removal_anchors[index] = anchors
        if not change_marks and not removal_anchors:
            return (None, None)
        return (change_marks, removal_anchors)

    def _prefetch_parent_comparison(
        self: Any, identity: str, ordinal: int, document: PagerDocument, generation: int
    ) -> None:
        state = self._history_states.get(identity)
        if state is None or ordinal <= 0:
            return
        try:
            visible = tuple(getattr(state, "visible_ordinals", ()) or ())
            below = [int(v or 0) for v in visible if int(v or 0) < ordinal]
            base = max(below) if below else 0
        except Exception:
            base = ordinal - 1
        if (base, ordinal) in state.comparison_cache:
            return
        task = spawn_pump_free_task(
            self,
            self._load_one_comparison(identity, base, ordinal, document, generation),
            name="sase-pager-history-compare",
            registry_attr=_HISTORY_TASK_ATTR,
        )
        if task is None:
            return

    async def _load_one_comparison(
        self: Any,
        identity: str,
        base: int,
        target: int,
        document: PagerDocument,
        generation: int,
    ) -> None:
        state = self._history_states.get(identity)
        if state is None:
            return

        def _fetch() -> dict[str, Any] | None:
            try:
                section = next(s for s in document.sections if s.identity == identity)
            except StopIteration:
                return None
            try:
                provider = history_provider_for_section(section)
            except Exception:
                return None
            if provider is None:
                return None
            try:
                compare = getattr(provider, "compare_versions", None)
                if compare is None:
                    return None
                return compare(section, base, target)
            except Exception:
                return None

        comparison = await asyncio.to_thread(_fetch)
        if generation != self._history_generation or self.document is not document:
            return
        if not isinstance(comparison, dict):
            return
        if len(state.comparison_cache) >= _HISTORY_CACHE_LIMIT:
            state.comparison_cache.clear()
        state.comparison_cache[(base, target)] = comparison
        try:
            self._recompose_for_history_marks()
        except Exception:
            pass

    def _recompose_for_history_marks(self: Any) -> None:
        try:
            self._invalidate_body_paint()
            self._update_subject()
        except Exception:
            pass

    def _prefetch_neighbours(
        self: Any, identity: str, ordinal: int, document: PagerDocument, generation: int
    ) -> None:
        state = self._history_states.get(identity)
        if state is None:
            return
        visible = state.visible_ordinals
        neighbours: list[int] = []
        if ordinal == 0:
            neighbours = list(visible[-2:])
        elif ordinal in visible:
            index = visible.index(ordinal)
            neighbours = [
                v
                for v in (visible[index - 2 : index] + visible[index + 1 : index + 3])
                if v != ordinal
            ]
        for neighbour in neighbours:
            if (neighbour, state.subject_id) in state.body_cache:
                continue
            task = spawn_pump_free_task(
                self,
                self._prefetch_one(identity, neighbour, document, generation),
                name="sase-pager-history-prefetch",
                registry_attr=_HISTORY_TASK_ATTR,
            )
            if task is None:
                break

    async def _prefetch_one(
        self: Any, identity: str, ordinal: int, document: PagerDocument, generation: int
    ) -> None:
        state = self._history_states.get(identity)
        if state is None:
            return

        def _fetch() -> PagerSection | None:
            try:
                section = next(s for s in document.sections if s.identity == identity)
            except StopIteration:
                return None
            try:
                provider = history_provider_for_section(section)
            except Exception:
                return None
            if provider is None:
                return None
            try:
                return provider.load_version(section, ordinal)
            except Exception:
                return None

        loaded = await asyncio.to_thread(_fetch)
        if generation != self._history_generation or self.document is not document:
            return
        if loaded is None:
            return
        if len(state.body_cache) < _HISTORY_CACHE_LIMIT:
            state.body_cache[(ordinal, state.subject_id)] = loaded

    def _swap_active_section(
        self: Any, replacement: PagerSection, ordinal: int, generation: int
    ) -> None:
        if generation != self._history_generation:
            return
        try:
            index = next(
                i
                for i, s in enumerate(self.document.sections)
                if s.identity == replacement.identity
            )
        except StopIteration:
            return
        # Capture the top visible logical line before replacement.
        search_query = self._search.query if self._search.is_active else ""
        search_direction = self._search.direction
        anchor = self._capture_history_anchor(index)
        sections = list(self.document.sections)
        # Advance generation on selection/navigation/restoration.
        self._history_generation += 1
        state = self._history_states.get(replacement.identity)
        if state is not None:
            state.generation = self._history_generation
            pin = replacement.version_pin
            if pin is None:
                pin = live_pin_for_subject(state.subject_id)
            # Fold expansions do not survive a version swap.
            state.expanded_folds.clear()
            sticky = getattr(self, "_history_view_sticky", None)
            if sticky is not None:
                try:
                    pin = replace(pin, view=sticky)
                except Exception:
                    pass
            state.current_pin = pin
        sections[index] = replacement
        self.document = replace(self.document, sections=tuple(sections))
        self._body = None
        self._label_layer = None
        self._invalidate_body_layout()
        self._restore_history_anchor(index, replacement, anchor)
        if search_query:
            self._reapply_history_search(search_query, search_direction)
        elif self._search.is_active:
            self._search.refresh_styled_base()
        self._update_footer()
        self._update_subject()
        self._update_trail()
        self._schedule_syntax_preparation()
        # Re-apply the sticky diff view after the read swap lands, so the
        # diff render is never clobbered by the section installed above.
        if state is not None:
            current = state.current_pin
            if current is not None and getattr(current, "view", "read") == "diff":
                ensure = getattr(self, "_ensure_diff_view", None)
                if callable(ensure):
                    ensure(replacement.identity)

    def _capture_history_anchor(self: Any, section_index: int) -> tuple[int, int]:
        try:
            body = self._body
            scroll = self._body_scroll()
            if body is None:
                return (1, 0)
            section_offset = body.section_offsets[section_index]
            top = max(int(scroll.scroll_y) - section_offset, 0)
            rows = body.section_line_rows[section_index]
            line = 1
            for number, row in enumerate(rows, start=1):
                if row <= top:
                    line = number
                else:
                    break
            wrapped_offset = max(top - (rows[line - 1] if rows else 0), 0)
            return (line, wrapped_offset)
        except Exception:
            return (1, 0)

    def _restore_history_anchor(
        self: Any,
        section_index: int,
        replacement: PagerSection,
        anchor: tuple[int, int] | None = None,
    ) -> None:
        if anchor is None:
            anchor = (1, 0)
        line, wrapped_offset = anchor
        try:
            body = self._body
            if body is None:
                return
            rows = body.section_line_rows[section_index]
            if not rows:
                target = body.section_offsets[section_index]
            else:
                clamped_line = max(1, min(line, len(rows)))
                target = rows[clamped_line - 1] + wrapped_offset
            section_offset = body.section_offsets[section_index]
            absolute = section_offset + max(target - section_offset, 0)
            scroll = self._body_scroll()
            clamped = max(0, min(absolute, scroll.max_scroll_y))
            scroll.scroll_to(y=clamped, animate=False, immediate=True)
        except Exception:
            pass

    def _reapply_history_search(self: Any, query: str, direction: str) -> None:
        try:
            from sase.ace.tui.widgets._vim_search import (
                find_search_matches,
                select_search_match,
            )

            corpus = self.vim_search_corpus()
            if not corpus or not query:
                return
            spans = find_search_matches(corpus, query)
            if not spans:
                return
            self._search.corpus = corpus
            self._search.query = query
            self._search.match_spans = tuple(spans)
            selection = select_search_match(spans, 0, direction)  # type: ignore[arg-type]
            self._search.current_selection = selection
            self._search.refresh_styled_base()
        except Exception:
            pass

    def action_refresh(self: Any) -> None:  # type: ignore[override]
        try:
            section = self._current_section()
        except Exception:
            return super().action_refresh()  # type: ignore[misc]
        state = self._history_states.get(section.identity)
        if state is None:
            return super().action_refresh()  # type: ignore[misc]
        self._history_generation += 1
        generation = self._history_generation
        document = self.document

        async def _refresh_now() -> None:
            def _fetch() -> PagerSection | None:
                try:
                    provider = history_provider_for_section(section)
                except Exception:
                    return None
                if provider is None:
                    return None
                try:
                    refreshed = provider.refresh(section)
                except Exception:
                    return None
                return refreshed

            loaded = await asyncio.to_thread(_fetch)
            if generation != self._history_generation or self.document is not document:
                return
            if loaded is None:
                self.notify("Refresh failed — keeping current.", severity="warning")
                return
            self._swap_active_section(loaded, 0, generation)

        task = spawn_pump_free_task(
            self,
            _refresh_now(),
            name="sase-pager-history-refresh",
            registry_attr=_HISTORY_TASK_ATTR,
        )
        if task is None:
            self.notify("History refresh unavailable.", severity="warning")

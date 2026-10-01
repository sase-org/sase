"""Modeless history navigation for ``PagerScreen``.

``(``/``)`` step through visible committed versions, ``{`` selects the
first version and ``}`` follows now or its deletion tombstone. Worker
scheduling runs after first paint; service calls stay off the pump via
``asyncio.to_thread`` with generation guards so stale loads cannot
overwrite a newer view.
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import Any, cast

from sase.ace.tui.util.pump_tasks import spawn_pump_free_task
from sase.pager._labels import PagerLabelLayer
from sase.pager._layout import ComposedBody
from sase.pager.document import PagerDocument, PagerSection
from sase.pager.history.models import (
    SectionTimeState,
    VersionPin,
    live_pin_for_subject,
)
from sase.pager.history.provider import history_provider_for_section

_HISTORY_TASK_ATTR = "_pump_free_history_tasks"
_HISTORY_CACHE_LIMIT = 50


class PagerHistoryMixin:
    """Own per-section history state and version-step navigation."""

    document: PagerDocument
    _body: ComposedBody | None
    _body_width: int | None
    _label_layer: PagerLabelLayer | None
    _history_states: dict[str, SectionTimeState]
    _history_generation: int
    _history_pending: dict[str, str]
    _history_supported: dict[str, bool]
    _history_indexing: bool
    _history_coalesced: bool

    def _init_history_state(self: Any) -> None:
        self._history_states = {}
        self._history_generation = 0
        self._history_pending = {}
        self._history_supported = {}
        self._history_indexing = False
        self._history_coalesced = False

    def _bump_history_generation(self: Any) -> None:
        self._history_generation += 1

    def _rehydrate_history_pins(
        self: Any, pins: tuple[tuple[str, object], ...]
    ) -> None:
        self._history_generation += 1
        for identity, pin in pins:
            state = self._history_states.get(identity)
            if state is None:
                continue
            state.generation = self._history_generation
            if isinstance(pin, VersionPin):
                state.current_pin = pin

    def _start_history_discovery_after_paint(self: Any) -> None:
        def _schedule() -> None:
            task = spawn_pump_free_task(
                self,
                self._run_history_discovery(),
                name="sase-pager-history",
                registry_attr=_HISTORY_TASK_ATTR,
            )
            if task is None:
                self._history_coalesced = False

        try:
            self.call_after_refresh(_schedule)
        except Exception:
            self._history_coalesced = False

    def _history_state_for(self: Any, section: PagerSection) -> SectionTimeState | None:
        return self._history_states.get(section.identity)

    def _history_current_pin_ordinal(self: Any, section: PagerSection) -> int:
        state = self._history_states.get(section.identity)
        if state is not None and state.current_pin is not None:
            return state.current_pin.ordinal
        pin = section.version_pin
        if pin is not None:
            return pin.ordinal
        return 0

    async def _run_history_discovery(self: Any) -> None:
        if self._history_indexing:
            self._history_coalesced = True
            return
        self._history_indexing = True
        try:
            sections = list(self.document.sections)
            document = self.document
            generation = self._history_generation
            for section in sections:
                if (
                    generation != self._history_generation
                    or self.document is not document
                ):
                    return
                await self._index_one_section(section, document, generation)
            # Replay queued time intents now that metadata is ready.
            for identity, intent in list(self._history_pending.items()):
                if generation != self._history_generation:
                    return
                self._history_pending.pop(identity, None)
                if intent in ("older", "newer", "first", "now"):
                    await self._apply_step_intent(
                        identity, intent, document, generation
                    )
                elif intent == "toggle-diff":
                    toggle = getattr(self, "_toggle_diff_for_state", None)
                    if callable(toggle):
                        toggle(identity)
        finally:
            self._history_indexing = False
            if self._history_coalesced:
                self._history_coalesced = False
                self._start_history_discovery_after_paint()

    async def _index_one_section(
        self: Any, section: PagerSection, document: PagerDocument, generation: int
    ) -> None:
        def _load() -> tuple[object | None, dict[str, Any]]:
            try:
                provider = history_provider_for_section(section)
            except Exception:
                return None, {"versions": [], "error": "discovery failed"}
            if provider is None:
                return None, {"versions": [], "error": "unsupported"}
            try:
                timeline = provider.load_timeline(section)
            except Exception as exc:
                return provider, {"versions": [], "error": str(exc)}
            return provider, timeline if isinstance(timeline, dict) else {
                "versions": []
            }

        provider, timeline = await asyncio.to_thread(_load)
        if generation != self._history_generation or self.document is not document:
            return
        if provider is None:
            self._history_supported[section.identity] = False
            return
        self._history_supported[section.identity] = True
        from sase.memory.history.pager_provider import (
            dirty_now_from_timeline,
            is_deleted_row,
            newest_committed_row,
            visible_ordinals_for_timeline,
        )

        visible = visible_ordinals_for_timeline(timeline)
        versions = timeline.get("versions", ())
        rows = tuple(r for r in versions if isinstance(r, dict))
        newest = newest_committed_row(timeline)
        tombstone_ordinal: int | None = None
        if newest is not None and is_deleted_row(newest):
            tombstone_ordinal = int(newest.get("ordinal", 0) or 0)
        dirty = dirty_now_from_timeline(timeline)
        status = (
            "dirty-now" if dirty else ("tombstone" if tombstone_ordinal else "live")
        )
        live_snapshot = section
        state = self._history_states.get(section.identity)
        if state is None:
            state = SectionTimeState(
                provider_key=getattr(provider, "provider_key", "history"),
                subject_id=section.subject_ref or section.identity,
                scope_key="",
                live_section=live_snapshot,
            )
            self._history_states[section.identity] = state
        state.timeline = rows  # type: ignore[assignment]
        try:
            meta = dict(timeline)
            meta.pop("versions", None)
            state.timeline_meta = meta
        except Exception:
            pass
        state.visible_ordinals = visible
        state.status = status
        state.loading = False
        state.error = (
            timeline.get("error") if isinstance(timeline.get("error"), str) else None
        )  # type: ignore[attr-defined]
        if state.current_pin is None:
            section_pin = getattr(section, "version_pin", None)
            if isinstance(section_pin, VersionPin):
                # Honor the arrival pin (CLI `-A`/`-d` and feed links open
                # straight into a version or the diff view).
                state.current_pin = section_pin
            else:
                state.current_pin = live_pin_for_subject(state.subject_id)
        if isinstance(state.current_pin, VersionPin):
            # A pin to the newest ordinal on a now ≡ vN subject reads now:
            # canonicalize the arrival pin (CLI `-A`, feed links) to the
            # live section without pushing a trail entry.
            from sase.pager.history.moment import (
                canonical_ordinal,
                moment_for_state,
            )

            moment = moment_for_state(state)
            if moment is not None:
                pin = state.current_pin
                if canonical_ordinal(pin.ordinal, moment) != pin.ordinal:
                    live = live_pin_for_subject(state.subject_id)
                    try:
                        state.current_pin = replace(
                            live,
                            view=pin.view,
                            compare_base=pin.compare_base,
                            explicit_base=pin.explicit_base,
                        )
                    except Exception:
                        state.current_pin = live
        self._update_footer()
        self._update_subject()
        pin = state.current_pin
        if pin is not None and getattr(pin, "view", "read") == "diff":
            ensure = getattr(self, "_ensure_diff_view", None)
            if callable(ensure):
                ensure(section.identity)

    def action_history_older(self: Any) -> None:
        self._queue_or_apply_step("older")

    def action_history_newer(self: Any) -> None:
        self._queue_or_apply_step("newer")

    def action_history_first(self: Any) -> None:
        self._queue_or_apply_step("first")

    def action_history_now(self: Any) -> None:
        self._queue_or_apply_step("now")

    def _queue_or_apply_step(self: Any, intent: str) -> None:
        if not self.document.sections:
            return
        try:
            section = self._current_section()
        except Exception:
            return
        identity = section.identity
        if identity not in self._history_states:
            # Discovery in flight: store the last intent and execute on ready.
            # A confirmed unsupported section notifies instead of queuing.
            if self._history_supported.get(identity) is False:
                self.notify("No history for this section.", severity="information")
                return
            self._history_pending[identity] = intent
            self._start_history_discovery_after_paint()
            return
        document = self.document
        generation = self._history_generation
        task = spawn_pump_free_task(
            self,
            self._apply_step_intent(identity, intent, document, generation),
            name="sase-pager-history-step",
            registry_attr=_HISTORY_TASK_ATTR,
        )
        if task is None:
            self.notify("History worker unavailable.", severity="warning")

    async def _apply_step_intent(
        self: Any, identity: str, intent: str, document: PagerDocument, generation: int
    ) -> None:
        state = self._history_states.get(identity)
        if state is None:
            return
        from sase.pager.history.moment import (
            StepIntent,
            boundary_notice,
            moment_for_state,
            step_target,
        )

        moment = moment_for_state(state)
        if moment is None:
            self.notify("History load failed — keeping live.", severity="warning")
            return
        if moment.kind == "loading":
            self.notify("No committed versions.", severity="information")
            return
        if intent not in ("older", "newer", "first", "now"):
            return
        step = cast(StepIntent, intent)
        target = step_target(moment, step)
        if target is None:
            self.notify(boundary_notice(moment, step), severity="information")
            return
        await self._load_and_swap_version(identity, target, document, generation)

    def _history_current_pin_ordinal_for_identity(self: Any, identity: str) -> int:
        state = self._history_states.get(identity)
        if state is not None and state.current_pin is not None:
            return state.current_pin.ordinal
        for section in self.document.sections:
            if section.identity == identity and section.version_pin is not None:
                return section.version_pin.ordinal
        return 0

    async def _load_and_swap_version(
        self: Any, identity: str, ordinal: int, document: PagerDocument, generation: int
    ) -> None:
        state = self._history_states.get(identity)
        if state is None:
            return
        # A step onto the newest ordinal of a now ≡ vN subject reads the
        # live section instead of a byte-identical copy.
        preserve_view = False
        try:
            from sase.pager.history.moment import (
                canonical_ordinal,
                moment_for_state,
            )

            moment = moment_for_state(state)
            if moment is not None and canonical_ordinal(ordinal, moment) != ordinal:
                ordinal = canonical_ordinal(ordinal, moment)
                current = state.current_pin
                preserve_view = (
                    current is not None
                    and str(getattr(current, "view", "read") or "read") == "diff"
                )
        except Exception:
            pass
        cache_key = (ordinal, state.subject_id)
        cached = state.body_cache.get(cache_key)
        if cached is not None and isinstance(cached, PagerSection):
            self._swap_active_section(cached, ordinal, generation)
            self._prefetch_neighbours(identity, ordinal, document, generation)
            self._prefetch_parent_comparison(identity, ordinal, document, generation)
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
            self.notify("History load failed — keeping live.", severity="warning")
            return
        if preserve_view:
            # The canonicalized live swap keeps the pin's view and base.
            current = state.current_pin
            base_pin = loaded.version_pin
            if base_pin is None:
                base_pin = live_pin_for_subject(state.subject_id)
            if current is not None:
                try:
                    loaded = replace(
                        loaded,
                        version_pin=replace(
                            base_pin,
                            view=getattr(current, "view", "read"),
                            compare_base=getattr(current, "compare_base", None),
                            explicit_base=bool(
                                getattr(current, "explicit_base", False)
                            ),
                        ),
                    )
                except Exception:
                    pass
        if len(state.body_cache) >= _HISTORY_CACHE_LIMIT:
            state.body_cache.clear()
        state.body_cache[cache_key] = loaded
        self._swap_active_section(loaded, ordinal, generation)
        # Prefetch ±2 neighbours plus parent comparisons off the render path.
        self._prefetch_neighbours(identity, ordinal, document, generation)
        self._prefetch_parent_comparison(identity, ordinal, document, generation)

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
            comparison = state.comparison_cache.get((ordinal - 1, ordinal))
            if comparison is None:
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
            self._body_width = None
            self._ensure_body()
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
        self._body_width = None
        self._label_layer = None
        self._ensure_body()
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


__all__ = ["PagerHistoryMixin"]

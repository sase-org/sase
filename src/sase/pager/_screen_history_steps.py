"""History version stepping for ``PagerScreen``.

Owns the ``(``/``)``/``{``/``}`` intents, intent queuing while discovery
is in flight, and version loading with canonical live swaps. Prefetch,
swap, and mark rendering live in the sibling ``_screen_history_*``
modules.
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import Any, cast

from sase.ace.tui.util.pump_tasks import spawn_pump_free_task
from sase.pager.document import PagerDocument, PagerSection
from sase.pager.history.models import SectionTimeState, live_pin_for_subject
from sase.pager.history.provider import history_provider_for_section

__all__ = ["PagerHistoryStepsMixin"]

_HISTORY_TASK_ATTR = "_pump_free_history_tasks"
_HISTORY_CACHE_LIMIT = 50


class PagerHistoryStepsMixin:
    """Step through visible committed versions with generation guards."""

    document: PagerDocument
    _history_states: dict[str, SectionTimeState]
    _history_generation: int
    _history_pending: dict[str, str]
    _history_supported: dict[str, bool]

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

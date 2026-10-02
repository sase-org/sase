"""History discovery for ``PagerScreen``.

Schedules worker discovery after first paint and indexes one section at
a time off the pump with generation guards. Step application and
version swaps live in the sibling ``_screen_history_*`` modules.
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import Any

from sase.ace.tui.util.pump_tasks import spawn_pump_free_task
from sase.pager.document import PagerDocument, PagerSection
from sase.pager.history.models import (
    SectionTimeState,
    VersionPin,
    live_pin_for_subject,
)
from sase.pager.history.provider import history_provider_for_section

__all__ = ["PagerHistoryDiscoveryMixin"]

_HISTORY_TASK_ATTR = "_pump_free_history_tasks"


class PagerHistoryDiscoveryMixin:
    """Index per-section history timelines off the render pump."""

    document: PagerDocument
    _history_states: dict[str, SectionTimeState]
    _history_generation: int
    _history_pending: dict[str, str]
    _history_supported: dict[str, bool]
    _history_indexing: bool
    _history_coalesced: bool

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
        # Avoid reloading sections already present in history states
        # (e.g., back-restore to a previously indexed document).
        try:
            existing = self._history_states.get(section.identity)
            if existing is not None and tuple(getattr(existing, "timeline", ()) or ()):
                return
        except Exception:
            pass

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
        try:
            if not self.is_mounted:
                return
        except Exception:
            pass
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
            # live section without pushing a trail entry. The document
            # section is swapped to the live pin in place (the content is
            # byte-identical on a clean subject), so `yy`, links, and the
            # trail all read live.
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
                    try:
                        sections = list(self.document.sections)
                        for index, current in enumerate(sections):
                            if current.identity != section.identity:
                                continue
                            try:
                                live_section = replace(
                                    current,
                                    version_pin=state.current_pin,
                                )
                            except Exception:
                                break
                            sections[index] = live_section
                            try:
                                self.document = replace(
                                    self.document,
                                    sections=tuple(sections),
                                )
                            except Exception:
                                pass
                            try:
                                state.live_section = live_section
                            except Exception:
                                pass
                            break
                    except Exception:
                        pass
        self._update_footer()
        self._update_subject()
        pin = state.current_pin
        if pin is not None and getattr(pin, "view", "read") == "diff":
            ensure = getattr(self, "_ensure_diff_view", None)
            if callable(ensure):
                ensure(section.identity)

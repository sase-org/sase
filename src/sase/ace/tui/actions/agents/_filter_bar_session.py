"""Auto-hiding FilterBar editing session for the top-level Agents tab (sase-zf.4).

Mirrors the Artifacts Agent pane's ``AgentsQueryMixin``
(:mod:`sase.ace.tui.widgets.artifacts.agents_query`) but adapted to the live
tab's own state (``_agents``/``_agents_with_children``, no snapshot object)
and to a bar with no closed/resting display of its own -- see
:class:`~sase.ace.tui.widgets.agents_filter_bar.AgentsFilterBar`.

Per-keystroke preview never rebuilds the Rust corpus on the event loop: a
keystroke only does a cheap string-level ``canonical_query_for_profile()``
validation synchronously (to show a parse error immediately) and then
schedules an off-thread rebuild+evaluate
(:func:`~sase.ace.tui.models.agent_live_query_engine.build_agents_live_query_index` /
``evaluate_agents_live_query``), coalesced last-request-wins by generation
counter exactly like the existing content-search-index refresh worker
(``actions/agents/_loading_filter.py``). The visible agent list only
re-renders once that worker's result lands and still matches the live text,
so a burst of keystrokes never triggers more than one visible re-filter per
resolved worker.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import TYPE_CHECKING, Any

log = logging.getLogger(__name__)

if TYPE_CHECKING:
    from ...models import Agent
    from ...widgets.agents_filter_bar import AgentsFilterBar

_SAVE_QUERY_RE = re.compile(r"^#(\d)?(.*)$")


class AgentsFilterBarSessionMixin:
    """Own the Agents-tab FilterBar editing session and its live preview."""

    current_tab: str
    _agents: list[Agent]
    _agent_search_query: str
    _agent_search_query_seeded: bool
    _agents_filter_session_open: bool
    _agents_filter_restore_query: str | None
    _agents_filter_restore_focus: Any | None
    _agents_live_preview_query: str
    _agents_filter_query_error: str | None
    _agents_filter_match_count: tuple[int, int] | None
    _agents_filter_preview_generation: int
    _agents_filter_preview_task: asyncio.Task[None] | None

    if TYPE_CHECKING:

        def _refilter_agents(
            self,
            *,
            prior_pos: int | None = None,
            refresh_content_index: bool = True,
            previous_agents: list[Agent] | None = None,
            refresh_display: bool = True,
        ) -> None: ...

        def _schedule_agents_async_refresh(
            self, *, source: str = "unknown", **kwargs: Any
        ) -> None: ...

    def show_agents_filters(self) -> None:
        """Open and focus the auto-hiding Agents-tab filter bar."""
        from ...widgets.agents_filter_bar import AgentsFilterBar

        bar = self.query_one(AgentsFilterBar)  # type: ignore[attr-defined]
        if self._agents_filter_session_open:
            bar.focus_editor()
            return
        self._agents_filter_session_open = True
        self._agents_filter_restore_query = self._agent_search_query
        self._agents_filter_restore_focus = self.focused  # type: ignore[attr-defined]
        self._agents_live_preview_query = self._agent_search_query
        self._agents_filter_query_error = None
        from ...models.agent_live_query_engine import AgentsLiveQueryFacade

        cached = getattr(self, "_agents_live_query_facade", None)
        self._agents_live_preview_facade: AgentsLiveQueryFacade | None = cached  # type: ignore[attr-defined]
        self._agents_filter_match_count = None
        bar.open(self._agent_search_query)

    def _close_agents_filter_session(self) -> None:
        from ...widgets.agents_filter_bar import AgentsFilterBar

        prior_task = self._agents_filter_preview_task
        if prior_task is not None and not prior_task.done():
            prior_task.cancel()
        self._agents_filter_preview_task = None
        try:
            self.query_one(AgentsFilterBar).close()  # type: ignore[attr-defined]
        except Exception:
            pass
        self._agents_filter_session_open = False
        self._agents_filter_restore_query = None
        self._agents_live_preview_query = ""
        self._agents_filter_query_error = None
        self._agents_filter_match_count = None
        restore_focus = self._agents_filter_restore_focus
        self._agents_filter_restore_focus = None
        if restore_focus is not None:
            try:
                restore_focus.focus()
            except Exception:
                pass

    def on_agent_info_panel_filter_clicked(self, event: Any) -> None:
        event.stop()
        self.show_agents_filters()

    def on_agents_filter_bar_query_changed(self, event: Any) -> None:
        event.stop()
        if not self._agents_filter_session_open:
            return
        from ...widgets.agents_filter_bar import AgentsFilterBar

        text = event.text
        self._agents_live_preview_query = text
        bar = self.query_one(AgentsFilterBar)  # type: ignore[attr-defined]

        if _SAVE_QUERY_RE.match(text.strip()):
            bar.set_status(None, exact=False, error=None, coverage_label="save")
            return

        error = self._validate_agents_live_query(text)
        if error is not None:
            self._agents_filter_query_error = error
            bar.set_status(None, exact=False, error=error)
            return

        self._agents_filter_query_error = None
        self._schedule_agents_filter_preview_refresh(text)
        self._sync_agents_filter_bar_status()

    def on_agents_filter_bar_submitted(self, event: Any) -> None:
        event.stop()
        if not self._agents_filter_session_open:
            return
        text = event.text
        stripped = text.strip()
        save_match = _SAVE_QUERY_RE.match(stripped)
        if save_match:
            self._save_agents_filter_query_slot(text)
            return

        error = self._validate_agents_live_query(text)
        if error is not None:
            from ...widgets.agents_filter_bar import AgentsFilterBar

            self._agents_filter_query_error = error
            self.query_one(AgentsFilterBar).set_status(  # type: ignore[attr-defined]
                None, exact=False, error=error
            )
            self.notify(f"Invalid query: {error}", severity="error")  # type: ignore[attr-defined]
            return

        self._commit_agents_filter_query(text)
        self._close_agents_filter_session()

    def on_agents_filter_bar_dismissed(self, event: Any) -> None:
        event.stop()
        if not self._agents_filter_session_open:
            return
        self._close_agents_filter_session()
        self._refilter_agents(refresh_content_index=False)

    def _commit_agents_filter_query(self, source: str) -> None:
        old_source = self._agent_search_query
        old_canonical = self._agents_history_canonical(old_source)
        new_canonical = self._agents_history_canonical(source)
        record_transition = getattr(self, "_record_artifacts_query_transition", None)
        if callable(record_transition):
            record_transition(
                "agents-live",
                old_source=old_source,
                old_canonical=old_canonical,
                old_profile_digest=self._agents_live_profile_digest(),
                new_canonical=new_canonical,
            )
        self._agent_search_query = source
        self._agent_search_query_seeded = False
        # Session is still open here, so this refilter uses (and, on a
        # cache-miss race, self-heals) the *preview* facade below -- copy it
        # into the committed slot only after that resolves, so a stale
        # preview facade never sticks as the committed one.
        self._refilter_agents()
        self._agents_live_query_facade = getattr(  # type: ignore[attr-defined]
            self, "_agents_live_preview_facade", None
        )
        self._schedule_agents_async_refresh(source="filter")

    def _validate_agents_live_query(self, text: str) -> str | None:
        from ....query.profile_reference import canonical_query_for_profile
        from ....query.profile_reference_support import ProfileQueryError
        from ...models.agent_live_query_engine import (
            agents_live_query_profile,
            augment_error_with_legacy_hint,
        )

        if not text.strip():
            return None
        try:
            canonical_query_for_profile(text, agents_live_query_profile())
        except ProfileQueryError as exc:
            return augment_error_with_legacy_hint(str(exc), text)
        return None

    def _agents_history_canonical(self, source: str) -> str:
        from ....query.profile_reference import canonical_query_for_profile
        from ...models.agent_live_query_engine import agents_live_query_profile

        if not source.strip():
            return ""
        return canonical_query_for_profile(source, agents_live_query_profile())

    def _agents_live_profile_digest(self) -> str | None:
        from ...models.agent_live_query_engine import agents_live_query_profile

        return agents_live_query_profile().digest

    def _sync_agents_filter_bar_status(self) -> None:
        from ...widgets.agents_filter_bar import AgentsFilterBar

        try:
            bar = self.query_one(AgentsFilterBar)  # type: ignore[attr-defined]
        except Exception:
            return
        if self._agents_filter_query_error is not None:
            bar.set_status(None, exact=False, error=self._agents_filter_query_error)
            return
        if not self._agents_live_preview_query.strip():
            bar.set_status(None, exact=False, error=None, coverage_label="preview")
            return
        count = self._agents_filter_match_count
        match_count = count[0] if count is not None else None
        bar.set_status(match_count, exact=False, error=None, coverage_label="preview")

    def _schedule_agents_filter_preview_refresh(self, query: str) -> None:
        generation = self._agents_filter_preview_generation + 1
        self._agents_filter_preview_generation = generation
        prior_task = self._agents_filter_preview_task
        if prior_task is not None and not prior_task.done():
            prior_task.cancel()
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self._agents_filter_preview_task = loop.create_task(
            self._run_agents_filter_preview_refresh(query=query, generation=generation)
        )

    async def _run_agents_filter_preview_refresh(
        self,
        *,
        query: str,
        generation: int,
    ) -> None:
        from ...models.agent_live_query_engine import (
            build_agents_live_query_index,
            evaluate_agents_live_query,
        )

        agents = list(getattr(self, "_agents_with_children", []) or [])
        content_index = getattr(self, "_agent_content_search_index", None)
        unread_agent_ids = getattr(self, "_unread_completed_agent_ids", ())

        def _build_and_evaluate() -> tuple[Any, str | None]:
            index = build_agents_live_query_index(
                agents,
                generation=generation,
                content_index=content_index,
                unread_agent_ids=unread_agent_ids,
            )
            return evaluate_agents_live_query(query, index)

        try:
            facade, error = await asyncio.to_thread(_build_and_evaluate)
        except Exception:
            log.debug("agents filter preview refresh failed", exc_info=True)
            return

        if generation != self._agents_filter_preview_generation:
            return
        if not self._agents_filter_session_open:
            return
        if query != (self._agents_live_preview_query or ""):
            return

        self._agents_filter_query_error = error
        if facade is not None:
            self._agents_live_preview_facade = facade  # type: ignore[attr-defined]
        self._refilter_agents(refresh_content_index=False)
        self._sync_agents_filter_bar_status()

    def _save_agents_filter_query_slot(self, text: str) -> None:
        from ....saved_queries import (
            delete_query,
            find_slot_for_query,
            get_next_available_slot,
            load_saved_queries,
            save_query,
        )

        match = _SAVE_QUERY_RE.match(text.strip())
        if match is None:
            return
        pane_id = "agents-live"
        slot_specified = match.group(1)
        query_part = match.group(2).strip()
        if not query_part:
            if slot_specified:
                if delete_query(pane_id, slot_specified):
                    self._invalidate_saved_query_cache()
                    self.notify(f"Deleted query from slot {slot_specified}")  # type: ignore[attr-defined]
                else:
                    self.notify("Failed to delete query", severity="error")  # type: ignore[attr-defined]
            else:
                self.notify("No slot specified to delete", severity="warning")  # type: ignore[attr-defined]
            return

        error = self._validate_agents_live_query(query_part)
        if error is not None:
            self.notify(f"Invalid query: {error}", severity="error")  # type: ignore[attr-defined]
            return
        canonical = self._agents_history_canonical(query_part)

        existing_slot = find_slot_for_query(pane_id, canonical)
        if slot_specified:
            slot = slot_specified
        else:
            if existing_slot is not None:
                self.notify(f"Query already saved in slot {existing_slot}")  # type: ignore[attr-defined]
                return
            slot = get_next_available_slot(load_saved_queries(pane_id))
            if slot is None:
                self.notify("All 10 slots are full", severity="warning")  # type: ignore[attr-defined]
                return

        if save_query(pane_id, slot, query_part, canonical):
            self._invalidate_saved_query_cache()
            if existing_slot is not None and existing_slot != slot:
                self.notify(f"Moved query from slot {existing_slot} to slot {slot}")  # type: ignore[attr-defined]
            else:
                self.notify(f"Saved to slot {slot}: {canonical}")  # type: ignore[attr-defined]
        else:
            self.notify("Failed to save query", severity="error")  # type: ignore[attr-defined]

    def _invalidate_saved_query_cache(self) -> None:
        invalidate = getattr(
            getattr(self, "app", self),
            "_invalidate_saved_queries_cache",
            None,
        )
        if callable(invalidate):
            invalidate()

    # -- Query history (``^``/``_`` while the bar is open) -----------------

    def query_history_record(self) -> object:
        """Return the Agents-tab live-preview query as a history record."""
        from ....query_record import QueryRecord

        source = (
            self._agents_live_preview_query
            if self._agents_filter_session_open
            else self._agent_search_query
        )
        return QueryRecord(
            source=source,
            canonical=self._agents_history_canonical(source),
            profile_digest=self._agents_live_profile_digest(),
        )

    def apply_query_history_record(self, record: object) -> bool:
        """Replace the in-progress live edit with a stored history entry."""
        source = getattr(record, "source", "")
        try:
            canonical = self._agents_history_canonical(source)
        except Exception:
            return False
        if canonical != getattr(record, "canonical", None):
            return False
        if not self._agents_filter_session_open:
            return False
        from ...widgets.agents_filter_bar import AgentsFilterBar

        bar = self.query_one(AgentsFilterBar)  # type: ignore[attr-defined]
        bar.set_query(source)
        self._agents_live_preview_query = source
        error = self._validate_agents_live_query(source)
        if error is not None:
            self._agents_filter_query_error = error
            bar.set_status(None, exact=False, error=error)
        else:
            self._agents_filter_query_error = None
            self._schedule_agents_filter_preview_refresh(source)
            self._sync_agents_filter_bar_status()
        return True


__all__ = ["AgentsFilterBarSessionMixin"]

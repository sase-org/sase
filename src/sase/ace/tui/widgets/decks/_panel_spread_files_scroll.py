"""Private implementation pieces for DeckPanel spread state."""

from __future__ import annotations


from typing import Any

from textual.containers import VerticalScroll

from ._panel_spread_cards import PanelSpreadCardsMixin
from .model import DeckId


class PanelSpreadFilesScrollMixin(PanelSpreadCardsMixin):
    """Navigate and confirm Files deck scroll positions."""

    def _clear_files_pending_scroll(self) -> None:
        """Drop any outstanding Files spread navigation without moving scroll."""
        try:
            self._files_pending_scroll_index = None
        except Exception:
            pass
        try:
            self._files_scroll_retry = 0
        except Exception:
            pass
        try:
            self._files_scroll_confirmed = False
        except Exception:
            pass

    def _cycle_files_spread(self, direction: int) -> None:
        try:
            file_view = self.file_view  # type: ignore[attr-defined]
            slots = list(getattr(file_view, "_file_list", []))
            if len(slots) <= 1:
                return
            # A pending mode transition may still have a deferred restore
            # queued for the old page. Let this navigation own the scroll.
            # A pending navigation owns its target: chain from it so rapid
            # Ctrl-J presses supersede instead of recomputing from stale scroll.
            try:
                pending_current = getattr(self, "_files_pending_scroll_index", None)
            except Exception:
                pending_current = None
            try:
                if pending_current is not None:
                    current = int(pending_current)
                else:
                    current = self._files_spread_active_index()
            except Exception:
                current = self._files_spread_active_index()
            self._files_transition_generation += 1
            generation = self._files_transition_generation
            nxt = (current + direction) % len(slots)
            self._files_pending_scroll_index = nxt
            self._files_scroll_retry = 0
            self._files_scroll_confirmed = False
            spread_view = self.files_spread_view  # type: ignore[attr-defined]
            spread_view.enable_section_layout_reserve()
            # Update the hidden paged index silently so E/clipboard follow.
            try:
                file_view.set_current_index_silent(nxt)
            except Exception:
                pass
            self._file_index = nxt  # type: ignore[attr-defined]
            try:
                self.refresh_chrome()  # type: ignore[attr-defined]
            except Exception:
                pass
            # Enabling the reserve changes the scroll extent during layout.
            # Resolve the anchor only after that layout, then confirm the
            # requested position survived the refresh before considering the
            # navigation complete.
            self._schedule_files_scroll(nxt, generation, 0)
        except Exception:
            pass

    def _schedule_files_scroll(self, index: int, generation: int, attempt: int) -> None:
        try:
            live_generation = int(getattr(self, "_files_transition_generation", -1))
        except Exception:
            return
        if generation != live_generation:
            return
        try:
            pending = getattr(self, "_files_pending_scroll_index", None)
        except Exception:
            pending = None
        if pending is None:
            try:
                self._files_pending_scroll_index = int(index)
            except Exception:
                return
        elif int(pending) != int(index):
            return
        try:
            retries = int(getattr(self, "_files_scroll_retry", 0) or 0)
        except Exception:
            retries = 0
        if retries >= 8 or int(attempt) >= 8:
            return
        try:
            self.call_after_refresh(  # type: ignore[attr-defined]
                lambda: self._apply_files_scroll(index, generation, attempt)
            )
        except Exception:
            pass

    def _request_files_scroll_y(self, row: int) -> bool:
        """Apply one scroll request immediately so layout cannot drop it."""
        try:
            scroll = self.query_one(  # type: ignore[attr-defined]
                f"#agent-deck-panel-{self._panel_index}-files-scroll",
                VerticalScroll,
            )
        except Exception:
            return False
        try:
            try:
                scroll.scroll_to(y=row, animate=False, immediate=True)
            except TypeError:
                scroll.scroll_to(y=row, animate=False)
        except Exception:
            return False
        try:
            self.call_after_refresh(  # type: ignore[attr-defined]
                lambda: self._sync_files_scrollbar(scroll)
            )
        except Exception:
            pass
        return True

    def _sync_files_scrollbar(self, scroll: Any) -> None:
        """Sync the scrollbar position after an immediate scroll request."""
        try:
            from .document_transitions_capture import sync_scrollbar_position

            sync_scrollbar_position(scroll)
        except Exception:
            pass

    def _on_files_scroll_extent(self, _old: Any, _new: Any) -> None:
        """Resume stalled Files navigation when the scroll extent changes.

        The retry chain is bounded, so a pending jump can run out of hops
        while the scroll extent is still short of its anchor. Anchor
        publishes already re-arm the chain; a later extent change (for
        example the trailing reserve landing several layouts after the
        last publish) must re-arm it too, or the jump stalls forever.
        """
        try:
            pending = getattr(self, "_files_pending_scroll_index", None)
        except Exception:
            return
        if pending is None:
            return
        self._reschedule_files_scroll_after_layout()

    def _reschedule_files_scroll_after_layout(self) -> None:
        """Resume pending Files navigation after anchors/reserve publish."""
        try:
            pending = getattr(self, "_files_pending_scroll_index", None)
        except Exception:
            return
        if pending is None:
            return
        try:
            generation = int(getattr(self, "_files_transition_generation", -1))
        except Exception:
            return
        try:
            spread = bool(self.is_spread(DeckId.FILES))  # type: ignore[attr-defined]
        except Exception:
            spread = False
        if not spread:
            return
        try:
            deck = getattr(self, "_deck", None)
        except Exception:
            deck = None
        if deck is not DeckId.FILES:
            return
        try:
            self._files_scroll_retry = 0
        except Exception:
            pass
        try:
            self._files_scroll_confirmed = False
        except Exception:
            pass
        try:
            pending_index = int(pending)
        except Exception:
            return
        self._schedule_files_scroll(pending_index, generation, 0)

    def _apply_files_scroll(self, index: int, generation: int, attempt: int) -> None:
        try:
            live_generation = int(getattr(self, "_files_transition_generation", -1))
        except Exception:
            return
        if generation != live_generation:
            return
        try:
            pending = getattr(self, "_files_pending_scroll_index", None)
        except Exception:
            pending = None
        if pending is None or int(pending) != int(index):
            return
        try:
            mounted = bool(getattr(self, "is_mounted", True))
        except Exception:
            mounted = True
        if not mounted:
            self._clear_files_pending_scroll()
            return
        row = self._files_anchor_row(index)
        try:
            scroll = self.query_one(  # type: ignore[attr-defined]
                f"#agent-deck-panel-{self._panel_index}-files-scroll",
                VerticalScroll,
            )
            max_scroll_y = int(scroll.max_scroll_y)
        except Exception:
            try:
                retries = int(getattr(self, "_files_scroll_retry", 0) or 0)
            except Exception:
                retries = 0
            if retries < 8:
                try:
                    self._files_scroll_retry = retries + 1
                except Exception:
                    pass
                self._schedule_files_scroll(index, generation, attempt + 1)
            return
        if row is None or max_scroll_y < row:
            try:
                self._files_scroll_confirmed = False
            except Exception:
                pass
            try:
                retries = int(getattr(self, "_files_scroll_retry", 0) or 0)
            except Exception:
                retries = 0
            if retries < 8:
                try:
                    self._files_scroll_retry = retries + 1
                except Exception:
                    pass
                self._schedule_files_scroll(index, generation, attempt + 1)
            return
        if not self._request_files_scroll_y(row):
            try:
                retries = int(getattr(self, "_files_scroll_retry", 0) or 0)
            except Exception:
                retries = 0
            if retries < 8:
                try:
                    self._files_scroll_retry = retries + 1
                except Exception:
                    pass
                self._schedule_files_scroll(index, generation, attempt + 1)
            return
        try:
            self.call_after_refresh(  # type: ignore[attr-defined]
                lambda: self._confirm_files_scroll(index, row, generation, attempt)
            )
        except Exception:
            pass

    def _confirm_files_scroll(
        self, index: int, row: int, generation: int, attempt: int
    ) -> None:
        try:
            live_generation = int(getattr(self, "_files_transition_generation", -1))
        except Exception:
            return
        if generation != live_generation:
            return
        try:
            pending = getattr(self, "_files_pending_scroll_index", None)
        except Exception:
            pending = None
        if pending is None or int(pending) != int(index):
            return
        live_row = self._files_anchor_row(index)
        try:
            scroll = self.query_one(  # type: ignore[attr-defined]
                f"#agent-deck-panel-{self._panel_index}-files-scroll",
                VerticalScroll,
            )
            landed = (
                live_row == row
                and int(scroll.scroll_y) == row
                and int(scroll.max_scroll_y) >= row
            )
        except Exception:
            landed = False
        if landed:
            try:
                confirmed = bool(getattr(self, "_files_scroll_confirmed", False))
            except Exception:
                confirmed = False
            if confirmed:
                self._clear_files_pending_scroll()
                return
            try:
                self._files_scroll_confirmed = True
            except Exception:
                pass
            self._schedule_files_scroll(index, generation, attempt)
            return
        try:
            self._files_scroll_confirmed = False
        except Exception:
            pass
        try:
            retries = int(getattr(self, "_files_scroll_retry", 0) or 0)
        except Exception:
            retries = 0
        if retries < 8:
            try:
                self._files_scroll_retry = retries + 1
            except Exception:
                pass
            self._schedule_files_scroll(index, generation, attempt + 1)

"""Private implementation pieces for DeckPanel spread state."""

from __future__ import annotations


from typing import Any

from textual.containers import VerticalScroll

from ...agent_decks_settings import agent_decks_settings_for
from .card_documents import CARD_DOCUMENT_DECKS
from .model import DeckId, DeckView, RenderMode
from .render_mode import decide_render_mode, measure_card_rows, spread_budget_rows
from .view_policy import forced_deck_mode


class PanelSpreadDecisionMixin:
    """Manage per-panel render mode decisions and their measurement state."""

    _panel_index: int
    _deck: DeckId
    _render_mode: dict[DeckId, RenderMode]
    _mode_subject: dict[DeckId, object]
    _files_probe_pages: tuple[Any, ...]
    _files_probe_total: int | None
    _files_probe_exceeded: bool
    _files_probe_bound: float
    _files_probe_subject: object | None
    _files_probe_slots: tuple[str, ...]
    _files_probe_agent: Any | None
    _files_pending_probe: Any | None
    _files_probe_complete: bool
    _files_media_toast_armed: bool
    _resize_decision_pending: bool
    _one_shot_spread_card: str | None
    _files_transition_generation: int
    _files_pending_scroll_index: int | None
    _files_scroll_retry: int
    _files_scroll_confirmed: bool
    _deck_mode_measured: bool
    _deck_mode_retry: int
    _deck_mode_retry_pending: bool

    def _init_spread_state(self) -> None:
        self._render_mode = dict.fromkeys(CARD_DOCUMENT_DECKS, RenderMode.PAGED)
        self._render_mode[DeckId.FILES] = RenderMode.PAGED
        self._mode_subject = {}
        self._files_probe_pages = ()
        self._files_probe_total = None
        self._files_probe_exceeded = False
        self._files_probe_bound = 0.0
        self._files_probe_subject = None
        self._files_probe_slots = ()
        self._files_probe_agent = None
        self._files_pending_probe = None
        # Whether the stored Files pages were read completely (complete
        # probe, or a bounded probe that never exceeded its bound and found
        # no media). Only complete pages may render a fixed spread.
        self._files_probe_complete = False
        # Set by a user-initiated fixed-spread change; consumed by the first
        # media-blocked probe result that follows it (for the D8 toast).
        self._files_media_toast_armed = False
        self._resize_decision_pending = False
        self._one_shot_spread_card = None
        self._files_transition_generation = 0
        self._files_pending_scroll_index: int | None = None
        self._files_scroll_retry = 0
        self._files_scroll_confirmed = False
        self._deck_mode_measured = False
        self._deck_mode_retry = 0
        self._deck_mode_retry_pending = False

    def _spread_settings_max_screens(self) -> float:
        try:
            return float(agent_decks_settings_for(self).spread_max_screens)
        except Exception:
            return 1.5

    def _spread_viewport(self, deck: DeckId) -> tuple[int, int]:
        """Return ``(rows, width)`` for ``deck``; zeros when not laid out."""
        try:
            scroll = self.query_one(  # type: ignore[attr-defined]
                f"#agent-deck-panel-{self._panel_index}-{deck.value}-scroll",
                VerticalScroll,
            )
        except Exception:
            return (0, 0)
        try:
            region = scroll.scrollable_content_region
            rows = int(region.height)
            width = int(region.width)
        except Exception:
            return (0, 0)
        if rows <= 0 or width <= 0:
            return (0, 0)
        return (rows, max(1, width))

    def _spread_console(self) -> tuple[Any, Any] | None:
        try:
            app = self.app  # type: ignore[attr-defined]
            console = app.console
            options = console.options
            return (console, options)
        except Exception:
            return None

    def is_spread(self, deck: DeckId) -> bool:
        """Return whether ``deck`` currently renders spread."""
        try:
            return self._render_mode.get(deck) is RenderMode.SPREAD
        except Exception:
            return False

    def _decide_document_mode(
        self,
        deck: DeckId,
        document: Any,
        *,
        same_subject: bool,
        policy: DeckView | None = None,
    ) -> RenderMode:
        """Decide the spread/paged mode for any card-document ``deck``."""
        if policy is None:
            try:
                policy = self.view_policy(deck)  # type: ignore[attr-defined]
            except Exception:
                policy = DeckView.AUTO
        previous = self._render_mode.get(deck, RenderMode.PAGED)
        card_count = len(document.cards)
        try:
            forced = forced_deck_mode(policy, card_count)
        except Exception:
            forced = None
        if forced is not None:
            self._mark_deck_mode_measured()
            return forced
        spread_max = self._spread_settings_max_screens()
        if spread_max <= 0:
            self._mark_deck_mode_measured()
            return RenderMode.PAGED
        rows, width = self._spread_viewport(deck)
        if rows <= 0 or width <= 0:
            self._deck_mode_measured = False
            self._schedule_document_mode_redecision(deck)
            return previous
        self._mark_deck_mode_measured()
        budget = spread_budget_rows(spread_max, rows)
        pair = self._spread_console()
        if pair is None:
            return decide_render_mode(
                card_count=card_count,
                has_solo_card=False,
                total_rows=None,
                viewport_rows=rows,
                spread_max_screens=spread_max,
                previous=previous,
                same_subject=same_subject,
            )
        console, options = pair
        try:
            total = measure_card_rows(
                document.cards,
                deck=deck,
                width=width,
                console=console,
                options=options,
                budget=budget,
                cache_key_prefix=document.digest,
            )
        except Exception:
            total = None
        return decide_render_mode(
            card_count=card_count,
            has_solo_card=False,
            total_rows=total,
            viewport_rows=rows,
            spread_max_screens=spread_max,
            previous=previous,
            same_subject=same_subject,
        )

    def _mark_deck_mode_measured(self) -> None:
        self._deck_mode_measured = True
        self._deck_mode_retry = 0
        self._deck_mode_retry_pending = False

    def _schedule_document_mode_redecision(self, deck: DeckId) -> None:
        """Retry an unmeasured AUTO decision after layout settles."""
        if bool(getattr(self, "_deck_mode_measured", False)):
            return
        if bool(getattr(self, "_deck_mode_retry_pending", False)):
            return
        try:
            retries = int(getattr(self, "_deck_mode_retry", 0) or 0)
        except Exception:
            retries = 0
        if retries >= 8:
            return
        self._deck_mode_retry_pending = True
        try:
            self.call_after_refresh(  # type: ignore[attr-defined]
                lambda: self._retry_document_mode(deck)
            )
        except Exception:
            self._deck_mode_retry_pending = False

    def _retry_document_mode(self, deck: DeckId) -> None:
        self._deck_mode_retry_pending = False
        try:
            self._deck_mode_retry = int(getattr(self, "_deck_mode_retry", 0) or 0) + 1
        except Exception:
            self._deck_mode_retry = 1
        try:
            self._refresh_document_mode_for_shown(deck)  # type: ignore[attr-defined]
        except Exception:
            pass
        if not bool(getattr(self, "_deck_mode_measured", False)):
            self._schedule_document_mode_redecision(deck)

    def _decide_main_mode(
        self,
        document: Any,
        *,
        same_subject: bool,
    ) -> RenderMode:
        return self._decide_document_mode(
            DeckId.MAIN, document, same_subject=same_subject
        )

    def _decide_files_mode(
        self,
        *,
        same_subject: bool,
        total_rows: int | None,
        has_solo: bool,
        card_count: int,
    ) -> RenderMode:
        previous = self._render_mode.get(DeckId.FILES, RenderMode.PAGED)
        # A one-card deck always spreads, even under a fixed policy (D1).
        if card_count <= 1:
            return RenderMode.SPREAD
        try:
            policy = self.view_policy(DeckId.FILES)  # type: ignore[attr-defined]
        except Exception:
            policy = DeckView.AUTO
        if policy is DeckView.PAGE_CARDS:
            return RenderMode.PAGED
        if policy is DeckView.SPREAD:
            if has_solo:
                return RenderMode.PAGED
            # Fixed spread needs complete pages; otherwise stay paged
            # until the complete probe lands.
            try:
                complete = bool(self._files_probe_complete)
            except Exception:
                complete = False
            return RenderMode.SPREAD if complete else RenderMode.PAGED
        spread_max = self._spread_settings_max_screens()
        rows, _width = self._spread_viewport(DeckId.FILES)
        if rows <= 0:
            return previous
        return decide_render_mode(
            card_count=card_count,
            has_solo_card=has_solo,
            total_rows=total_rows,
            viewport_rows=rows,
            spread_max_screens=spread_max,
            previous=previous,
            same_subject=same_subject,
        )

    def _recompute_files_rows(self, width: int) -> int | None:
        """Recompute Files rows from stored page texts without I/O."""
        from ..file_panel._spread_probe import estimate_wrapped_rows

        pages = self._files_probe_pages
        if not pages:
            return None
        total = 0
        for index, page in enumerate(pages):
            header_rows = 2
            total += header_rows + estimate_wrapped_rows(
                page.text, width=max(1, width), gutter=0
            )
            if index > 0:
                total += 2
        return total

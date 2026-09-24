"""Spread versus paged mode state for ``DeckPanel``."""

from __future__ import annotations

from typing import Any

from textual.containers import VerticalScroll

from ...agent_decks_settings import agent_decks_settings_for
from .model import DeckId, RenderMode, cycle_card_id
from .render_mode import (
    decide_render_mode,
    measure_main_rows,
    spread_budget_rows,
)


class DeckPanelSpreadMixin:
    """Per-panel, per-deck spread/paged decision and scroll tracking."""

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
    _resize_decision_pending: bool
    _one_shot_spread_card: str | None

    def _init_spread_state(self) -> None:
        self._render_mode = {
            DeckId.MAIN: RenderMode.PAGED,
            DeckId.FILES: RenderMode.PAGED,
        }
        self._mode_subject = {}
        self._files_probe_pages = ()
        self._files_probe_total = None
        self._files_probe_exceeded = False
        self._files_probe_bound = 0.0
        self._files_probe_subject = None
        self._files_probe_slots = ()
        self._files_probe_agent = None
        self._resize_decision_pending = False
        self._one_shot_spread_card = None

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

    # -- Main decisions -------------------------------------------------

    def _decide_main_mode(
        self,
        document: Any,
        *,
        same_subject: bool,
    ) -> RenderMode:
        previous = self._render_mode.get(DeckId.MAIN, RenderMode.PAGED)
        card_count = len(document.cards)
        spread_max = self._spread_settings_max_screens()
        if card_count <= 1:
            return RenderMode.SPREAD
        if spread_max <= 0:
            return RenderMode.PAGED
        rows, width = self._spread_viewport(DeckId.MAIN)
        if rows <= 0 or width <= 0:
            return previous
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
            total = measure_main_rows(
                document.cards,
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

    # -- Files decisions ------------------------------------------------

    def _decide_files_mode(
        self,
        *,
        same_subject: bool,
        total_rows: int | None,
        has_solo: bool,
        card_count: int,
    ) -> RenderMode:
        previous = self._render_mode.get(DeckId.FILES, RenderMode.PAGED)
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

    # -- Scroll-derived active cards ------------------------------------

    def _main_spread_active(self) -> str | None:
        try:
            view = self.main_view  # type: ignore[attr-defined]
            if view.render_mode is not RenderMode.SPREAD:
                return getattr(self, "_main_active_card", None)
            return view.spread_active_card()
        except Exception:
            return getattr(self, "_main_active_card", None)

    def _files_spread_active_index(self) -> int:
        try:
            spread_view = self.files_spread_view  # type: ignore[attr-defined]
            pages = list(spread_view.page_slots)
            if not pages:
                file_view = self.file_view  # type: ignore[attr-defined]
                return int(getattr(file_view, "_current_file_index", 0))
            width = self._spread_viewport(DeckId.FILES)[1]
            if width <= 0:
                file_view = self.file_view  # type: ignore[attr-defined]
                return int(getattr(file_view, "_current_file_index", 0))
            pairs = spread_view.card_anchor_rows(width=width)
            if not pairs:
                return 0
            scroll = self.query_one(  # type: ignore[attr-defined]
                f"#agent-deck-panel-{self._panel_index}-files-scroll",
                VerticalScroll,
            )
            scroll_y = int(scroll.scroll_y)
            active_index = 0
            for cid, row in sorted(pairs, key=lambda item: item[1]):
                if row <= scroll_y:
                    try:
                        if cid.startswith("file-"):
                            active_index = int(cid[len("file-") :])
                    except Exception:
                        pass
                else:
                    break
            # First page anchor is implicit row 0; already covered by index 0.
            file_view = self.file_view  # type: ignore[attr-defined]
            count = len(getattr(file_view, "_file_list", pages))
            return max(0, min(active_index, max(0, count - 1)))
        except Exception:
            try:
                file_view = self.file_view  # type: ignore[attr-defined]
                return int(getattr(file_view, "_current_file_index", 0))
            except Exception:
                return 0

    def _files_body_start(self, index: int) -> int | None:
        if index <= 0:
            return 0
        try:
            spread_view = self.files_spread_view  # type: ignore[attr-defined]
            width = self._spread_viewport(DeckId.FILES)[1]
            if width <= 0:
                return None
            pairs = spread_view.card_anchor_rows(width=width)
            if not pairs:
                return None
            want = f"file-{index}"
            for cid, row in pairs:
                if cid == want:
                    return row + 1
            return None
        except Exception:
            return None

    # -- Main spread cycling --------------------------------------------

    def _cycle_main_spread(self, direction: int) -> str | None:
        try:
            document = self._main_document  # type: ignore[attr-defined]
        except Exception:
            return None
        ids = [card.card_id for card in document.cards]
        if not ids:
            return None
        active = self._main_spread_active()
        next_id = cycle_card_id(ids, active, direction)
        if next_id is None:
            return None
        try:
            view = self.main_view  # type: ignore[attr-defined]
            shown = view.scroll_to_card(next_id)
        except Exception:
            return None
        if shown is None:
            return None
        self._main_active_card = shown  # type: ignore[attr-defined]
        try:
            self.refresh_chrome()  # type: ignore[attr-defined]
        except Exception:
            pass
        return shown

    def _cycle_files_spread(self, direction: int) -> None:
        try:
            file_view = self.file_view  # type: ignore[attr-defined]
            slots = list(getattr(file_view, "_file_list", []))
            if len(slots) <= 1:
                return
            current = self._files_spread_active_index()
            nxt = (current + direction) % len(slots)
            spread_view = self.files_spread_view  # type: ignore[attr-defined]
            spread_view.enable_section_layout_reserve()
            row = self._files_body_start(nxt)
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
            if row is None:
                # Anchors not ready: retry bounded after refresh.
                try:
                    self.call_after_refresh(  # type: ignore[attr-defined]
                        lambda: self._retry_files_scroll(nxt, 0)
                    )
                except Exception:
                    pass
                return
            try:
                scroll = self.query_one(  # type: ignore[attr-defined]
                    f"#agent-deck-panel-{self._panel_index}-files-scroll",
                    VerticalScroll,
                )
                scroll.scroll_to(y=row, animate=False)
            except Exception:
                pass
        except Exception:
            pass

    def _retry_files_scroll(self, index: int, attempt: int) -> None:
        if attempt >= 3:
            return
        row = self._files_body_start(index)
        if row is None:
            try:
                self.call_after_refresh(  # type: ignore[attr-defined]
                    lambda: self._retry_files_scroll(index, attempt + 1)
                )
            except Exception:
                pass
            return
        try:
            scroll = self.query_one(  # type: ignore[attr-defined]
                f"#agent-deck-panel-{self._panel_index}-files-scroll",
                VerticalScroll,
            )
            scroll.scroll_to(y=row, animate=False)
        except Exception:
            pass


__all__ = ["DeckPanelSpreadMixin"]

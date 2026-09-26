"""Card cycling and main-document push for ``DeckPanel``.

Extracted from ``panel.py`` so the panel shell stays under the line-count
gate. All cross-deck collaborators are reached through ``self``; this module
imports only public names and never a ``_``-prefixed symbol.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .main_document import MainDeckDocument
from .model import DeckId, RenderMode, cycle_card_id


class DeckPanelNavigationMixin:
    """Cycle cards and push Main documents for a deck panel."""

    _deck: DeckId
    _main_document: MainDeckDocument
    _main_active_card: str | None
    _render_mode: dict[DeckId, RenderMode]
    _mode_subject: dict[DeckId, object]

    if TYPE_CHECKING:

        def __getattr__(self, name: str) -> Any: ...

    def cycle_card(self, direction: int) -> str | None:
        """Cycle cards in the active deck; return the new Main card id."""
        if self._deck is DeckId.MAIN:
            if self.is_spread(DeckId.MAIN):
                return self._cycle_main_spread(direction)
            ids = [card.card_id for card in self._main_document.cards]
            try:
                active = self.main_view.active_card_id
            except Exception:
                active = self._main_active_card
            next_id = cycle_card_id(ids, active, direction)
            if next_id is None:
                return None
            try:
                block_mode = self._block_mode_for_card(self._main_document, next_id)
            except Exception:
                block_mode = None
            try:
                try:
                    shown = self.main_view.show_card(next_id, block_mode=block_mode)
                except TypeError:
                    shown = self.main_view.show_card(next_id)
            except Exception:
                return None
            if shown is None:
                return None
            self._main_active_card = shown
            self.refresh_chrome()
            try:
                self._sync_block_navigable()
            except Exception:
                pass
            try:
                self._sync_block_rail()  # type: ignore[attr-defined]
            except Exception:
                pass
            return shown
        if self._deck is DeckId.FILES:
            if self.is_spread(DeckId.FILES):
                self._cycle_files_spread(direction)
                return None
            try:
                view = self.file_view
                if direction >= 0:
                    view.next_file()
                else:
                    view.prev_file()
            except Exception:
                pass
            try:
                self.refresh_chrome()
            except Exception:
                pass
            return None
        return None

    def show_main_document(
        self, document: MainDeckDocument, preferred_card: str | None
    ) -> str | None:
        """Push ``document`` to the Main view; return the active card."""
        previous_document = self._main_document
        self._main_document = document
        # Partial documents never decide the mode.
        if document.partial:
            current = self._render_mode.get(DeckId.MAIN, RenderMode.PAGED)
            try:
                active = self.main_view.show_document(
                    document, preferred_card=preferred_card, mode=current
                )
            except TypeError:
                active = self.main_view.show_document(
                    document, preferred_card=preferred_card
                )
            except Exception:
                active = None
            self._main_active_card = active
            if self._deck is DeckId.MAIN:
                self.set_deck(DeckId.MAIN)
            else:
                self.refresh_chrome()
            try:
                self._sync_block_navigable()
            except Exception:
                pass
            try:
                self._sync_block_rail()  # type: ignore[attr-defined]
            except Exception:
                pass
            return active
        stored_subject = self._mode_subject.get(DeckId.MAIN)
        same_subject = stored_subject is not None and stored_subject == document.subject
        # First decision for a subject counts as a new subject.
        is_new_subject = stored_subject != document.subject
        new_mode = self._decide_main_mode(document, same_subject=same_subject)
        old_mode = self._render_mode.get(DeckId.MAIN, RenderMode.PAGED)
        if new_mode is not old_mode:
            active = self._apply_main_transition(
                document,
                preferred_card,
                old_mode=old_mode,
                new_mode=new_mode,
                is_new_subject=is_new_subject,
                previous_document=previous_document,
            )
        else:
            try:
                if new_mode is RenderMode.PAGED:
                    active = self._show_main_paged(document, preferred_card, new_mode)
                else:
                    active = self.main_view.show_document(
                        document, preferred_card=preferred_card, mode=new_mode
                    )
            except TypeError:
                active = self.main_view.show_document(
                    document, preferred_card=preferred_card
                )
            except Exception:
                active = None
            if new_mode is RenderMode.SPREAD:
                if is_new_subject:
                    # Sticky-Reply landing replaces scroll_to_card when the
                    # preferred card carries blocks; <2 blocks keeps today.
                    landed = False
                    if (
                        preferred_card is not None
                        and document.card(preferred_card) is not None
                        and preferred_card
                        != (document.cards[0].card_id if document.cards else None)
                    ):
                        try:
                            landed = bool(
                                self._land_deck_spread_on_blocks(  # type: ignore[attr-defined]
                                    document, preferred_card
                                )
                            )
                        except Exception:
                            landed = False
                        if landed:
                            active = self._main_active_card
                        else:
                            try:
                                self.main_view.scroll_to_card(preferred_card)
                                active = preferred_card
                            except Exception:
                                pass
                    elif (
                        preferred_card is None or document.card(preferred_card) is None
                    ):
                        # No explicit choice: sticky landing still applies when
                        # the preferred/sticky card has blocks (e.g. Reply).
                        try:
                            sticky = self._land_deck_spread_on_blocks(  # type: ignore[attr-defined]
                                document, preferred_card
                            )
                            if sticky:
                                active = self._main_active_card
                        except Exception:
                            pass
                else:
                    # Same-subject streaming: a follower re-lands with the
                    # clamp; a parked reader stays put. A bottom pin persists
                    # via the scheduled reapply.
                    try:
                        pinned = bool(
                            getattr(self.main_view, "is_pinned_to_bottom", False)
                        )
                    except Exception:
                        pinned = False
                    if not pinned:
                        try:
                            view = self.main_view
                            card = self._spread_block_card(  # type: ignore[attr-defined]
                                document, preferred_card
                            )
                            if card is not None:
                                try:
                                    cursor = view._block_cursors.get(card.card_id)  # type: ignore[attr-defined]
                                except Exception:
                                    cursor = None
                                if cursor is not None and bool(
                                    getattr(cursor, "following", False)
                                ):
                                    try:
                                        if bool(
                                            self._land_deck_spread_on_blocks(  # type: ignore[attr-defined]
                                                document,
                                                card.card_id,
                                            )
                                        ):
                                            active = self._main_active_card
                                    except Exception:
                                        pass
                        except Exception:
                            pass
            self._main_active_card = active
        self._render_mode[DeckId.MAIN] = new_mode
        self._mode_subject[DeckId.MAIN] = document.subject
        if self._deck is DeckId.MAIN:
            self.set_deck(DeckId.MAIN)
        else:
            self.refresh_chrome()
        # set_deck re-decides with same subject; guard against recursion by
        # restoring the just-decided mode when set_deck did not change it.
        self._render_mode[DeckId.MAIN] = new_mode
        try:
            self._sync_block_navigable()
        except Exception:
            pass
        try:
            self._schedule_block_redecision()
        except Exception:
            pass
        try:
            self._sync_block_rail()  # type: ignore[attr-defined]
        except Exception:
            pass
        return self._main_active_card


__all__ = ["DeckPanelNavigationMixin"]

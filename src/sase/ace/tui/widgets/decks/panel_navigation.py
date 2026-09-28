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
    _final_document: MainDeckDocument
    _final_switcher: Any | None
    _tools_switcher: Any | None
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
        if self._deck is DeckId.FINAL:
            if self.is_spread(DeckId.FINAL):
                return self._cycle_document_spread(DeckId.FINAL, direction)
            try:
                ids = [card.card_id for card in self._final_document.cards]
            except Exception:
                return None
            try:
                active = self.final_view.active_card_id
            except Exception:
                try:
                    active = self._stored_document_active(DeckId.FINAL)
                except Exception:
                    active = None
            next_id = cycle_card_id(ids, active, direction)
            if next_id is None:
                return None
            try:
                block_mode = self.document_block_mode_for_card(
                    DeckId.FINAL, self._final_document, next_id
                )
            except Exception:
                block_mode = None
            try:
                try:
                    shown = self.final_view.show_card(next_id, block_mode=block_mode)
                except TypeError:
                    shown = self.final_view.show_card(next_id)
            except Exception:
                return None
            if shown is None:
                return None
            try:
                self._store_document_active(DeckId.FINAL, shown)
            except Exception:
                pass
            self.refresh_chrome()
            return shown
        if self._deck is DeckId.TOOLS:
            return self._cycle_tools_card(direction)
        return None

    def _cycle_tools_card(self, direction: int) -> str | None:
        """Cycle the Tools cards (``runs`` | ``llm-calls``); Ctrl+J/K."""
        try:
            tabs = self._tools_tabs()  # type: ignore[attr-defined]
        except Exception:
            return None
        ids = [tab.card_id for tab in tabs]
        if not ids:
            return None
        try:
            active = self.active_tools_card()  # type: ignore[attr-defined]
        except Exception:
            active = None
        next_id = cycle_card_id(ids, active, direction)
        if next_id is None:
            return None
        return self._show_tools_card(next_id)

    def _show_tools_card(self, card_id: str) -> str | None:
        """Show one Tools card host; return the shown card id."""
        try:
            self._store_document_active(DeckId.TOOLS, card_id)
        except Exception:
            pass
        try:
            self._sync_tools_hosts()  # type: ignore[attr-defined]
        except Exception:
            pass
        self.refresh_chrome()
        try:
            self._sync_block_navigable()
        except Exception:
            pass
        try:
            self._sync_block_rail()  # type: ignore[attr-defined]
        except Exception:
            pass
        return card_id

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
            if is_new_subject:
                self.set_deck(DeckId.MAIN)
            else:
                self._update_empty_state()
                self.refresh_chrome()
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

    def handle_tool_runs_deck_loaded(self, message: Any) -> None:
        """Store a freshly loaded Runs document and refresh chrome.

        Records the document for tabs, the ``tools ⚒N M`` subtitle
        segment and the empty state, merges Runs availability with the
        LLM Calls card's, and shows exactly one Tools host — all
        without disturbing the active card.
        """
        try:
            document = message.document
        except Exception:
            return
        self._tool_runs_document = document
        try:
            active = message.active_card
        except Exception:
            active = None
        try:
            self._store_document_active(DeckId.TOOLS, active)
        except Exception:
            pass
        try:
            from sase.ace.tui.tool_runs.deck import tools_switcher_segment

            if document.cards:
                try:
                    avail = self._availability.get(DeckId.TOOLS)  # type: ignore[attr-defined]
                    n_calls = getattr(avail, "calls_count", None)
                except Exception:
                    n_calls = None
                self._tools_switcher = tools_switcher_segment(
                    getattr(message, "n_runs", 0),
                    n_calls,
                    live=bool(getattr(message, "live", False)),
                    silent=bool(getattr(message, "silent", False)),
                )
            else:
                self._tools_switcher = None
        except Exception:
            pass
        try:
            self._merge_tool_runs_availability(message)
        except Exception:
            pass
        try:
            self._sync_tools_hosts()  # type: ignore[attr-defined]
        except Exception:
            pass
        try:
            from sase.ace.tui.tool_runs.reveal import (
                apply_pending_tool_run_select,
            )

            app = getattr(self, "app", None)
            if app is not None:
                try:
                    n_runs = int(getattr(message, "n_runs", 0) or 0)
                except Exception:
                    n_runs = None
                if apply_pending_tool_run_select(app, self, n_runs=n_runs):
                    try:
                        self._sync_block_navigable()  # type: ignore[attr-defined]
                    except Exception:
                        pass
                    try:
                        self._sync_block_rail()  # type: ignore[attr-defined]
                    except Exception:
                        pass
        except Exception:
            pass
        if self._deck is DeckId.TOOLS:
            try:
                self.set_deck(DeckId.TOOLS)
            except Exception:
                try:
                    self.refresh_chrome()
                except Exception:
                    pass
        else:
            try:
                self.refresh_chrome()
            except Exception:
                pass
        try:
            message.stop()
        except Exception:
            pass

    def _merge_tool_runs_availability(self, message: Any = None) -> None:
        """Merge the Runs card's availability with the LLM Calls card's."""
        from .availability import DeckAvailability

        try:
            current = self._availability.get(DeckId.TOOLS)  # type: ignore[attr-defined]
        except Exception:
            current = None
        try:
            has_runs = bool(self._tool_runs_document.cards)
        except Exception:
            has_runs = False
        try:
            # Prefer the loaded row count: single-run documents render
            # their run as preamble text (no CardBlock), so len(blocks)
            # undercounts them as zero.
            runs_count = int(getattr(message, "n_runs", 0))
        except Exception:
            runs_count = 0
        if not runs_count:
            try:
                runs_count = len(self._tool_runs_document.cards[0].blocks)  # type: ignore[attr-defined]
            except Exception:
                runs_count = 0
        calls_has: bool | None = None
        calls_count: int | None = None
        if current is not None:
            calls_count = getattr(current, "calls_count", None)
            if calls_count is None:
                calls_count = getattr(current, "count", None)
            calls_has = getattr(current, "has_content", None)
        has_content: bool | None
        if has_runs:
            has_content = True
        elif calls_has is None:
            has_content = None
        else:
            has_content = bool(calls_has)
        try:
            self._availability[DeckId.TOOLS] = DeckAvailability(  # type: ignore[attr-defined]
                has_content,
                calls_count,
                runs_count=runs_count if has_runs else 0,
                calls_count=calls_count,
            )
        except Exception:
            pass
        try:
            self._update_empty_state()  # type: ignore[attr-defined]
        except Exception:
            pass

    def show_tool_runs_document(
        self,
        document: MainDeckDocument,
        preferred_card: str | None,
    ) -> str | None:
        """Push ``document`` to the Runs view; return the active card."""
        self._tool_runs_document = document
        try:
            block_mode = self.document_block_mode_for_card(
                DeckId.TOOLS, document, preferred_card
            )
        except Exception:
            block_mode = None
        try:
            active = self.tool_runs_view.show_tool_runs_document(  # type: ignore[attr-defined]
                document, preferred_card, block_mode=block_mode
            )
        except TypeError:
            try:
                active = self.tool_runs_view.show_tool_runs_document(  # type: ignore[attr-defined]
                    document, preferred_card
                )
            except Exception:
                active = None
        except Exception:
            active = None
        try:
            self._store_document_active(DeckId.TOOLS, active)
        except Exception:
            pass
        try:
            self._sync_tools_hosts()  # type: ignore[attr-defined]
        except Exception:
            pass
        return active

    def handle_final_deck_loaded(self, message: Any) -> None:
        """Store a freshly loaded FINAL document and refresh chrome.

        The originating view already painted; this records the document
        for tabs, the ``final <glyph>`` subtitle segment and the empty
        state without disturbing the active card.
        """
        try:
            document = message.document
        except Exception:
            return
        self._final_document = document
        try:
            active = message.active_card
        except Exception:
            active = None
        try:
            self._store_document_active(DeckId.FINAL, active)
        except Exception:
            pass
        try:
            from .titles import final_switcher_segment

            if document.cards:
                self._final_switcher = final_switcher_segment(
                    getattr(message, "status", None),
                    getattr(message, "glyph", None),
                )
            else:
                self._final_switcher = None
        except Exception:
            pass
        if self._deck is DeckId.FINAL:
            try:
                self.set_deck(DeckId.FINAL)
            except Exception:
                try:
                    self.refresh_chrome()
                except Exception:
                    pass
        else:
            try:
                self.refresh_chrome()
            except Exception:
                pass
        try:
            message.stop()
        except Exception:
            pass

    def show_final_document(
        self,
        document: MainDeckDocument,
        preferred_card: str | None,
        *,
        status: str | None = None,
        glyph: str | None = None,
    ) -> str | None:
        """Push ``document`` to the FINAL view; return the active card.

        ``status``/``glyph`` feed the ``final <glyph>`` subtitle segment so
        a landing failure shows in the border while reading other decks.
        """
        self._final_document = document
        try:
            from .model import resolve_active_card

            pending = resolve_active_card(
                document.card_ids, preferred_card, partial=document.partial
            )
            block_mode = self.document_block_mode_for_card(
                DeckId.FINAL, document, pending
            )
        except Exception:
            block_mode = None
        try:
            try:
                active = self.final_view.show_final_document(
                    document, preferred_card, block_mode=block_mode
                )
            except TypeError:
                active = self.final_view.show_final_document(document, preferred_card)
        except Exception:
            active = None
        try:
            self._store_document_active(DeckId.FINAL, active)
        except Exception:
            pass
        try:
            from .titles import final_switcher_segment

            if document.cards:
                self._final_switcher = final_switcher_segment(status, glyph)
            else:
                self._final_switcher = None
        except Exception:
            pass
        if self._deck is DeckId.FINAL:
            try:
                self.set_deck(DeckId.FINAL)
            except Exception:
                try:
                    self.refresh_chrome()
                except Exception:
                    pass
        else:
            try:
                self.refresh_chrome()
            except Exception:
                pass
        try:
            self._sync_block_navigable()
        except Exception:
            pass
        try:
            self._sync_block_rail()  # type: ignore[attr-defined]
        except Exception:
            pass
        return active


__all__ = ["DeckPanelNavigationMixin"]

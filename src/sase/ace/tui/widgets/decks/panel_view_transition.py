"""Anchor-preserving Main view-change transition.

Transition third of :mod:`sase.ace.tui.widgets.decks.panel_view`: the
generation-guarded scroll/restore helpers and the stored-policy Main
view-change that keeps the reader's card, block, offset, pin, and
following in every direction.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from textual.containers import VerticalScroll

from .main_view_blocks import sync_scrollbar_position
from .model import DeckId, DeckView, RenderMode
from .panel_view_deferred import PrebuiltRenderContext
from .view_policy import forced_block_mode

__all__ = ["DeckPanelViewTransitionMixin"]


def _set_applied_generation(owner: object, generation: int) -> None:
    try:
        owner._main_view_applied_generation = int(generation)  # type: ignore[attr-defined]
    except Exception:
        pass


class DeckPanelViewTransitionMixin:
    """Main view-change transition with anchor-preserving restores."""

    _panel_index: int
    _render_mode: dict[DeckId, RenderMode]
    _mode_subject: dict[DeckId, object]
    _block_mode_key: tuple[object, str] | None
    _view_generation: int
    _pending_view_anchor: tuple[object, Any, int] | None
    _main_active_card: str | None

    if TYPE_CHECKING:

        def __getattr__(self, name: str) -> Any: ...

    # -- View-change transition -----------------------------------------

    def _clear_pending_view_anchor(self, generation: int) -> None:
        """Drop the pending anchor once ``generation`` has settled."""
        try:
            pending = self._pending_view_anchor
        except Exception:
            return
        if pending is None:
            return
        try:
            _, _, pending_generation = pending
        except Exception:
            return
        if pending_generation != generation:
            return
        try:
            self._pending_view_anchor = None
        except Exception:
            pass

    def _scroll_main_to(self, target: int, generation: int) -> None:
        """Scroll the Main scroller when ``generation`` is still current."""
        if generation != self._view_generation:
            return
        try:
            scroll = self.query_one(
                f"#agent-deck-panel-{self._panel_index}-main-scroll",
                VerticalScroll,
            )
        except Exception:
            return
        try:
            scroll.scroll_to(y=max(0, int(target)), animate=False, immediate=True)
        except TypeError:
            try:
                scroll.scroll_to(y=max(0, int(target)), animate=False)
            except Exception:
                return
        except Exception:
            return
        try:
            self.call_after_refresh(lambda: sync_scrollbar_position(scroll))
        except Exception:
            pass

    def _spread_block_row(self, block_id: str) -> int | None:
        """Return the spread block-anchor row for ``block_id``."""
        try:
            view = self.main_view
        except Exception:
            return None
        try:
            width = int(view._spread_content_width())  # type: ignore[attr-defined]
        except Exception:
            width = 0
        if width <= 0:
            return None
        try:
            pairs = view.block_anchor_rows(width=width)
        except Exception:
            return None
        if not pairs:
            return None
        for bid, row in pairs:
            if bid == block_id:
                return int(row)
        return None

    def _restore_spread_view_target(self, anchor: Any, generation: int) -> None:
        """Restore a spread target with bounded, generation-guarded retries."""
        if anchor is None:
            return
        try:
            pinned = bool(anchor.pinned)
        except Exception:
            pinned = False
        if pinned:
            if generation != self._view_generation:
                return
            try:
                self.main_view.pin_to_bottom()
            except Exception:
                pass
            try:
                self.call_after_refresh(lambda: self._reapply_view_pin(generation))
            except Exception:
                pass
            self._clear_pending_view_anchor(generation)
            return
        try:
            block_id = anchor.block_id
            card_id = anchor.card_id
            offset = max(0, int(anchor.offset_rows))
        except Exception:
            return
        if block_id is not None:
            self._restore_spread_block_offset(anchor, generation, 0)
            return
        try:
            base = self.main_view.spread_body_start(card_id or "") if card_id else None
        except Exception:
            base = None
        if base is None:
            try:
                self.call_after_refresh(
                    lambda: self._restore_spread_card_offset(anchor, generation, 1)
                )
            except Exception:
                pass
            return
        self._scroll_main_to(int(base) + offset, generation)
        self._clear_pending_view_anchor(generation)

    def _reapply_view_pin(self, generation: int) -> None:
        """Reapply a restored bottom pin after layout settles."""
        if generation != self._view_generation:
            return
        try:
            self.main_view.pin_to_bottom()
        except Exception:
            pass
        self._clear_pending_view_anchor(generation)

    def _restore_spread_card_offset(
        self, anchor: Any, generation: int, attempt: int
    ) -> None:
        """Retry a card-top spread restore with a bounded attempt count."""
        if generation != self._view_generation:
            return
        try:
            card_id = anchor.card_id
            offset = max(0, int(anchor.offset_rows))
        except Exception:
            return
        try:
            base = self.main_view.spread_body_start(card_id or "") if card_id else None
        except Exception:
            base = None
        if base is None:
            if attempt >= 3:
                self._scroll_main_to(0, generation)
                self._clear_pending_view_anchor(generation)
                return
            try:
                self.call_after_refresh(
                    lambda: self._restore_spread_card_offset(
                        anchor, generation, attempt + 1
                    )
                )
            except Exception:
                pass
            return
        self._scroll_main_to(int(base) + offset, generation)
        self._clear_pending_view_anchor(generation)

    def _restore_spread_block_offset(
        self, anchor: Any, generation: int, attempt: int
    ) -> None:
        """Retry a block-anchored spread restore with a bounded count."""
        if generation != self._view_generation:
            # A newer view change owns the scroll position now.
            return
        try:
            offset = max(0, int(anchor.offset_rows))
            block_id = anchor.block_id
        except Exception:
            return
        row = self._spread_block_row(block_id) if block_id is not None else None
        if row is None:
            if attempt >= 3:
                # Anchors never published: fall back to the card top.
                try:
                    base = self.main_view.spread_body_start(anchor.card_id or "")
                except Exception:
                    base = None
                self._scroll_main_to(int(base) if base is not None else 0, generation)
                self._clear_pending_view_anchor(generation)
                return
            try:
                self.call_after_refresh(
                    lambda: self._restore_spread_block_offset(
                        anchor, generation, attempt + 1
                    )
                )
            except Exception:
                pass
            return
        self._scroll_main_to(int(row) + offset, generation)
        self._clear_pending_view_anchor(generation)

    def _restore_paged_view_target(
        self, anchor: Any, active: str | None, generation: int
    ) -> None:
        """Restore a paged target; stale generations are a no-op."""
        if generation != self._view_generation:
            return
        if anchor is None:
            return
        try:
            pinned = bool(anchor.pinned)
        except Exception:
            pinned = False
        if pinned:
            try:
                self.main_view.pin_to_bottom()
            except Exception:
                pass
            try:
                self.call_after_refresh(lambda: self._reapply_view_pin(generation))
            except Exception:
                pass
            self._clear_pending_view_anchor(generation)
            return
        try:
            has_block = anchor.block_id is not None and anchor.card_id is not None
        except Exception:
            has_block = False
        if has_block:
            # Staleness safety comes from the shared pending anchor: every
            # rapid change reuses it, so a stale deferred retry converges on
            # the same block target instead of a torn scroll offset.
            try:
                self._restore_block_transition(anchor, active)
            except Exception:
                pass
            try:
                self.call_after_refresh(
                    lambda: self._clear_pending_view_anchor(generation)
                )
            except Exception:
                pass
            return
        try:
            offset = max(0, int(anchor.offset_rows))
        except Exception:
            offset = 0
        self._scroll_main_to(offset, generation)
        self._clear_pending_view_anchor(generation)

    def _apply_main_view_change(self) -> None:
        """Apply the stored Main policy, keeping the reader's place (D7)."""
        try:
            document = self._main_document
        except Exception:
            return
        try:
            subject = document.subject
            cards = document.cards
            partial = document.partial
        except Exception:
            return
        if partial or not cards:
            self._refresh_view_chrome()
            return
        try:
            old_mode = self._render_mode.get(DeckId.MAIN, RenderMode.PAGED)
        except Exception:
            old_mode = RenderMode.PAGED
        # While a restore is still pending, reuse that anchor instead of
        # capturing from a scroll offset that has not been restored yet. A
        # subject change drops it (subjects never share anchors).
        anchor: Any = None
        try:
            pending = self._pending_view_anchor
        except Exception:
            pending = None
        if pending is not None:
            try:
                pending_subject, pending_anchor, _ = pending
                if pending_subject == subject and pending_anchor is not None:
                    anchor = pending_anchor
            except Exception:
                anchor = None
        if anchor is None:
            try:
                anchor = self._capture_reading_anchor(document, old_mode=old_mode)
            except Exception:
                anchor = None
        try:
            self._view_generation += 1
            generation = int(self._view_generation)
        except Exception:
            generation = 0
        try:
            self._pending_view_anchor = (subject, anchor, generation)
        except Exception:
            pass
        # A policy switch (including back to AUTO) decides both levels
        # without hysteresis, like a fresh Auto decision for this content.
        try:
            self._block_mode_key = None
        except Exception:
            pass
        try:
            new_mode = self._decide_main_mode(document, same_subject=False)
        except Exception:
            self._refresh_view_chrome()
            try:
                _set_applied_generation(self, int(self._view_generation))
            except Exception:
                pass
            return
        try:
            self._render_mode[DeckId.MAIN] = new_mode
            self._mode_subject[DeckId.MAIN] = subject
        except Exception:
            pass
        try:
            current: str | None = self.main_view.active_card_id
        except Exception:
            current = None
        if current is None:
            try:
                current = self._main_active_card
            except Exception:
                current = None
        try:
            anchor_card: str | None = anchor.card_id if anchor is not None else None
        except Exception:
            anchor_card = None
        # Badge-first prefix: the destination badge must be what the next
        # frame paints. Flip the layout, refresh chrome synchronously, and
        # build the body off the pump. Never call show_document here.
        try:
            self._sync_files_views()
        except Exception:
            pass
        self._refresh_view_chrome()
        try:
            self._sync_view_cycle_available()
        except Exception:
            pass
        self._spawn_deferred_main_body(
            document,
            subject,
            anchor,
            generation,
            new_mode,
            anchor_card,
            current,
        )
        return

    def _spawn_deferred_main_body(
        self,
        document: Any,
        subject: object,
        anchor: Any,
        generation: int,
        new_mode: RenderMode,
        anchor_card: str | None,
        current: str | None,
    ) -> None:
        """Warm the destination body off-thread, then apply it on the loop."""
        try:
            policy = self.view_policy(DeckId.MAIN)  # type: ignore[attr-defined]
        except Exception:
            policy = DeckView.AUTO
        target_card = anchor_card or current
        card_obj = None
        if target_card is not None and new_mode is not RenderMode.SPREAD:
            try:
                card_obj = document.card(target_card)
            except Exception:
                card_obj = None
        try:
            block_total = len(card_obj.blocks) if card_obj is not None else 0
        except Exception:
            block_total = 0
        try:
            want_paged_blocks = (
                forced_block_mode(policy, block_total) is RenderMode.PAGED
            )
        except Exception:
            want_paged_blocks = False
        try:
            anchor_block = anchor.block_id if anchor is not None else None
        except Exception:
            anchor_block = None
        try:
            view = self.main_view  # type: ignore[attr-defined]
            width = int(view._spread_content_width())  # type: ignore[attr-defined]
        except Exception:
            width = 0
            view = None
        try:
            accent = str(view._spread_accent()) if view is not None else ""  # type: ignore[attr-defined]
        except Exception:
            accent = ""
        renderable: Any = None
        dest_digest: str | None = None
        if width > 0:
            try:
                from .panel_view_deferred import build_destination_renderable

                renderable, dest_digest = build_destination_renderable(
                    document,
                    spread=new_mode is RenderMode.SPREAD,
                    target_card_id=target_card,
                    anchor_block_id=anchor_block
                    if isinstance(anchor_block, str)
                    else None,
                    want_paged_blocks=bool(want_paged_blocks),
                    spread_accent=accent,
                )
            except Exception:
                renderable, dest_digest = None, None
        # Fidelity capture (UI thread only): snapshot the console options,
        # post-render wrap, and base-style token so the worker replicates
        # RichVisual.render_strips. Without a capture, skip the prebuilt
        # body and apply synchronously instead of painting stale pixels.
        prebuilt_context: PrebuiltRenderContext | None = None
        if width > 0 and renderable is not None and view is not None:
            try:
                from textual._context import active_app

                from .panel_view_deferred import (
                    capture_prebuilt_context as _capture,
                )

                prebuilt_context = _capture(active_app.get(), view, renderable)
            except Exception:
                prebuilt_context = None
        try:
            from ...util.pump_tasks import spawn_pump_free_task
        except Exception:
            spawn_pump_free_task = None  # type: ignore[assignment]
        if (
            spawn_pump_free_task is None
            or width <= 0
            or renderable is None
            or prebuilt_context is None
        ):
            try:
                self._apply_deferred_main_body(
                    document, anchor, generation, new_mode, anchor_card, current
                )
            finally:
                _set_applied_generation(self, generation)
            return
        try:
            task = spawn_pump_free_task(
                self,
                self._run_deferred_main_body(
                    prebuilt_context,
                    dest_digest,
                    width,
                    document,
                    anchor,
                    generation,
                    new_mode,
                    anchor_card,
                    current,
                ),
                name="deck-main-view-body",
                registry_attr="_pump_free_main_view_tasks",
            )
        except Exception:
            task = None
        if task is None:
            try:
                self._apply_deferred_main_body(
                    document, anchor, generation, new_mode, anchor_card, current
                )
            finally:
                _set_applied_generation(self, generation)

    async def _run_deferred_main_body(
        self,
        prebuilt_context: PrebuiltRenderContext,
        dest_digest: str | None,
        width: int,
        document: Any,
        anchor: Any,
        generation: int,
        new_mode: RenderMode,
        anchor_card: str | None,
        current: str | None,
    ) -> None:
        """Build strips in a worker thread, then apply on the UI thread."""
        prebuilt: tuple[Any, Any, Any] | None = None
        try:
            from .panel_view_deferred import build_prebuilt_offthread

            prebuilt = await asyncio.to_thread(
                build_prebuilt_offthread, prebuilt_context, width
            )
        except Exception:
            prebuilt = None
        if prebuilt is not None and dest_digest is not None:
            try:
                from .panel_view_deferred import store_prebuilt as _store

                _store(
                    dest_digest,
                    width,
                    prebuilt[0],
                    prebuilt[1],
                    prebuilt[2],
                    prebuilt_context.style_token,
                )
            except Exception:
                pass
        try:
            if int(getattr(self, "_view_generation", -1)) != int(generation):
                return
        except Exception:
            return
        try:
            self._apply_deferred_main_body(
                document, anchor, generation, new_mode, anchor_card, current
            )
        finally:
            _set_applied_generation(self, generation)

    def _apply_deferred_main_body(
        self,
        document: Any,
        anchor: Any,
        generation: int,
        new_mode: RenderMode,
        anchor_card: str | None,
        current: str | None,
    ) -> None:
        """Apply the prebuilt body when ``generation`` is still current."""
        try:
            if int(getattr(self, "_view_generation", -1)) != int(generation):
                return
        except Exception:
            return
        try:
            subject = document.subject
        except Exception:
            subject = None
        if new_mode is RenderMode.SPREAD:
            try:
                active = self.main_view.show_document(
                    document,
                    preferred_card=anchor_card or current,
                    mode=new_mode,
                )
            except TypeError:
                try:
                    active = self.main_view.show_document(
                        document, preferred_card=anchor_card or current
                    )
                except Exception:
                    active = None
            except Exception:
                active = None
            try:
                # The restore targets the anchor card, not the derived one.
                self._main_active_card = anchor_card or active
            except Exception:
                pass
            self._restore_spread_view_target(anchor, generation)
        else:
            target_card = anchor_card or current
            card_obj = None
            if target_card is not None:
                try:
                    card_obj = document.card(target_card)
                except Exception:
                    card_obj = None
            # Entering page blocks shows the anchor's block, not the newest:
            # align the cursor first, exactly as scroll-sync would have.
            try:
                policy = self.view_policy(DeckId.MAIN)
            except Exception:
                policy = DeckView.AUTO
            try:
                block_total = len(card_obj.blocks) if card_obj is not None else 0
            except Exception:
                block_total = 0
            try:
                want_paged_blocks = (
                    forced_block_mode(policy, block_total) is RenderMode.PAGED
                )
            except Exception:
                want_paged_blocks = False
            if want_paged_blocks and card_obj is not None and anchor is not None:
                try:
                    anchor_block = anchor.block_id
                except Exception:
                    anchor_block = None
                if (
                    anchor_block is not None
                    and card_obj.block(anchor_block) is not None
                ):
                    try:
                        cursor = self.main_view.active_block_id(target_card or "")
                    except Exception:
                        cursor = None
                    if cursor != anchor_block:
                        try:
                            self.main_view.select_block_cursor(card_obj, anchor_block)
                        except Exception:
                            pass
            # Same-subject view change: suppress the show-time block-spread
            # newest landing (it would fight the anchor restore, including
            # through its deferred retries) by presetting the projection
            # identity the show is about to compute. The restore below owns
            # the final scroll position and cursor.
            try:
                view_subject_seen = bool(self.main_view._subject_seen)  # type: ignore[attr-defined]
                view_subject = self.main_view._previous_subject  # type: ignore[attr-defined]
            except Exception:
                view_subject_seen = False
                view_subject = None
            if view_subject_seen and view_subject == subject and card_obj is not None:
                try:
                    navigable = bool(card_obj.has_block_navigation)
                except Exception:
                    navigable = False
                if navigable and want_paged_blocks is False:
                    try:
                        self.main_view._block_projected = (target_card, None)  # type: ignore[attr-defined]
                    except Exception:
                        pass
            try:
                active = self._show_main_paged(document, target_card, new_mode)
            except Exception:
                active = None
            try:
                self._main_active_card = active
            except Exception:
                pass
            self._restore_paged_view_target(anchor, active, generation)
        try:
            self._sync_files_views()
        except Exception:
            pass
        self._refresh_view_chrome()
        # The chrome refresh above already re-synced the cycle predicate
        # through the block-predicate override; call it directly as well so
        # a missing override in a future MRO cannot leave it stale.
        try:
            self._sync_view_cycle_available()
        except Exception:
            pass

    def on_unmount(self) -> None:
        """Cancel any in-flight deferred Main body at teardown."""
        try:
            from ...util.pump_tasks import cancel_pump_free_tasks
        except Exception:
            cancel_pump_free_tasks = None  # type: ignore[assignment]
        try:
            if cancel_pump_free_tasks is not None:
                cancel_pump_free_tasks(self)
        except Exception:
            pass
        try:
            parent_unmount = super().on_unmount  # type: ignore[misc]
        except Exception:
            parent_unmount = None
        if callable(parent_unmount):
            try:
                parent_unmount()
            except Exception:
                pass

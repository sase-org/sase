"""⊛ FINAL deck view with an off-thread run-view loader (``final-deck-shell``).

Thin :class:`DeckId.FINAL` specialization of
:class:`~sase.ace.tui.widgets.decks.document_view.CardDocumentView` that
paints any cached projection instantly, otherwise a loading line, then
collects inputs and projects through the binding on a worker thread.
Stale results are rejected by subject identity **and** detail generation;
a stat-only signature cache skips re-projection when nothing changed.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from rich.text import Text
from textual.message import Message
from textual.worker import Worker, WorkerState

from ....agent_decks_settings import agent_decks_settings_for
from ..document_view import CardDocumentView
from ..main_document import MainDeckDocument
from ..model import DeckId, RenderMode
from .document import decide_final_mode
from .live import (
    FINAL_LIVE_TICK_SECONDS,
    FinalLiveTicker,
    finalization_active,
)
from .loader import (
    FinalDeckLoadResult,
    cached_final_result,
    final_cache_key,
    load_final_deck,
)

log = logging.getLogger(__name__)


class FinalDeckLoaded(Message):
    """A FINAL worker finished painting for the current subject."""

    def __init__(
        self,
        document: MainDeckDocument,
        *,
        status: str,
        glyph: str,
        signature: str,
        active_card: str | None,
    ) -> None:
        """Initialize the loaded notification."""
        super().__init__()
        self.document = document
        self.status = status
        self.glyph = glyph
        self.signature = signature
        self.active_card = active_card


class FinalDeckView(CardDocumentView):
    """One FINAL card view that lives inside a VerticalScroll."""

    def __init__(self, **kwargs: Any) -> None:
        """Initialize the FINAL deck view."""
        super().__init__(DeckId.FINAL, **kwargs)
        self._current_subject: object | None = None
        self._current_subject_identity: object | None = None
        self._current_generation: int = 0
        self._current_preferred: str | None = None
        self._current_worker: Worker[FinalDeckLoadResult] | None = None
        self._current_worker_subject: object | None = None
        self._current_worker_generation: int = 0
        self._painted_signature: str | None = None
        self._has_displayed_content = False
        self._live_ticker = FinalLiveTicker()
        self._live_timer: Any | None = None
        self._live_agent: Any | None = None
        self._live_attempt_number: int | None = None
        self._live_scroll_watched = False

    def update_display(
        self,
        agent: Any,
        *,
        attempt_number: int | None = None,
        generation: int = 0,
        preferred_card: str | None = None,
    ) -> None:
        """Show FINAL cards for ``agent``, loading off-thread on a miss."""
        from ....models.finalizer_run_targets import node_run_targets

        subject = _subject_key(agent)
        identity = getattr(agent, "identity", None)
        self._current_subject = subject
        self._current_subject_identity = identity
        self._current_generation = generation
        self._current_preferred = preferred_card
        self._live_agent = agent
        self._live_attempt_number = attempt_number
        self._sync_live_timer()
        try:
            targets = node_run_targets(agent, attempt_number)
        except Exception:
            targets = ()
        try:
            signature = final_cache_key(targets)
        except Exception:
            signature = ""
        if signature and signature == self._painted_signature and subject is not None:
            return
        try:
            cached = cached_final_result(identity, signature) if signature else None
        except Exception:
            cached = None
        if cached is not None:
            self._paint_final_result(cached, preferred_card)
            return
        if (
            self._current_worker is not None
            and self._current_worker.is_running
            and self._current_worker_subject == identity
            and self._current_worker_generation == generation
        ):
            return
        try:
            if self._current_worker is not None and self._current_worker.is_running:
                self._current_worker.cancel()
        except Exception:
            pass
        self._show_loading()

        def _fetch() -> FinalDeckLoadResult:
            return load_final_deck(
                targets,
                subject=subject,
                subject_identity=identity,
                generation=generation,
                live_tail_delay=self._live_delay_seconds(),
            )

        try:
            self._current_worker = self.run_worker(_fetch, thread=True)
        except Exception:
            return
        self._current_worker_subject = identity
        self._current_worker_generation = generation

    def show_empty(self) -> None:
        """Show the empty state."""
        self._current_subject = None
        self._current_subject_identity = None
        self._painted_signature = None
        self._has_displayed_content = False
        self._live_agent = None
        self._live_attempt_number = None
        self._stop_live_timer()
        try:
            if self._current_worker is not None and self._current_worker.is_running:
                self._current_worker.cancel()
        except Exception:
            pass
        self.update(Text("No agent selected", style="dim italic"))

    def show_final_document(
        self,
        document: MainDeckDocument,
        preferred_card: str | None,
        block_mode: RenderMode | None = None,
    ) -> str | None:
        """Push ``document`` to the FINAL view; return the active card.

        ``block_mode`` carries the panel's decided block mode for the
        active card (always automatic: FINAL has no deck-view policy, so
        ``P`` never forces it). ``None`` renders the legacy whole card.
        """
        try:
            mode = decide_final_mode(len(document.cards))
        except Exception:
            mode = RenderMode.PAGED
        try:
            return self.show_document(
                document,
                preferred_card=preferred_card,
                mode=mode,
                block_mode=block_mode,
            )
        except TypeError:
            try:
                return self.show_document(
                    document, preferred_card=preferred_card, mode=mode
                )
            except Exception:
                return None
        except Exception:
            return None

    def get_final_text(self) -> str | None:
        """Return the active FINAL document as plain text (search/export)."""
        try:
            from ...renderable_text import renderable_to_text
            from rich.console import Group
        except Exception:
            return None
        try:
            document = self._document
        except Exception:
            return None
        if document is None or not document.cards:
            return None
        try:
            parts: list[str] = []
            for card in document.cards:
                parts.append(f"── {card.title} ──")
                try:
                    parts.append(renderable_to_text(Group(*card.renderables)) or "")
                except Exception:
                    parts.append("")
            return "\n".join(parts).strip() or None
        except Exception:
            return None

    def _show_loading(self) -> None:
        if self._has_displayed_content:
            return
        self.update(Text("Loading finalizers…", style="dim italic"))

    def _live_delay_seconds(self) -> float:
        """Return the configured tail-delay gate, failing open to default."""
        try:
            return float(agent_decks_settings_for(self).final_tail_delay_seconds)
        except Exception:
            return 5.0

    @staticmethod
    def _live_summaries(agent: Any) -> list[Any]:
        """Return the in-memory finalizer summaries for ``agent`` (no I/O)."""
        summaries: list[Any] = []
        try:
            summaries.append(agent.finalizer_status)
        except Exception:
            pass
        try:
            from ....models.agent_session_members import (
                concrete_agent_session_turn_rows,
                is_sequential_agent_session_container,
            )

            if is_sequential_agent_session_container(agent):
                for turn in concrete_agent_session_turn_rows(agent):
                    try:
                        summaries.append(turn.finalizer_status)
                    except Exception:
                        continue
        except Exception:
            pass
        return [summary for summary in summaries if summary is not None]

    def _live_subject_active(self) -> bool:
        """Return whether the tick's subject has an active finalization."""
        agent = self._live_agent
        if agent is None:
            return False
        try:
            return any(
                finalization_active(summary) for summary in self._live_summaries(agent)
            )
        except Exception:
            return False

    def _live_host_visible(self) -> bool:
        """Return whether a panel currently shows this FINAL view (no I/O)."""
        try:
            from textual.containers import VerticalScroll

            node: Any = self.parent
            while node is not None:
                if isinstance(node, VerticalScroll):
                    try:
                        if not node.has_class("-shown"):
                            return False
                    except Exception:
                        return False
                    try:
                        if not node.display:
                            return False
                    except Exception:
                        pass
                    return True
                node = getattr(node, "parent", None)
        except Exception:
            pass
        return False

    def _live_navigating(self) -> bool:
        """Return whether the user is mid-navigation (250 ms gate)."""
        try:
            gate = getattr(getattr(self, "app", None), "_nav_gate", None)
            if gate is None:
                return False
            return bool(gate.is_navigating())
        except Exception:
            return False

    def _live_typing(self) -> bool:
        """Return whether the user is typing in the prompt input."""
        try:
            active = getattr(getattr(self, "app", None), "_prompt_input_active", None)
            if callable(active):
                return bool(active())
        except Exception:
            pass
        return False

    def _sync_live_timer(self) -> None:
        """Start the 1 Hz tick while the subject is active, else stop it."""
        try:
            if self._live_subject_active():
                self._watch_live_scroll()
                self._start_live_timer()
            else:
                self._stop_live_timer()
        except Exception:
            pass

    def _start_live_timer(self) -> None:
        """Start the 1 Hz live tick (idempotent)."""
        try:
            if self._live_timer is not None:
                return
            self._live_timer = self.set_interval(
                FINAL_LIVE_TICK_SECONDS, self._on_live_timer
            )
        except Exception:
            self._live_timer = None

    def _stop_live_timer(self) -> None:
        """Stop the 1 Hz live tick and release the in-flight slot."""
        timer, self._live_timer = self._live_timer, None
        try:
            if timer is not None:
                timer.stop()
        except Exception:
            pass
        try:
            self._live_ticker.finish()
        except Exception:
            pass

    def on_unmount(self) -> None:
        """Stop the live tick when the view tears down."""
        try:
            self._stop_live_timer()
        except Exception:
            pass
        try:
            from ....util.pump_tasks import cancel_pump_free_tasks

            cancel_pump_free_tasks(self)
        except Exception:
            pass

    def _on_live_timer(self) -> None:
        """Thin 1 Hz pump callback: gate synchronously, collect off-pump."""
        try:
            if self._live_agent is None:
                self._stop_live_timer()
                return
            if not self._live_subject_active():
                self._stop_live_timer()
                return
            if not self._live_ticker.want_tick(
                visible=self._live_host_visible(),
                active=True,
                navigating=self._live_navigating(),
                typing=self._live_typing(),
            ):
                return
            self._spawn_live_tick()
        except Exception:
            log.debug("final live tick gate failed", exc_info=True)

    def _spawn_live_tick(self) -> None:
        """Claim the in-flight slot and collect the tick pump-free."""
        try:
            from ....util.pump_tasks import spawn_pump_free_task
        except Exception:
            return
        try:
            if not self._live_ticker.begin():
                return
        except Exception:
            return
        try:
            task = spawn_pump_free_task(
                self,
                self._live_tick_run(),
                name="final-live-tick",
                registry_attr="_pump_free_final_live_tasks",
            )
        except Exception:
            task = None
        if task is None:
            try:
                self._live_ticker.finish()
            except Exception:
                pass

    async def _live_tick_run(self) -> None:
        """Collect fresh inputs off-thread, then repaint only when current."""
        try:
            result = await asyncio.to_thread(self._live_collect)
        except Exception:
            log.debug("final live collection failed", exc_info=True)
            try:
                self._live_ticker.finish()
            except Exception:
                pass
            return
        try:
            if result is None or self._is_stale_result(result):
                return
            if self._live_ticker.follow.paused:
                return
            if not self._live_host_visible() or not self._live_subject_active():
                return
            self._paint_final_result(result, self._current_preferred)
        except Exception:
            log.debug("final live paint failed", exc_info=True)
        finally:
            try:
                self._live_ticker.finish()
            except Exception:
                pass

    def _live_collect(self) -> FinalDeckLoadResult | None:
        """Collect, project and build one FINAL deck (tick worker body)."""
        from ....models.finalizer_run_targets import node_run_targets

        agent = self._live_agent
        if agent is None:
            return None
        try:
            targets = node_run_targets(agent, self._live_attempt_number)
        except Exception:
            return None
        return load_final_deck(
            targets,
            subject=self._current_subject,
            subject_identity=self._current_subject_identity,
            generation=self._current_generation,
            live_tail_delay=self._live_delay_seconds(),
            live_now=time.time(),
            fresh=True,
        )

    def _watch_live_scroll(self) -> None:
        """Watch the host scroll container for follow pause/resume."""
        if self._live_scroll_watched:
            return
        try:
            scroll = self._scroll_container()
            if scroll is None:
                return
            self.watch(scroll, "scroll_y", self._on_live_scroll_y)
            self._live_scroll_watched = True
        except Exception:
            pass

    def _on_live_scroll_y(self, _old: object, _new: object) -> None:
        """Pause the tail on scroll-up; resume with a refresh at the bottom."""
        try:
            scroll = self._scroll_container()
            if scroll is None:
                return
            try:
                position = float(scroll.scroll_y)
                ceiling = float(scroll.max_scroll_y)
            except Exception:
                return
            at_bottom = position >= ceiling if ceiling > 0 else True
            if self._live_ticker.note_scroll(at_bottom=at_bottom):
                self._on_live_timer()
        except Exception:
            pass

    def _paint_final_result(
        self, result: FinalDeckLoadResult, preferred_card: str | None
    ) -> None:
        try:
            ids = tuple(result.document.card_ids)
        except Exception:
            ids = ()
        if preferred_card is not None and preferred_card in ids:
            active_choice: str | None = preferred_card
        else:
            active_choice = result.default_card
        try:
            shown = self.show_final_document(result.document, active_choice)
        except Exception:
            shown = None
        del shown
        try:
            active_card = self._active_card
        except Exception:
            active_card = None
        try:
            self.post_message(
                FinalDeckLoaded(
                    result.document,
                    status=result.status,
                    glyph=result.glyph,
                    signature=result.signature,
                    active_card=active_card,
                )
            )
        except Exception:
            pass
        self._painted_signature = result.signature
        try:
            self._has_displayed_content = bool(ids)
        except Exception:
            self._has_displayed_content = False

    def _is_stale_result(self, result: FinalDeckLoadResult) -> bool:
        if result.subject_identity != self._current_subject_identity:
            return True
        return result.generation != self._current_generation

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        """Handle worker state changes, rejecting stale subjects."""
        if event.worker is not self._current_worker:
            return
        if event.state == WorkerState.SUCCESS:
            result = event.worker.result
            if not isinstance(result, FinalDeckLoadResult):
                return
            if self._is_stale_result(result):
                return
            self._paint_final_result(result, self._current_preferred)
        elif event.state == WorkerState.ERROR:
            if self._has_displayed_content:
                return
            self.update(Text("Finalizers unavailable", style="dim italic"))
        elif event.state == WorkerState.CANCELLED:
            pass


def _subject_key(agent: Any) -> object | None:
    """Return the document subject key for ``agent`` (identity or None)."""
    try:
        return getattr(agent, "identity", None)
    except Exception:
        return None


__all__ = ["FinalDeckLoaded", "FinalDeckView"]

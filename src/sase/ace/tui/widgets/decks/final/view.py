"""⊛ FINAL deck view with an off-thread run-view loader (``final-deck-shell``).

Thin :class:`DeckId.FINAL` specialization of
:class:`~sase.ace.tui.widgets.decks.document_view.CardDocumentView` that
paints any cached projection instantly, otherwise a loading line, then
collects inputs and projects through the binding on a worker thread.
Stale results are rejected by subject identity **and** detail generation;
a stat-only signature cache skips re-projection when nothing changed.
"""

from __future__ import annotations

from typing import Any

from rich.text import Text
from textual.message import Message
from textual.worker import Worker, WorkerState

from ..document_view import CardDocumentView
from ..main_document import MainDeckDocument
from ..model import DeckId, RenderMode
from .document import decide_final_mode
from .loader import (
    FinalDeckLoadResult,
    cached_final_result,
    final_cache_key,
    load_final_deck,
)


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

    def update_display(
        self,
        agent: Any,
        *,
        attempt_number: int | None = None,
        generation: int = 0,
        preferred_card: str | None = None,
    ) -> None:
        """Show FINAL cards for ``agent``, loading off-thread on a miss."""
        from ...models.finalizer_run_targets import node_run_targets

        subject = _subject_key(agent)
        identity = getattr(agent, "identity", None)
        self._current_subject = subject
        self._current_subject_identity = identity
        self._current_generation = generation
        self._current_preferred = preferred_card
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

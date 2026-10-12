"""≡ RECORD deck view with an off-thread loader (``record-deck-shell``).

Thin :class:`DeckId.RECORD` specialization of
:class:`~sase.ace.tui.widgets.decks.document_view.CardDocumentView`
that paints any cached four-card document instantly, otherwise a
loading line, then loads both extras and builds the document on a
worker thread. Stale results are rejected by subject identity **and**
detail generation; a signature cache skips rebuilds when nothing
changed.
"""

from __future__ import annotations

from typing import Any

from rich.text import Text
from textual.message import Message
from textual.worker import Worker, WorkerState

from ..document_view import CardDocumentView
from ..main_document import MainDeckDocument
from ..model import DeckId, RenderMode
from .document import decide_record_mode
from .loader import (
    RecordDeckLoadResult,
    cached_record_result,
    load_record_deck,
    record_cache_key,
)
from .model import (
    RecordSubject,
    record_archive_facts_from_light_row,
    record_subject_from_agent,
)


class RecordDeckLoaded(Message):
    """A RECORD worker finished painting for the current subject."""

    def __init__(
        self,
        document: MainDeckDocument,
        *,
        signature: str,
        active_card: str | None,
    ) -> None:
        """Initialize the loaded notification."""
        super().__init__()
        self.document = document
        self.signature = signature
        self.active_card = active_card


class RecordDeckView(CardDocumentView):
    """One RECORD card view that lives inside a VerticalScroll."""

    def __init__(self, **kwargs: Any) -> None:
        """Initialize the RECORD deck view."""
        super().__init__(DeckId.RECORD, **kwargs)
        self._current_subject_identity: object | None = None
        self._current_generation: int = 0
        self._current_preferred: str | None = None
        self._current_worker: Worker[RecordDeckLoadResult] | None = None
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
        archive_light_row: Any | None = None,
        bundle_path: str | None = None,
    ) -> None:
        """Show RECORD cards for ``agent``, loading off-thread on a miss.

        ``archive_light_row`` supplies Archive facts for a hydrated
        archived agent. ``bundle_path`` overrides the agent's own path
        when the caller already resolved one.
        """
        archive = None
        if archive_light_row is not None:
            try:
                archive = record_archive_facts_from_light_row(archive_light_row)
            except Exception:
                archive = None
        try:
            subject = record_subject_from_agent(
                agent,
                attempt_number=attempt_number,
                archive=archive,
                bundle_path=bundle_path,
            )
        except Exception:
            return
        self.show_subject(subject, generation=generation, preferred_card=preferred_card)

    def show_subject(
        self,
        subject: RecordSubject,
        *,
        generation: int = 0,
        preferred_card: str | None = None,
    ) -> None:
        """Show RECORD cards for a captured ``subject``, loading off-thread.

        Used for unreadable Archive entries and container rows that have
        no hydrated Agent, and as the shared paint path for
        :meth:`update_display`.
        """
        identity = subject.identity
        self._current_subject_identity = identity
        self._current_generation = generation
        self._current_preferred = preferred_card
        try:
            signature = record_cache_key(subject)
        except Exception:
            signature = ""
        try:
            cached = cached_record_result(identity, signature) if signature else None
        except Exception:
            cached = None
        if cached is not None and signature != self._painted_signature:
            self._paint_record_result(cached, preferred_card)
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

        def _fetch() -> RecordDeckLoadResult:
            return load_record_deck(subject, generation=generation)

        try:
            self._current_worker = self.run_worker(_fetch, thread=True)
        except Exception:
            return
        self._current_worker_subject = identity
        self._current_worker_generation = generation

    def show_empty(self) -> None:
        """Show the empty state."""
        self._current_subject_identity = None
        self._painted_signature = None
        self._has_displayed_content = False
        try:
            if self._current_worker is not None and self._current_worker.is_running:
                self._current_worker.cancel()
        except Exception:
            pass
        self.update(Text("No agent selected", style="dim italic"))

    def show_record_document(
        self,
        document: MainDeckDocument,
        preferred_card: str | None,
        block_mode: RenderMode | None = None,
    ) -> str | None:
        """Push ``document`` to the RECORD view; return the active card.

        ``block_mode`` carries the panel's decided block mode for the
        active card (always automatic: RECORD has no deck-view policy,
        so ``P`` never forces it). ``None`` renders the legacy whole
        card.
        """
        try:
            mode = decide_record_mode(len(document.cards))
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

    def get_record_text(self) -> str | None:
        """Return the active RECORD document as plain text (search/export)."""
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
        self.update(Text("Loading record…", style="dim italic"))

    def _paint_record_result(
        self, result: RecordDeckLoadResult, preferred_card: str | None
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
            shown = self.show_record_document(result.document, active_choice)
        except Exception:
            shown = None
        del shown
        try:
            active_card = self._active_card
        except Exception:
            active_card = None
        try:
            self.post_message(
                RecordDeckLoaded(
                    result.document,
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

    def _is_stale_result(self, result: RecordDeckLoadResult) -> bool:
        if result.subject_identity != self._current_subject_identity:
            return True
        return result.generation != self._current_generation

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        """Handle worker state changes, rejecting stale subjects."""
        if event.worker is not self._current_worker:
            return
        if event.state == WorkerState.SUCCESS:
            result = event.worker.result
            if not isinstance(result, RecordDeckLoadResult):
                return
            if self._is_stale_result(result):
                return
            self._paint_record_result(result, self._current_preferred)
        elif event.state == WorkerState.ERROR:
            if self._has_displayed_content:
                return
            self.update(Text("Record unavailable", style="dim italic"))
        elif event.state == WorkerState.CANCELLED:
            pass


__all__ = ["RecordDeckLoaded", "RecordDeckView"]

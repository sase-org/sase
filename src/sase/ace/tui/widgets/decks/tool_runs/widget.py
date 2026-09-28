"""``⚒ Runs`` deck widget (epic sase-1bt).

Thin :class:`DeckId.TOOLS` specialization of
:class:`~sase.ace.tui.widgets.decks.document_view.CardDocumentView` that
paints the cached node summary instantly, otherwise a loading line, then
loads through the node-summary LRU on a worker thread.
"""

from __future__ import annotations

import time
from typing import Any

from rich.text import Text
from textual.worker import Worker, WorkerState

from sase.ace.tui.tool_runs.deck import (
    DEFAULT_TOOL_RUNS_DETAIL_LEVEL,
    ToolRunsDetailLevel,
    coerce_tool_runs_detail_level,
    tool_run_display_bucket,
)
from sase.ace.tui.tool_runs.summaries import (
    cached_node_summary_for_selector,
    selector_for_agent,
)

from ..document_view import CardDocumentView
from ..main_document import MainDeckDocument
from ..model import DeckId, RenderMode
from ._shared import (
    cached_block_details,
    count_silent_rows,
    tool_runs_hint_numbers,
    tool_runs_render_width,
)
from .document import build_tool_runs_document
from .loader import load_tool_runs_deck
from .messages import ToolRunsDeckLoaded, ToolRunsDeckLoadResult
from .rows import tool_runs_cache_signature, tool_runs_rows_for_document
from .widget_live import ToolRunsLiveMixin


def _subject_key(agent: Any) -> object | None:
    """Return the document subject key for ``agent`` (identity or None)."""
    try:
        return getattr(agent, "identity", None)
    except Exception:
        return None


class ToolRunsDeckView(ToolRunsLiveMixin, CardDocumentView):
    """One ``⚒ Runs`` card view that lives inside a VerticalScroll."""

    def __init__(self, **kwargs: Any) -> None:
        """Initialize the Runs deck view."""
        super().__init__(DeckId.TOOLS, **kwargs)
        self._current_subject: object | None = None
        self._current_subject_identity: object | None = None
        self._current_generation: int = 0
        self._current_preferred: str | None = None
        self._current_worker: Worker[ToolRunsDeckLoadResult] | None = None
        self._current_worker_subject: object | None = None
        self._current_worker_generation: int = 0
        self._painted_signature: str | None = None
        self._has_displayed_content = False
        self._detail_level: ToolRunsDetailLevel = DEFAULT_TOOL_RUNS_DETAIL_LEVEL
        self._current_agent: Any | None = None
        self._live_timer: Any | None = None
        self._live_rows: tuple[Any, ...] = ()
        self._live_details: dict[str, Any] = {}
        self._live_total_runs: int = 0
        self._live_truncated: bool = False
        self._live_subject: object | None = None
        self._live_signature: str | None = None
        self._painted_store_token: Any | None = None

    @property
    def detail_level(self) -> ToolRunsDetailLevel:
        """Return the Runs card's own detail level (default STANDARD)."""
        return self._detail_level

    def expand_detail(self) -> bool:
        """Step the Runs detail level up; False when already FULL."""
        return self.set_detail_level(self._detail_level + 1)

    def collapse_detail(self) -> bool:
        """Step the Runs detail level down; False when already COMPACT."""
        return self.set_detail_level(self._detail_level - 1)

    def set_detail_level(self, level: ToolRunsDetailLevel | int) -> bool:
        """Set the Runs detail level and rebuild; False when unchanged."""
        next_level = coerce_tool_runs_detail_level(level)
        if next_level == self._detail_level:
            return False
        self._detail_level = next_level
        try:
            agent = self._current_agent
        except Exception:
            agent = None
        if agent is None:
            try:
                self.refresh()
            except Exception:
                pass
            return True
        try:
            self.update_display(
                agent,
                generation=self._current_generation,
                preferred_card=self._current_preferred,
            )
        except Exception:
            try:
                self.refresh()
            except Exception:
                pass
        return True

    def update_display(
        self,
        agent: Any,
        *,
        attempt_number: int | None = None,
        generation: int = 0,
        preferred_card: str | None = None,
        force: bool = False,
    ) -> None:
        """Show the ``⚒ Runs`` card for ``agent``, loading off-thread.

        ``force`` skips the cached fast path and reloads on a worker;
        the live tick uses it to re-fetch details only when the glance
        store token drifted (plan §4.8).
        """
        subject = _subject_key(agent)
        identity = getattr(agent, "identity", None)
        self._current_agent = agent
        self._current_subject = subject
        self._current_subject_identity = identity
        self._current_generation = generation
        self._current_preferred = preferred_card
        if attempt_number is not None:
            self.show_empty()
            return
        try:
            selector = selector_for_agent(agent)
        except Exception:
            selector = None
        if selector is None:
            self.show_empty()
            return
        try:
            summary = None if force else cached_node_summary_for_selector(selector)
        except Exception:
            summary = None
        if summary is not None:
            try:
                from sase.ace.tui.tool_runs.snapshot import get_snapshot

                snapshot = get_snapshot()
                snapshot_runs = tuple(snapshot.runs or ()) if snapshot else ()
            except Exception:
                snapshot_runs = ()
            rows, total, truncated = tool_runs_rows_for_document(summary, snapshot_runs)
            live_ids = tuple(
                str(getattr(row, "run_id", ""))
                for row in rows
                if tool_run_display_bucket(row) == "running"
            )
            signature = tool_runs_cache_signature(
                selector.key, total, live_ids, truncated
            )
            if signature and signature == self._painted_signature and not force:
                return
            try:
                store_token = snapshot.store_token if snapshot else None
            except Exception:
                store_token = None
            now_s = time.time()
            self._paint_tool_runs_result(
                ToolRunsDeckLoadResult(
                    subject_identity=identity,
                    generation=generation,
                    signature=signature,
                    document=build_tool_runs_document(
                        rows,
                        subject=subject,
                        digest=signature,
                        total_runs=total,
                        truncated=truncated,
                        details=cached_block_details(rows, store_token),
                        level=self._detail_level,
                        width=tool_runs_render_width(self),
                        now_s=now_s,
                        hint_numbers=tool_runs_hint_numbers(self),
                    ),
                    runs=rows,
                    total_runs=total,
                    truncated=truncated,
                    live_count=len(live_ids),
                    silent_count=count_silent_rows(rows, now_s),
                ),
                preferred_card,
                store_token=store_token,
            )
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

        def _fetch() -> ToolRunsDeckLoadResult:
            try:
                level = self._detail_level
            except Exception:
                level = DEFAULT_TOOL_RUNS_DETAIL_LEVEL
            try:
                width = tool_runs_render_width(self)
            except Exception:
                width = 100
            try:
                hints = tool_runs_hint_numbers(self)
            except Exception:
                hints = None
            return load_tool_runs_deck(
                agent,
                subject=subject,
                subject_identity=identity,
                generation=generation,
                level=level,
                width=width,
                hint_numbers=hints,
            )

        try:
            self._current_worker = self.run_worker(_fetch, thread=True)
        except Exception:
            return
        self._current_worker_subject = identity
        self._current_worker_generation = generation

    def show_empty(self) -> None:
        """Show the empty state."""
        self._current_agent = None
        self._current_subject = None
        self._current_subject_identity = None
        self._painted_signature = None
        self._has_displayed_content = False
        self._clear_live_state()
        try:
            self._stop_live_timer()
        except Exception:
            pass
        try:
            if self._current_worker is not None and self._current_worker.is_running:
                self._current_worker.cancel()
        except Exception:
            pass
        self.update(Text("No tool runs for this node", style="dim italic"))

    def show_tool_runs_document(
        self,
        document: MainDeckDocument,
        preferred_card: str | None,
        block_mode: RenderMode | None = None,
    ) -> str | None:
        """Push ``document`` to the Runs view; return the active card.

        The Runs card is always paged: Tools never spreads and ``P``
        stays a no-op.
        """
        try:
            return self.show_document(
                document,
                preferred_card=preferred_card,
                mode=RenderMode.PAGED,
                block_mode=block_mode,
            )
        except TypeError:
            try:
                return self.show_document(
                    document,
                    preferred_card=preferred_card,
                    mode=RenderMode.PAGED,
                )
            except Exception:
                return None
        except Exception:
            return None

    def get_tool_runs_text(self) -> str | None:
        """Return the Runs document as plain text (search/export)."""
        from sase.ace.tui.tool_runs.deck import tool_runs_card_search_text

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
                parts.append(tool_runs_card_search_text(card.renderables))
            return "\n".join(parts).strip() or None
        except Exception:
            return None

    def _show_loading(self) -> None:
        if self._has_displayed_content:
            return
        self.update(Text("Loading tool runs…", style="dim italic"))

    def _paint_tool_runs_result(
        self,
        result: ToolRunsDeckLoadResult,
        preferred_card: str | None,
        *,
        store_token: Any | None = None,
    ) -> None:
        try:
            ids = tuple(result.document.card_ids)
        except Exception:
            ids = ()
        # Reconcile block cursors on every paint: a follower lands on a
        # new arrival (arrival dots stay empty), a parked reader holds
        # position and the arrival shows as a dot, and a settle keeps
        # the cursor on the same block id (plan §4.8).
        try:
            self._reconcile_block_cursors(
                result.document, new_subject=False, enabled=True
            )
        except Exception:
            pass
        if preferred_card is not None and preferred_card in ids:
            active_choice: str | None = preferred_card
        else:
            active_choice = ids[0] if ids else None
        try:
            self.show_tool_runs_document(result.document, active_choice)
        except Exception:
            pass
        try:
            active_card = self._active_card
        except Exception:
            active_card = None
        try:
            self.post_message(
                ToolRunsDeckLoaded(
                    result.document,
                    status="",
                    glyph="⚒",
                    signature=result.signature,
                    active_card=active_card,
                    n_runs=result.total_runs,
                    live=result.live_count > 0,
                    silent=result.silent_count > 0,
                )
            )
        except Exception:
            pass
        self._painted_signature = result.signature
        try:
            self._has_displayed_content = bool(ids)
        except Exception:
            self._has_displayed_content = False
        self._remember_live_state(result, store_token=store_token)
        try:
            self._sync_live_timer()
        except Exception:
            pass

    def _is_stale_result(self, result: Any) -> bool:
        if not isinstance(result, ToolRunsDeckLoadResult):
            return True
        if result.subject_identity != self._current_subject_identity:
            return True
        return result.generation != self._current_generation

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        """Handle worker state changes, rejecting stale subjects."""
        if event.worker is not self._current_worker:
            return
        if event.state == WorkerState.SUCCESS:
            result = event.worker.result
            if self._is_stale_result(result):
                return
            if not isinstance(result, ToolRunsDeckLoadResult):
                return
            self._paint_tool_runs_result(result, self._current_preferred)
        elif event.state == WorkerState.ERROR:
            if self._has_displayed_content:
                return
            self.update(Text("Tool runs unavailable", style="dim italic"))
        elif event.state == WorkerState.CANCELLED:
            pass


__all__ = ["ToolRunsDeckView"]

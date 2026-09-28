"""``⚒ Runs`` deck view with off-thread node-summary and block loaders.

Thin :class:`DeckId.TOOLS` specialization of
:class:`~sase.ace.tui.widgets.decks.document_view.CardDocumentView` that
paints the cached node summary instantly, otherwise a loading line, then
loads through the node-summary LRU on a worker thread. The same worker
loads each visible block's detail plus its bounded log tail through the
detail LRU; stale results are rejected by subject identity and detail
generation. Live in-place progress arrives with ``runs-card-live``.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

from rich.text import Text
from textual.message import Message
from textual.worker import Worker, WorkerState

from sase.ace.tui.tool_runs.deck import (
    DEFAULT_TOOL_RUNS_DETAIL_LEVEL,
    ToolRunsDetailLevel,
    coerce_tool_runs_detail_level,
    tool_run_display_bucket,
)
from sase.ace.tui.tool_runs.detail import (
    LoadedToolRunDetail,
    cached_tool_run_detail,
    load_tool_run_detail_blocking,
)
from sase.ace.tui.tool_runs.summaries import (
    cached_node_summary_for_selector,
    node_live_runs,
    resolve_tool_run_summary,
    selector_for_agent,
)

from ..document_view import CardDocumentView
from ..main_document import MainDeckDocument
from ..model import DeckId, RenderMode
from .document import build_tool_runs_document

log = logging.getLogger(__name__)


@dataclass
class ToolRunsDeckLoadResult:
    """One loaded ``⚒ Runs`` document for the current subject."""

    subject_identity: object | None
    generation: int
    signature: str
    document: MainDeckDocument
    runs: tuple[Any, ...]
    total_runs: int
    truncated: bool
    live_count: int
    silent_count: int


class ToolRunsDeckLoaded(Message):
    """A ToolRuns worker finished painting for the current subject."""

    def __init__(
        self,
        document: MainDeckDocument,
        *,
        status: str,
        glyph: str,
        signature: str,
        active_card: str | None,
        n_runs: int,
        live: bool,
        silent: bool,
    ) -> None:
        """Initialize the loaded notification."""
        super().__init__()
        self.document = document
        self.status = status
        self.glyph = glyph
        self.signature = signature
        self.active_card = active_card
        self.n_runs = n_runs
        self.live = live
        self.silent = silent


def tool_runs_cache_signature(
    selector_key: str, total_runs: int, live_ids: tuple[str, ...], truncated: bool
) -> str:
    """Return the stat-only signature for one painted Runs document."""
    return f"{selector_key}:{total_runs}:{','.join(live_ids)}:{int(truncated)}"


def tool_runs_rows_for_document(
    summary: Any, snapshot_runs: tuple[Any, ...] | list[Any] | None
) -> tuple[tuple[Any, ...], int, bool]:
    """Return ``(rows, total_runs, truncated)`` for one node summary.

    Merges the summary's settled history with the glance snapshot's
    live rows for the same selector, deduped by ``run_id`` and ordered
    oldest first so the cursor lands on the newest block.
    """
    history = list(getattr(summary, "runs", ()) or ())
    live_rows = list(getattr(summary, "live", ()) or ())
    if snapshot_runs:
        try:
            from sase.ace.tui.tool_runs.summaries import ToolRunSelector

            selector = ToolRunSelector(key=str(getattr(summary, "key", "") or ""))
            scoped = node_live_runs(tuple(snapshot_runs), selector)
        except Exception:
            scoped = ()
        seen_live = {str(getattr(run, "run_id", "")) for run in live_rows}
        for run in scoped:
            run_id = str(getattr(run, "run_id", "") or "")
            if run_id and run_id not in seen_live:
                live_rows.append(run)
                seen_live.add(run_id)
    seen: set[str] = set()
    merged: list[Any] = []
    for row in (*history, *live_rows):
        run_id = str(getattr(row, "run_id", "") or "")
        if not run_id or run_id in seen:
            continue
        seen.add(run_id)
        merged.append(row)
    try:
        merged.sort(key=lambda row: int(getattr(row, "created_ts", 0) or 0))
    except Exception:
        pass
    try:
        total = max(int(getattr(summary, "total_runs", 0) or 0), len(merged))
    except (TypeError, ValueError):
        total = len(merged)
    try:
        truncated = bool(getattr(summary, "truncated", False))
    except Exception:
        truncated = False
    return (tuple(merged), total, truncated)


def _tool_runs_render_width(view: Any) -> int:
    """Return the block render width for *view* (narrow-safe, never raises)."""

    try:
        width = int(view.size.width or 0)
    except Exception:
        width = 0
    return width if width > 0 else 100


def _tool_runs_hint_numbers(view: Any) -> dict[str, int] | None:
    """Return mapped run-id → ``v`` hint numbers while hint mode is active.

    Single source of truth is the app's ``_hint_mappings``; the tail
    header shows a ``[N]`` marker only for targets mapped right now.
    Never raises.
    """

    try:
        app = view.app
    except Exception:
        return None
    try:
        if not bool(getattr(app, "_hint_mode_active", False)):
            return None
        mappings = getattr(app, "_hint_mappings", None)
    except Exception:
        return None
    if not mappings:
        return None
    try:
        from sase.ace.tui.tool_runs.hints import run_id_from_hint_target

        numbers: dict[str, int] = {}
        for number, target in dict(mappings).items():
            run_id = run_id_from_hint_target(target)
            if run_id and run_id not in numbers:
                numbers[run_id] = int(number)
    except Exception:
        return None
    return numbers or None


def _cached_block_details(
    rows: tuple[Any, ...] | list[Any],
    store_token: Any | None,
) -> dict[str, LoadedToolRunDetail]:
    """Return LRU-cached details for *rows* (memory-only, never raises)."""

    details: dict[str, LoadedToolRunDetail] = {}
    for row in rows or ():
        run_id = str(getattr(row, "run_id", "") or "")
        if not run_id:
            continue
        try:
            hit = cached_tool_run_detail(run_id, row, store_token)
        except Exception:
            hit = None
        if hit is not None:
            details[run_id] = hit
    return details


def _load_block_details(
    rows: tuple[Any, ...] | list[Any],
    store_token: Any | None,
    *,
    is_current: Any | None = None,
) -> dict[str, LoadedToolRunDetail]:
    """Load every row's detail plus tail on a worker thread (never raises).

    Settled hits never re-read; live rows refetch only when the store
    token drifted (their LRU key carries the token). ``is_current``
    rejects the whole batch when the subject moved on mid-load.
    """

    details: dict[str, LoadedToolRunDetail] = {}
    for row in rows or ():
        run_id = str(getattr(row, "run_id", "") or "")
        if not run_id:
            continue
        try:
            loaded = load_tool_run_detail_blocking(
                run_id, row, store_token, is_current=is_current
            )
        except Exception:
            loaded = None
        if loaded is None:
            if is_current is not None:
                try:
                    if not is_current():
                        return details
                except Exception:
                    return details
            continue
        details[run_id] = loaded
    return details


class ToolRunsDeckView(CardDocumentView):
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
    ) -> None:
        """Show the ``⚒ Runs`` card for ``agent``, loading off-thread."""
        from sase.ace.tui.tool_runs.flag import tool_runs_enabled

        if not tool_runs_enabled():
            return
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
            summary = cached_node_summary_for_selector(selector)
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
            if signature and signature == self._painted_signature:
                return
            try:
                store_token = snapshot.store_token if snapshot else None
            except Exception:
                store_token = None
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
                        details=_cached_block_details(rows, store_token),
                        level=self._detail_level,
                        width=_tool_runs_render_width(self),
                        hint_numbers=_tool_runs_hint_numbers(self),
                    ),
                    runs=rows,
                    total_runs=total,
                    truncated=truncated,
                    live_count=len(live_ids),
                    silent_count=0,
                ),
                preferred_card,
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
                width = _tool_runs_render_width(self)
            except Exception:
                width = 100
            try:
                hints = _tool_runs_hint_numbers(self)
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
        self, result: ToolRunsDeckLoadResult, preferred_card: str | None
    ) -> None:
        try:
            ids = tuple(result.document.card_ids)
        except Exception:
            ids = ()
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


def _empty_tool_runs_result(
    *,
    subject: object | None,
    subject_identity: object | None,
    generation: int,
    selector_key: str = "",
) -> ToolRunsDeckLoadResult:
    """Return an empty (no runs) load result for one subject."""
    signature = tool_runs_cache_signature(selector_key, 0, (), False)
    return ToolRunsDeckLoadResult(
        subject_identity=subject_identity,
        generation=generation,
        signature=signature,
        document=build_tool_runs_document((), subject=subject, digest=signature),
        runs=(),
        total_runs=0,
        truncated=False,
        live_count=0,
        silent_count=0,
    )


def load_tool_runs_deck(
    agent: Any,
    *,
    subject: object | None,
    subject_identity: object | None,
    generation: int,
    level: ToolRunsDetailLevel | int = DEFAULT_TOOL_RUNS_DETAIL_LEVEL,
    width: int = 100,
    hint_numbers: dict[str, int] | None = None,
) -> ToolRunsDeckLoadResult:
    """Load one ``⚒ Runs`` document on a worker thread; never raise.

    The same worker call loads each visible block's detail plus its
    bounded log tail through the detail LRU (§3.5.3).
    """
    try:
        selector = selector_for_agent(agent)
        selector_key = selector.key if selector is not None else ""
    except Exception:
        selector_key = ""
    try:
        summary = resolve_tool_run_summary(agent)
    except Exception as exc:
        log.debug("ToolRuns deck load failed, keeping last state: %s", exc)
        summary = None
    if summary is None:
        return _empty_tool_runs_result(
            subject=subject,
            subject_identity=subject_identity,
            generation=generation,
            selector_key=selector_key,
        )
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
    try:
        selector = selector_for_agent(agent)
        selector_key = selector.key if selector is not None else ""
    except Exception:
        selector_key = ""
    signature = tool_runs_cache_signature(selector_key, total, live_ids, truncated)
    now = time.time()
    silent = 0
    try:
        from sase.tool.view_vocabulary import is_silent

        for row in rows:
            if tool_run_display_bucket(row) != "running":
                continue
            last_activity = getattr(row, "last_activity_ts", None)
            if last_activity is None:
                last_activity = getattr(row, "created_ts", 0)
            if isinstance(last_activity, bool) or not isinstance(
                last_activity, (int, float)
            ):
                continue
            try:
                if is_silent(float(last_activity), now):
                    silent += 1
            except (TypeError, ValueError):
                continue
    except Exception:
        silent = 0
    try:
        store_token = snapshot.store_token if snapshot else None
    except Exception:
        store_token = None
    details = _load_block_details(rows, store_token)
    try:
        render_width = max(20, int(width))
    except (TypeError, ValueError):
        render_width = 100
    return ToolRunsDeckLoadResult(
        subject_identity=subject_identity,
        generation=generation,
        signature=signature,
        document=build_tool_runs_document(
            rows,
            subject=subject,
            digest=signature,
            total_runs=total,
            truncated=truncated,
            details=details,
            level=level,
            width=render_width,
            hint_numbers=hint_numbers,
        ),
        runs=rows,
        total_runs=total,
        truncated=truncated,
        live_count=len(live_ids),
        silent_count=silent,
    )


def _subject_key(agent: Any) -> object | None:
    """Return the document subject key for ``agent`` (identity or None)."""
    try:
        return getattr(agent, "identity", None)
    except Exception:
        return None


__all__ = [
    "ToolRunsDeckLoaded",
    "ToolRunsDeckLoadResult",
    "ToolRunsDeckView",
    "load_tool_runs_deck",
    "tool_runs_cache_signature",
    "tool_runs_rows_for_document",
]

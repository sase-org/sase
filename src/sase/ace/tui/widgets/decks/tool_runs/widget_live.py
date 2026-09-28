"""Live 1 Hz repaint mixin for the ``⚒ Runs`` deck view (epic sase-1bt).

``runs-card-live`` reuses FINAL's live gate: a pure 1 Hz repaint
updates elapsed and bar growth from the cached detail plus ``now`` —
no stat, no SQLite open, no log read — while the card is visible and
its run is live. Detail is re-fetched only when the glance store token
drifts.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from sase.ace.tui.tool_runs.deck import ToolRunsDetailLevel

from ._shared import (
    cached_block_details,
    tool_runs_hint_numbers,
    tool_runs_render_width,
)
from .document import build_tool_runs_document
from .live import (
    TOOL_RUNS_LIVE_TICK_SECONDS,
    live_detail_drifted,
    live_host_visible,
    live_navigating,
    live_typing,
    tool_runs_rows_have_live,
    want_live_tick,
)

log = logging.getLogger(__name__)


class ToolRunsLiveMixin:
    """Live-tick state and 1 Hz pure repaint for ``ToolRunsDeckView``.

    Expects the host class to provide ``_live_rows``, ``_live_details``,
    ``_live_total_runs``, ``_live_truncated``, ``_live_subject``,
    ``_live_signature``, ``_painted_store_token``, ``_current_agent``,
    ``_current_generation``, ``_current_preferred``, ``_current_worker``,
    ``_live_timer``, ``_detail_level``, ``_active_card``,
    ``_reconcile_block_cursors`` and ``show_tool_runs_document``.
    """

    _live_rows: tuple[Any, ...]
    _live_details: dict[str, Any]
    _live_total_runs: int
    _live_truncated: bool
    _live_subject: object | None
    _live_signature: str | None
    _painted_store_token: Any | None
    _current_agent: Any | None
    _current_generation: int
    _current_preferred: str | None
    _current_worker: Any | None
    _live_timer: Any | None
    _detail_level: ToolRunsDetailLevel

    def _remember_live_state(
        self, result: Any, *, store_token: Any | None = None
    ) -> None:
        """Snapshot the painted rows for the 1 Hz pure repaint (no I/O)."""

        try:
            rows = tuple(result.runs or ())
        except Exception:
            rows = ()
        try:
            cached = cached_block_details(rows, store_token)
        except Exception:
            cached = {}
        self._live_rows = rows
        self._live_details = dict(cached)
        try:
            self._live_total_runs = int(result.total_runs)
        except (TypeError, ValueError):
            self._live_total_runs = len(rows)
        try:
            self._live_truncated = bool(result.truncated)
        except Exception:
            self._live_truncated = False
        self._live_subject = self._current_subject  # type: ignore[attr-defined]
        self._live_signature = result.signature
        self._painted_store_token = store_token

    def _clear_live_state(self) -> None:
        """Forget the painted rows so the tick stands down."""

        self._live_rows = ()
        self._live_details = {}
        self._live_total_runs = 0
        self._live_truncated = False
        self._live_subject = None
        self._live_signature = None
        self._painted_store_token = None

    def _sync_live_timer(self) -> None:
        """Start the 1 Hz tick while a live run is painted, else stop it."""

        try:
            if tool_runs_rows_have_live(self._live_rows):
                self._start_live_timer()  # type: ignore[attr-defined]
            else:
                self._stop_live_timer()  # type: ignore[attr-defined]
        except Exception:
            pass

    def _start_live_timer(self) -> None:
        """Start the 1 Hz live repaint (idempotent)."""

        try:
            if self._live_timer is not None:
                return
            self._live_timer = self.set_interval(  # type: ignore[attr-defined]
                TOOL_RUNS_LIVE_TICK_SECONDS,
                self._on_live_timer,  # type: ignore[attr-defined]
            )
        except Exception:
            self._live_timer = None

    def _stop_live_timer(self) -> None:
        """Stop the 1 Hz live repaint."""

        timer, self._live_timer = self._live_timer, None
        try:
            if timer is not None:
                timer.stop()
        except Exception:
            pass

    def on_unmount(self) -> None:
        """Stop the live tick when the view tears down."""

        try:
            self._stop_live_timer()  # type: ignore[attr-defined]
        except Exception:
            pass

    def _live_worker_running(self) -> bool:
        """Return whether a deck reload worker is still running."""

        try:
            worker = self._current_worker
            return bool(worker is not None and worker.is_running)
        except Exception:
            return False

    def _on_live_timer(self) -> None:
        """Thin 1 Hz pump callback: gate synchronously, repaint purely."""

        try:
            agent = self._current_agent
            if agent is None or not tool_runs_rows_have_live(self._live_rows):
                self._stop_live_timer()  # type: ignore[attr-defined]
                return
            if not want_live_tick(
                visible=live_host_visible(self),
                has_live=True,
                navigating=live_navigating(self),
                typing=live_typing(self),
                in_flight=self._live_worker_running(),  # type: ignore[attr-defined]
            ):
                return
            try:
                from sase.ace.tui.tool_runs.snapshot import get_snapshot

                snapshot = get_snapshot()
                snapshot_token = snapshot.store_token if snapshot is not None else None
            except Exception:
                snapshot_token = None
            if live_detail_drifted(snapshot_token, self._painted_store_token):
                self._live_reload_on_drift()  # type: ignore[attr-defined]
                return
            self._live_pure_repaint()  # type: ignore[attr-defined]
        except Exception:
            log.debug("tool runs live tick failed", exc_info=True)

    def _live_reload_on_drift(self) -> None:
        """Reload the card on a worker after glance drift (I/O only here)."""

        try:
            agent = self._current_agent
            if agent is None:
                return
            if self._live_worker_running():  # type: ignore[attr-defined]
                return
            self.update_display(  # type: ignore[attr-defined]
                agent,
                generation=self._current_generation,
                preferred_card=self._current_preferred,
                force=True,
            )
        except Exception:
            log.debug("tool runs drift reload failed", exc_info=True)

    def _live_pure_repaint(self) -> None:
        """Repaint elapsed and bar growth from cached state (never I/O).

        Rebuilds the document from the painted rows and their cached
        details with a fresh clock. The per-second digest forces the
        render past the render-key dedupe; block ids are stable, so a
        parked cursor holds and a settle keeps its block in place.
        """

        try:
            rows = tuple(self._live_rows or ())
            if not rows:
                return
            now_s = time.time()
            signature = self._live_signature or ""
            try:
                width = tool_runs_render_width(self)
            except Exception:
                width = 100
            try:
                hints = tool_runs_hint_numbers(self)
            except Exception:
                hints = None
            document = build_tool_runs_document(
                rows,
                subject=self._live_subject,
                digest=f"{signature}:{int(now_s)}",
                total_runs=self._live_total_runs,
                truncated=self._live_truncated,
                details=dict(self._live_details),
                level=self._detail_level,
                width=width,
                now_s=now_s,
                hint_numbers=hints,
            )
            try:
                self._reconcile_block_cursors(  # type: ignore[attr-defined]
                    document, new_subject=False, enabled=True
                )
            except Exception:
                pass
            try:
                self.show_tool_runs_document(document, self._active_card)  # type: ignore[attr-defined]
            except Exception:
                pass
        except Exception:
            log.debug("tool runs pure repaint failed", exc_info=True)


__all__ = ["ToolRunsLiveMixin"]

"""Files-deck behavior extracted from ``panel.py``."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from textual.containers import VerticalScroll
from textual.worker import Worker, WorkerState

from ..file_panel import (
    FileLineCountChanged,
    FileListChanged,
    FileVisibilityChanged,
)
from ..file_panel._spread_probe import FilesSpreadProbe
from ..llm_calls_panel import LLMCallsVisibilityChanged
from .availability import DeckAvailability
from .model import DeckId, RenderMode


class DeckPanelFilesMixin:
    """Files rendering, probes, and message handlers for a deck panel."""

    _files_probe_agent: Any | None
    _files_pending_probe: Any | None

    if TYPE_CHECKING:

        def __getattr__(self, name: str) -> Any: ...

    def _refresh_files_mode_for_shown(self) -> None:
        if self._deck is not DeckId.FILES:
            return
        rows, width = self._spread_viewport(DeckId.FILES)
        if rows <= 0 or width <= 0:
            return
        # Recompute from stored pages without I/O when possible.
        if self._files_probe_pages:
            total = self._recompute_files_rows(width)
            spread_max = self._spread_settings_max_screens()
            from .render_mode import spread_budget_rows as _budget

            budget = _budget(spread_max, rows)
            if (
                self._files_probe_exceeded
                and total is not None
                and total > budget * 1.10
            ):
                self._schedule_files_probe(reason="resize-exceeded")
                return
            same = True
            new_mode = self._decide_files_mode(
                same_subject=same,
                total_rows=total,
                has_solo=False,
                card_count=len(self._files_probe_slots) or 1,
            )
            old_mode = self._render_mode.get(DeckId.FILES, RenderMode.PAGED)
            if new_mode is not old_mode:
                self._apply_files_transition(new_mode)
            return
        self._schedule_files_probe(reason="resize-no-pages")

    def _schedule_files_probe(self, *, reason: str = "") -> None:
        del reason
        try:
            file_view = self.file_view
            slots = tuple(getattr(file_view, "_file_list", ()))
        except Exception:
            return
        if not slots:
            return
        try:
            agent = getattr(file_view, "_current_agent", None)
            subject = getattr(file_view, "_anchor_agent_identity", None)
        except Exception:
            agent = None
            subject = None
        rows, width = self._spread_viewport(DeckId.FILES)
        if rows <= 0 or width <= 0:
            return
        spread_max = self._spread_settings_max_screens()
        if spread_max <= 0:
            if self._render_mode.get(DeckId.FILES) is not RenderMode.PAGED:
                self._render_mode[DeckId.FILES] = RenderMode.PAGED
                self._sync_files_views()
                self.refresh_chrome()
            return
        from .render_mode import spread_budget_rows as _budget

        budget = _budget(spread_max, rows)
        stop_after = budget * 1.10
        current_slots = self._files_probe_slots
        current_subject = self._files_probe_subject
        if (
            tuple(slots) == tuple(current_slots)
            and subject == current_subject
            and self._files_probe_pages
        ):
            return
        # New subject starts paged until the probe lands.
        if subject != current_subject:
            self._render_mode[DeckId.FILES] = RenderMode.PAGED
            self._sync_files_views()
            self.refresh_chrome()
        probe_agent = agent
        probe_slots = tuple(slots)
        probe_subject = subject
        probe_width = width
        probe_stop = stop_after

        def _task() -> Any:
            from ..file_panel._spread_probe import probe_files_spread

            return probe_files_spread(
                probe_agent,
                probe_slots,
                width=probe_width,
                stop_after_rows=probe_stop,
            )

        try:
            worker = self.run_worker(
                _task,
                thread=True,
                exclusive=True,
                exit_on_error=False,
                group=f"deck-files-spread-{self._panel_index}",
            )
            # Attach completion via worker state change.
            self._files_probe_agent = probe_agent
            self._files_pending_probe = (
                worker,
                probe_agent,
                probe_slots,
                probe_subject,
            )
        except Exception:
            # Fall back to a synchronous bounded probe.
            try:
                from ..file_panel._spread_probe import probe_files_spread

                probe = probe_files_spread(
                    probe_agent, probe_slots, width=width, stop_after_rows=stop_after
                )
                self._on_files_probe_result(probe, probe_agent, probe_slots, subject)
            except Exception:
                pass

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        """Apply the Files spread probe once its worker reaches a terminal state.

        ``Worker.StateChanged`` carries only ``worker`` and ``state``, so the
        gate is the state itself. Events for any other worker on this panel are
        ignored untouched, and a probe that errored or was cancelled leaves the
        deck in whatever mode it already had (paged for a new subject).
        """
        pending = self._files_pending_probe
        if pending is None:
            return
        worker, agent, slots, subject = pending
        if event.worker is not worker:
            return
        if event.state is WorkerState.SUCCESS:
            self._files_pending_probe = None
            result = event.worker.result
            if isinstance(result, FilesSpreadProbe):
                self._on_files_probe_result(result, agent, slots, subject)
        elif event.state in (WorkerState.ERROR, WorkerState.CANCELLED):
            self._files_pending_probe = None

    def _on_files_probe_result(
        self, probe: Any, agent: Any, slots: tuple[str, ...], subject: Any
    ) -> None:
        # Drop stale results.
        try:
            file_view = self.file_view
            current_slots = tuple(getattr(file_view, "_file_list", ()))
            current_subject = getattr(file_view, "_anchor_agent_identity", None)
            if tuple(slots) != tuple(current_slots) or subject != current_subject:
                return
        except Exception:
            pass
        self._files_probe_pages = tuple(probe.pages)
        self._files_probe_total = probe.total_rows
        self._files_probe_exceeded = bool(probe.exceeded)
        self._files_probe_bound = float(probe.bound)
        self._files_probe_subject = subject
        self._files_probe_slots = tuple(slots)
        self._files_probe_agent = agent
        same = True
        # Solo cards force paged.
        if probe.has_solo:
            total: int | None = None
        elif probe.exceeded:
            total = probe.total_rows
        else:
            total = probe.total_rows
        new_mode = self._decide_files_mode(
            same_subject=same,
            total_rows=total,
            has_solo=bool(probe.has_solo),
            card_count=len(slots),
        )
        old_mode = self._render_mode.get(DeckId.FILES, RenderMode.PAGED)
        # New subjects are already paged; only switch when the probe says spread.
        if new_mode is old_mode:
            self._mode_subject[DeckId.FILES] = subject
            return
        self._mode_subject[DeckId.FILES] = subject
        self._apply_files_transition(new_mode)

    def _apply_files_transition(self, new_mode: RenderMode) -> None:
        self._render_mode[DeckId.FILES] = new_mode
        self._sync_files_views()
        if new_mode is RenderMode.SPREAD:
            # Anchor the current page so the switch is viewport-stable.
            try:
                file_view = self.file_view
                current = int(getattr(file_view, "_current_file_index", 0))
            except Exception:
                current = 0
            try:
                scroll = self.query_one(
                    f"#agent-deck-panel-{self._panel_index}-files-scroll",
                    VerticalScroll,
                )
                paged_y = int(scroll.scroll_y)
            except Exception:
                paged_y = 0
            try:
                agent = getattr(self.file_view, "_current_agent", None)
                digest = None
                if agent is not None:
                    try:
                        digest = str(getattr(agent, "identity", None))
                    except Exception:
                        digest = None
                self.files_spread_view.show_pages(
                    self._files_probe_pages, digest=digest
                )
            except Exception:
                pass

            # Scroll after anchors are ready.
            def _restore() -> None:
                row = self._files_body_start(current)
                target = (row or 0) + paged_y if row is not None else paged_y
                try:
                    sc = self.query_one(
                        f"#agent-deck-panel-{self._panel_index}-files-scroll",
                        VerticalScroll,
                    )
                    sc.scroll_to(y=target, animate=False)
                except Exception:
                    pass
                try:
                    self.files_spread_view.enable_section_layout_reserve()
                except Exception:
                    pass

            try:
                self.call_after_refresh(_restore)
            except Exception:
                pass
        else:
            # Spread -> paged: select the spread active page without extra hop.
            try:
                active = self._files_spread_active_index()
            except Exception:
                active = 0
            try:
                scroll = self.query_one(
                    f"#agent-deck-panel-{self._panel_index}-files-scroll",
                    VerticalScroll,
                )
                spread_y = int(scroll.scroll_y)
            except Exception:
                spread_y = 0
            try:
                body = self._files_body_start(active)
                offset = max(0, spread_y - (body or 0)) if body is not None else 0
            except Exception:
                offset = 0
            try:
                self.file_view.select_file_index(active)
                self._file_index = active
                try:
                    self._file_source_label = self.file_view.current_source_label()
                except Exception:
                    pass
            except Exception:
                pass
            # Seed the paged anchor so the async static read restores to it.
            try:
                key = self.file_view._current_anchor_key()
                if key is not None:
                    self.file_view.seed_scroll_anchor(key, offset)
            except Exception:
                pass
        self.refresh_chrome()
        self._update_empty_state()

    def _notify_duplicate_ready(self, deck: DeckId) -> None:
        """Ask AgentDetail to re-feed sibling duplicates from cache."""
        try:
            node: object | None = self.parent
            for _ in range(5):
                if node is None:
                    break
                reload = getattr(node, "_reload_duplicate_deck_from_cache", None)
                if callable(reload):
                    try:
                        reload(deck, exclude_panel_index=self._panel_index)
                    except Exception:
                        pass
                    break
                node = getattr(node, "parent", None)
        except Exception:
            pass

    def handle_deck_file_list_changed(self, message: FileListChanged) -> None:
        self._file_count = message.file_count
        self._file_index = message.file_index
        try:
            self._file_source_label = self.file_view.current_source_label()
        except Exception:
            self._file_source_label = None
        self.refresh_chrome()
        self._update_empty_state()
        self._notify_duplicate_ready(DeckId.FILES)
        # Probe when the Files deck is shown and the list changes.
        if self._deck is DeckId.FILES:
            try:
                self._schedule_files_probe(reason="file-list")
            except Exception:
                pass
        message.stop()

    def handle_deck_file_line_count_changed(
        self, message: FileLineCountChanged
    ) -> None:
        self._file_visible_lines = message.visible_lines
        self._file_total_lines = message.total_lines
        self._file_capped = message.capped
        self.refresh_chrome()
        message.stop()

    def handle_deck_file_visibility_changed(
        self, message: FileVisibilityChanged
    ) -> None:
        self._availability[DeckId.FILES] = DeckAvailability(
            bool(message.has_file), message.file_count
        )
        self._file_count = message.file_count
        self._file_index = message.file_index
        self.refresh_chrome()
        self._update_empty_state()
        self._notify_duplicate_ready(DeckId.FILES)
        if self._deck is DeckId.FILES:
            try:
                self._schedule_files_probe(reason="visibility")
            except Exception:
                pass
        message.stop()

    def handle_deck_llm_calls_visibility_changed(
        self, message: LLMCallsVisibilityChanged
    ) -> None:
        self._tools_has_content = bool(message.has_llm_calls)
        self._availability[DeckId.TOOLS] = DeckAvailability(
            bool(message.has_llm_calls), None
        )
        self.refresh_chrome()
        self._update_empty_state()
        self._notify_duplicate_ready(DeckId.TOOLS)
        message.stop()


__all__ = ["DeckPanelFilesMixin"]

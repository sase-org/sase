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
from .model import DeckId, DeckView, RenderMode

_FILES_MEDIA_BLOCKED_TOAST = "Files stays paged: images and videos can't spread"


class DeckPanelFilesMixin:
    """Files rendering, probes, and message handlers for a deck panel."""

    _files_probe_agent: Any | None
    _files_pending_probe: Any | None
    _files_probe_complete: bool

    if TYPE_CHECKING:

        def __getattr__(self, name: str) -> Any: ...

    def _refresh_files_mode_for_shown(self) -> None:
        if self._deck is not DeckId.FILES:
            return
        try:
            policy = self.view_policy(DeckId.FILES)  # type: ignore[attr-defined]
        except Exception:
            policy = DeckView.AUTO
        if policy is DeckView.PAGE_CARDS:
            # Fixed page cards: always paged; never probe.
            try:
                if self._render_mode.get(DeckId.FILES) is not RenderMode.PAGED:
                    self._render_mode[DeckId.FILES] = RenderMode.PAGED
                    self._sync_files_views()
                    self.refresh_chrome()
            except Exception:
                pass
            return
        if policy is DeckView.SPREAD:
            try:
                complete = bool(self._files_probe_complete)
            except Exception:
                complete = False
            if not complete:
                try:
                    self._schedule_files_probe(reason="resize-needs-complete")
                except Exception:
                    pass
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
            policy = self.view_policy(DeckId.FILES)  # type: ignore[attr-defined]
        except Exception:
            policy = DeckView.AUTO
        try:
            file_view = self.file_view
            slots = tuple(getattr(file_view, "_file_list", ()))
        except Exception:
            return
        if not slots:
            return
        if policy is DeckView.PAGE_CARDS:
            # Fixed page cards skips the spread probe entirely.
            try:
                if self._render_mode.get(DeckId.FILES) is not RenderMode.PAGED:
                    self._render_mode[DeckId.FILES] = RenderMode.PAGED
                    self._sync_files_views()
                    self.refresh_chrome()
            except Exception:
                pass
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
        want_complete = policy is DeckView.SPREAD
        current_slots = self._files_probe_slots
        current_subject = self._files_probe_subject
        if (
            tuple(slots) == tuple(current_slots)
            and subject == current_subject
            and self._files_probe_pages
        ):
            try:
                complete = bool(self._files_probe_complete)
            except Exception:
                complete = False
            if not want_complete or complete:
                return
            # Fixed spread with only bounded pages: fall through to a
            # complete re-probe.
        # New subject starts paged until the probe lands.
        if subject != current_subject:
            self._files_probe_complete = False
            self._files_spread_pending = False  # type: ignore[attr-defined]
            self._files_spread_blocked = False  # type: ignore[attr-defined]
            self._files_media_toast_armed = False
            self._render_mode[DeckId.FILES] = RenderMode.PAGED
            self._sync_files_views()
            self.refresh_chrome()
        probe_agent = agent
        probe_slots = tuple(slots)
        probe_subject = subject
        probe_width = width
        probe_stop = stop_after
        probe_complete = want_complete

        def _task() -> Any:
            from ..file_panel._spread_probe import probe_files_spread

            return probe_files_spread(
                probe_agent,
                probe_slots,
                width=probe_width,
                stop_after_rows=probe_stop,
                complete=probe_complete,
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
            if want_complete:
                self._files_spread_pending = True  # type: ignore[attr-defined]
                self.refresh_chrome()
        except Exception:
            # Fall back to a synchronous probe of the same mode.
            try:
                from ..file_panel._spread_probe import probe_files_spread

                probe = probe_files_spread(
                    probe_agent,
                    probe_slots,
                    width=width,
                    stop_after_rows=stop_after,
                    complete=probe_complete,
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
        # Auto-probe pages count as complete only when the probe did not
        # exceed its bound and found no media.
        self._files_probe_complete = bool(
            getattr(probe, "complete", False)
            or (not probe.exceeded and not probe.has_solo)
        )
        try:
            policy = self.view_policy(DeckId.FILES)  # type: ignore[attr-defined]
        except Exception:
            policy = DeckView.AUTO
        if policy is DeckView.PAGE_CARDS:
            # A probe that landed after the switch to fixed page cards:
            # keep the pages, stay paged.
            self._files_spread_pending = False  # type: ignore[attr-defined]
            self._files_spread_blocked = False  # type: ignore[attr-defined]
            self._mode_subject[DeckId.FILES] = subject
            if self._render_mode.get(DeckId.FILES) is not RenderMode.PAGED:
                self._apply_files_transition(RenderMode.PAGED)
            else:
                self.refresh_chrome()
            return
        if policy is DeckView.SPREAD:
            self._files_spread_pending = False  # type: ignore[attr-defined]
            if probe.has_solo:
                # Media can never spread: stay paged and keep the fixed
                # preference for the next compatible subject.
                self._files_spread_blocked = True  # type: ignore[attr-defined]
                self._mode_subject[DeckId.FILES] = subject
                if self._files_media_toast_armed:
                    self._files_media_toast_armed = False
                    self._post_files_media_toast()
                self.refresh_chrome()
                return
            self._files_spread_blocked = False  # type: ignore[attr-defined]
            if not self._files_probe_complete:
                # A bounded probe that landed after the switch to fixed
                # spread: re-probe completely instead of spreading partial
                # pages.
                self._files_spread_pending = True  # type: ignore[attr-defined]
                self.refresh_chrome()
                self._schedule_files_probe(reason="spread-incomplete")
                return
            self._files_media_toast_armed = False
            self._mode_subject[DeckId.FILES] = subject
            if self._render_mode.get(DeckId.FILES) is not RenderMode.SPREAD:
                self._apply_files_transition(RenderMode.SPREAD)
            else:
                self.refresh_chrome()
            return
        self._files_spread_pending = False  # type: ignore[attr-defined]
        self._files_spread_blocked = False  # type: ignore[attr-defined]
        self._files_media_toast_armed = False
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

    def _post_files_media_toast(self) -> None:
        """Post the one-shot media toast for a user-initiated spread request."""
        try:
            notify = getattr(self, "notify", None)
            if callable(notify):
                notify(_FILES_MEDIA_BLOCKED_TOAST, severity="warning")
        except Exception:
            pass

    def _apply_files_view_change(self, *, user_initiated: bool = False) -> None:
        """Apply the stored Files policy, keeping the page and offset (D8)."""
        try:
            policy = self.view_policy(DeckId.FILES)  # type: ignore[attr-defined]
        except Exception:
            policy = DeckView.AUTO
        if policy is DeckView.SPREAD and user_initiated:
            self._files_media_toast_armed = True
        elif policy is not DeckView.SPREAD:
            self._files_media_toast_armed = False
        if policy is DeckView.PAGE_CARDS:
            self._files_spread_pending = False  # type: ignore[attr-defined]
            self._files_spread_blocked = False  # type: ignore[attr-defined]
            try:
                if self._render_mode.get(DeckId.FILES) is RenderMode.SPREAD:
                    self._apply_files_transition(RenderMode.PAGED)
                else:
                    self._sync_files_views()
                    self.refresh_chrome()
            except Exception:
                pass
            try:
                self._sync_view_cycle_available()  # type: ignore[attr-defined]
            except Exception:
                pass
            return
        if policy is DeckView.SPREAD:
            self._files_spread_blocked = False  # type: ignore[attr-defined]
            try:
                self._schedule_files_probe(reason="view-change")
            except Exception:
                pass
            try:
                pending = bool(self._files_spread_pending)  # type: ignore[attr-defined]
            except Exception:
                pending = False
            if not pending:
                # No probe in flight: complete pages are already stored,
                # so apply the fixed spread now instead of waiting.
                try:
                    complete = bool(self._files_probe_complete)
                except Exception:
                    complete = False
                try:
                    blocked = bool(  # type: ignore[attr-defined]
                        self._files_spread_blocked
                    )
                except Exception:
                    blocked = False
                try:
                    if (
                        complete
                        and not blocked
                        and self._render_mode.get(DeckId.FILES) is not RenderMode.SPREAD
                    ):
                        self._apply_files_transition(RenderMode.SPREAD)
                    else:
                        self.refresh_chrome()
                except Exception:
                    pass
            try:
                self._sync_view_cycle_available()  # type: ignore[attr-defined]
            except Exception:
                pass
            return
        # AUTO: clear fixed state and re-decide with today's bounded probe.
        self._files_spread_pending = False  # type: ignore[attr-defined]
        self._files_spread_blocked = False  # type: ignore[attr-defined]
        try:
            self._schedule_files_probe(reason="view-change-auto")
        except Exception:
            pass
        # The schedule above no-ops when stored pages are already current;
        # re-decide from them now so reset-to-AUTO never keeps a fixed mode.
        try:
            current = tuple(getattr(self.file_view, "_file_list", ()))
            anchor = getattr(self.file_view, "_anchor_agent_identity", None)
            fresh = (
                bool(self._files_probe_pages)
                and tuple(self._files_probe_slots) == tuple(current)
                and self._files_probe_subject == anchor
            )
        except Exception:
            fresh = False
            current = ()
        if fresh:
            try:
                new_mode = self._decide_files_mode(
                    same_subject=True,
                    total_rows=self._files_probe_total,
                    has_solo=False,
                    card_count=len(current) or 1,
                )
            except Exception:
                new_mode = None
            try:
                if new_mode is not None and new_mode is not self._render_mode.get(
                    DeckId.FILES, RenderMode.PAGED
                ):
                    self._apply_files_transition(new_mode)
                else:
                    self.refresh_chrome()
            except Exception:
                pass
        try:
            self._sync_view_cycle_available()  # type: ignore[attr-defined]
        except Exception:
            pass

    def _apply_files_transition(self, new_mode: RenderMode) -> None:
        self._files_transition_generation += 1  # type: ignore[attr-defined]
        generation = self._files_transition_generation  # type: ignore[attr-defined]
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
                if generation != self._files_transition_generation:  # type: ignore[attr-defined]
                    return
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
        try:
            from ...tool_runs.flag import tool_runs_enabled

            enabled = bool(tool_runs_enabled())
        except Exception:
            enabled = False
        if not enabled:
            self._availability[DeckId.TOOLS] = DeckAvailability(
                bool(message.has_llm_calls), None
            )
        else:
            self._availability[DeckId.TOOLS] = self._merged_tools_calls_availability(
                bool(message.has_llm_calls)
            )
            try:
                self._sync_tools_hosts()  # type: ignore[attr-defined]
            except Exception:
                pass
        self.refresh_chrome()
        self._update_empty_state()
        self._notify_duplicate_ready(DeckId.TOOLS)
        message.stop()

    def _merged_tools_calls_availability(self, has_calls: bool) -> DeckAvailability:
        """Return Tools availability with the LLM Calls card merged.

        The Runs card's part is preserved, never overwritten: the deck
        has content when either card does.
        """
        try:
            current = self._availability.get(DeckId.TOOLS)
        except Exception:
            current = None
        runs_count = 0
        has_runs = False
        if current is not None:
            try:
                runs_count = int(getattr(current, "runs_count", 0) or 0)
            except (TypeError, ValueError):
                runs_count = 0
            has_runs = runs_count > 0
        if not has_runs:
            try:
                has_runs = bool(self._tool_runs_document.cards)  # type: ignore[attr-defined]
            except Exception:
                has_runs = False
            if has_runs:
                try:
                    runs_count = len(self._tool_runs_document.cards[0].blocks)  # type: ignore[attr-defined]
                except Exception:
                    runs_count = 0
        try:
            calls_count: int | None = None
            if has_calls:
                try:
                    entries = getattr(self.tools_view, "_entries", None)  # type: ignore[attr-defined]
                    calls_count = len(entries) if entries is not None else None
                except Exception:
                    calls_count = None
                if calls_count is None and current is not None:
                    calls_count = getattr(current, "calls_count", None)
        except Exception:
            calls_count = None
        has_content: bool | None = True if (has_calls or has_runs) else False
        return DeckAvailability(
            has_content,
            calls_count,
            runs_count=runs_count if has_runs else 0,
            calls_count=calls_count,
        )


__all__ = ["DeckPanelFilesMixin"]

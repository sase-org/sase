"""Memory history rows and pager actions for the Memory pane.

Owns the phase memory-panel History integration behind :class:`MemoryPane`:
per-selection summary rows, off-thread summary loads, the history/changes
pager actions, explicit invalidation, and the quiet-time change probe.
Method calls reach the rest of the widget through ``self``;
this module imports no ``_``-prefixed names from its sibling pane modules.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from textual.worker import Worker, WorkerState

if TYPE_CHECKING:
    from textual.timer import Timer
    from textual.widget import Widget as _MixinBase
else:
    _MixinBase = object

#: Seconds between stat-only history change probes while the pane is visible.
_HISTORY_POLL_S = 5.0


class MemoryPaneHistoryMixin(_MixinBase):
    """History summaries and pager actions for ``MemoryPane``."""

    if TYPE_CHECKING:
        _accent: str
        _closed: bool
        _host_visible: bool
        _history_cache: dict[tuple[str, str, str], dict]
        _history_failed: set[tuple[str, str]]
        _history_latest: dict[tuple[str, str], dict]
        app: Any
        _history_open_worker: Worker[None] | None
        _history_poll_timer: Timer | None
        _history_probe_worker: Worker[tuple[str, str, bool]] | None
        _history_request: tuple[str, str] | None
        _history_worker: Worker[tuple[str, str, dict | None]] | None
        _loading: bool
        _ring: tuple[Any, ...]
        _scope_index: int

        def _after_history_landed(self, scope_key: str, selector: str) -> None: ...

        def _drop_diff_state_for_scope(self, scope_key: str) -> None: ...

        def _drop_time_state_for_scope(self, scope_key: str) -> None: ...

        def _history_diff_carry(self) -> tuple[str, str | None]: ...

        def _history_initial_revision(self) -> str: ...

        def _render_note_card(self) -> None: ...

        def _selected_row(self) -> Any | None: ...

    def _ace_history(self) -> Any | None:
        """Return the app-scoped history service, or ``None`` when unavailable."""
        try:
            from sase.ace.tui.memory_history import (
                AceMemoryHistory,
                ace_memory_history,
            )

            history = ace_memory_history(self.app)
            return history if isinstance(history, AceMemoryHistory) else None
        except Exception:
            return None

    def _history_key_for_node(
        self, node: Any | None
    ) -> tuple[str, str, Any, str] | None:
        """Return ``(scope_key, selector, panel_ref, selector)`` for *node*."""
        if node is None or not self._ring:
            return None
        try:
            from .memory_panel_history import selector_for_node

            selector = selector_for_node(node)
        except Exception:
            return None
        if not selector:
            return None
        ref = self._ring[self._scope_index]
        return (ref.key, selector, ref, selector)

    def _time_strip_snapshot_for_node(self, node: Any | None) -> Any | None:
        """Return the pinned-head snapshot without blocking.

        Notes, web descriptors, and strands all show the strip. Returns
        the last good timeline with a stale mark when the latest load
        failed, or ``None`` while the first load is still in flight
        (the strip shows ``indexing…``).
        """
        import time as _time

        from .memory_pane_time_strip import TimeStripSnapshot, subject_id_for_selector

        keyed = self._history_key_for_node(node)
        if keyed is None:
            return None
        scope_key, selector, _ref, _raw = keyed
        is_strand = bool(getattr(node, "strand", None) is not None)
        try:
            path_label = str(getattr(node, "identity", "") or selector)
            note = getattr(node, "note", None)
            if not is_strand and note is not None:
                relative = str(getattr(note, "relative_path", "") or "")
                if relative:
                    path_label = relative
        except Exception:
            path_label = str(selector)
        subject_id = subject_id_for_selector(selector, is_strand=is_strand)
        now_epoch = int(_time.time())
        cached = self._history_latest.get((scope_key, selector))
        failed = (scope_key, selector) in self._history_failed
        if cached is not None:
            return TimeStripSnapshot(
                subject_id=subject_id,
                path_label=path_label,
                timeline=dict(cached),
                now_epoch=now_epoch,
                failed=bool(failed),
            )
        if failed:
            return TimeStripSnapshot(
                subject_id=subject_id,
                path_label=path_label,
                timeline=None,
                now_epoch=now_epoch,
                failed=True,
            )
        self._ensure_history_load(scope_key, selector)
        return TimeStripSnapshot(
            subject_id=subject_id,
            path_label=path_label,
            timeline=None,
            now_epoch=now_epoch,
            failed=False,
        )

    def _time_strip_styles(self) -> Any:
        """Return the memoized kit styles for the current theme."""
        try:
            from .memory_pane_time_strip import get_time_strip_styles

            return get_time_strip_styles(self.app.current_theme)
        except Exception:
            return None

    def _ensure_history_load(self, scope_key: str, selector: str) -> None:
        if not self._ring or self._loading:
            return
        request = (scope_key, selector)
        if request in self._history_failed:
            return
        if self._history_request == request:
            if (
                self._history_worker is not None
                and not self._history_worker.is_finished
            ):
                return
        try:
            ref = self._ring[self._scope_index]
        except IndexError:
            return
        if ref.key != scope_key:
            return
        self._history_request = request
        if self._history_worker is not None and not self._history_worker.is_finished:
            self._history_worker.cancel()

        def task() -> tuple[str, str, dict | None]:
            try:
                from .memory_panel_history import (
                    fetch_history_summary,
                    history_cache_key,
                )

                history = self._ace_history()
                if history is None:
                    return (scope_key, selector, None)
                scope = history.scope_for_ref(ref)
                if scope is None:
                    return (scope_key, selector, None)
                summary = fetch_history_summary(history, scope, selector)
                if summary is not None:
                    try:
                        self._history_cache[history_cache_key(summary)] = summary
                    except Exception:
                        pass
                return (scope_key, selector, summary)
            except Exception:
                return (scope_key, selector, None)

        self._history_worker = self.run_worker(
            task,
            thread=True,
            exclusive=True,
            group="memory-panel-history",
            exit_on_error=False,
        )

    def _on_history_state_changed(self, event: Worker.StateChanged) -> None:
        if event.state != WorkerState.SUCCESS:
            if event.state == WorkerState.CANCELLED:
                self._history_request = None
            else:
                # A worker error settles like an unavailable summary: keep
                # the retry row instead of respawning on every render.
                if self._history_request is not None:
                    self._history_failed.add(self._history_request)
                self._history_request = None
            return
        result = event.worker.result
        if not isinstance(result, tuple) or len(result) != 3:
            return
        scope_key, selector, summary = result
        self._history_request = None
        if summary is not None:
            self._history_latest[(scope_key, selector)] = summary
            self._history_failed.discard((scope_key, selector))
        else:
            # Fail-open: keep the retry row, and remember the miss so
            # renders stop respawning workers for it. Scope reloads retry.
            self._history_failed.add((scope_key, selector))
        if self._closed or not self.is_mounted:
            return
        current = self._history_key_for_node(self._selected_row())
        if current is None:
            return
        if (current[0], current[1]) != (scope_key, selector):
            return  # Stale: the user moved before this load landed.
        try:
            self._after_history_landed(scope_key, selector)
        except Exception:
            pass
        try:
            self._render_note_card()
        except Exception:
            pass

    def _history_explicit_base(self) -> bool:
        """Return whether the pager hand-off carries an explicit base.

        Notes hand-offs never do; the Timeline lens overrides this to
        carry its ``b`` base when the cursor sits on now.
        """
        return False

    def _history_invalidate_scope_key(
        self, scope_key: str, *, clear_failures: bool = False
    ) -> None:
        """Drop memoized history for a scope after writes, publish, or ``r``.

        Clears the app-scoped timeline/subject/feed memos, forgets
        memoized scope objects (so a new ``AGENTS.md`` is picked up),
        and purges the pane's rendered snapshots so the next render
        refetches. With *clear_failures*, settled-unavailable rows
        retry as well.
        """
        history = self._ace_history()
        if history is not None:
            try:
                history.invalidate_scope(scope_key)
            except Exception:
                pass
            try:
                history.service.forget_scopes()
            except Exception:
                pass
        for key in [key for key in self._history_latest if key[0] == scope_key]:
            self._history_latest.pop(key, None)
        try:
            self._drop_time_state_for_scope(scope_key)
        except Exception:
            pass
        try:
            self._drop_diff_state_for_scope(scope_key)
        except Exception:
            pass
        if clear_failures:
            for key in [key for key in self._history_failed if key[0] == scope_key]:
                self._history_failed.discard(key)

    def _start_history_poll(self) -> None:
        """Start the quiet-time stat-only change probe (about every 5 s)."""
        try:
            self._stop_history_poll()
            self._history_poll_timer = self.set_interval(
                _HISTORY_POLL_S, self._history_poll_tick
            )
        except Exception:
            self._history_poll_timer = None

    def _stop_history_poll(self) -> None:
        """Stop the quiet-time change probe."""
        timer = getattr(self, "_history_poll_timer", None)
        self._history_poll_timer = None
        if timer is not None:
            try:
                timer.stop()
            except Exception:
                pass

    def _history_poll_tick(self) -> None:
        """Probe the stat-only change token off-thread; refetch on drift."""
        if self._closed or not self.is_mounted or not self._host_visible:
            return
        if self._loading or not self._ring:
            return
        try:
            gate = getattr(self.app, "_nav_gate", None)
            if gate is not None and gate.is_navigating():
                return
        except Exception:
            pass
        if self._history_worker is not None and not self._history_worker.is_finished:
            return
        if (
            self._history_probe_worker is not None
            and not self._history_probe_worker.is_finished
        ):
            return
        keyed = self._history_key_for_node(self._selected_row())
        if keyed is None:
            return
        scope_key, selector, ref, _raw = keyed
        history = self._ace_history()
        if history is None:
            return

        def task() -> tuple[str, str, bool]:
            try:
                scope = history.scope_for_ref(ref)
                if scope is None:
                    return (scope_key, selector, False)
                return (
                    scope_key,
                    selector,
                    bool(history.poll_changed(scope, selector)),
                )
            except Exception:
                return (scope_key, selector, False)

        self._history_probe_worker = self.run_worker(
            task,
            thread=True,
            exclusive=True,
            group="memory-panel-history-probe",
            exit_on_error=False,
        )

    def _on_history_probe_state_changed(self, event: Worker.StateChanged) -> None:
        if event.state != WorkerState.SUCCESS:
            return
        result = event.worker.result
        if not isinstance(result, tuple) or len(result) != 3:
            return
        scope_key, selector, changed = result
        if not isinstance(changed, bool) or not changed:
            return
        if self._closed or not self.is_mounted:
            return
        current = self._history_key_for_node(self._selected_row())
        if current is None or (current[0], current[1]) != (scope_key, selector):
            return  # Stale: the user moved before this probe landed.
        history = self._ace_history()
        if history is not None:
            try:
                history.invalidate_subject(scope_key, selector)
            except Exception:
                pass
        self._history_latest.pop((scope_key, selector), None)
        self._ensure_history_load(scope_key, selector)

    def action_open_history(self) -> None:
        """Open the selection in the pager at the card's exact pin and view."""
        from .memory_panel_history import selector_for_node

        node = self._selected_row()
        if node is None or not self._ring:
            return
        selector = selector_for_node(node)
        if not selector:
            return
        ref = self._ring[self._scope_index]
        scope_key = ref.key
        identity = node.identity

        async def _open() -> None:
            import asyncio

            def _build() -> Any | None:
                try:
                    from sase.memory.history.pager_provider import (
                        build_history_document,
                    )
                    from sase.memory.history.cli_history import (
                        translate_history_selector,
                    )
                    from pathlib import Path

                    history = self._ace_history()
                    if history is None:
                        return None
                    service = history.service
                    scope = history.scope_for_ref(ref)
                    if scope is None:
                        return None
                    try:
                        core_selector = translate_history_selector(
                            selector, Path(str(getattr(scope, "repo_root", ".")))
                        )
                    except Exception:
                        core_selector = selector
                    try:
                        carried_view, carried_base = self._history_diff_carry()
                    except Exception:
                        carried_view, carried_base = "read", None
                    try:
                        explicit = bool(self._history_explicit_base())
                    except Exception:
                        explicit = False
                    return build_history_document(
                        scope=scope,
                        subject=core_selector,
                        initial_revision=self._history_initial_revision(),
                        view=carried_view,
                        compare_base=carried_base,
                        explicit_base=explicit,
                        service=service,
                        title=selector,
                    )
                except Exception:
                    return None

            document = await asyncio.to_thread(_build)
            if document is None:
                # This async worker already runs on the app thread, so
                # notify directly: call_from_thread would raise here.
                self.notify(
                    "could not open history for this selection",
                    severity="error",
                )
                return
            # Drop the open when the selection moved while loading.
            try:
                current = self._selected_row()
            except Exception:
                current = None
            if current is None or current.identity != identity:
                return
            if not self._ring or self._ring[self._scope_index].key != scope_key:
                return
            if self._closed or not self.is_mounted:
                return

            try:
                from sase.pager.screen import PagerScreen
                from sase.pager.syntax_policy import (
                    pager_syntax_session_from_config,
                )

                session = pager_syntax_session_from_config()
                self.app.push_screen(
                    PagerScreen(
                        document,
                        links_enabled=True,
                        syntax_enabled=session.syntax_enabled,
                    )
                )
            except Exception as exc:
                self.notify(f"Could not open pager: {exc}", severity="error")

        self._history_open_worker = self.run_worker(
            _open(),
            exclusive=True,
            group="memory-panel-history-open",
            exit_on_error=False,
        )

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

#: Settled-unavailable History row text. The last good snapshot stays out
#: of the way: the row names the retry key instead of showing ``…`` forever.
_HISTORY_UNAVAILABLE_TEXT = "history unavailable · r retry"


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
        # Web descriptor rows carry no History row: only notes and strands.
        if (
            getattr(node, "web", None) is not None
            and getattr(node, "strand", None) is None
        ):
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

    def _history_renderable_for_node(self, node: Any | None) -> Any | None:
        """Return the History row value without blocking.

        Returns ``None`` when the row is omitted (web rows or no
        selection). Otherwise returns the cached summary, a dim
        ``history unavailable · r retry`` once a load settles
        unavailable, or a dim ``…`` placeholder while scheduling the
        off-thread load.
        """
        from rich.text import Text

        keyed = self._history_key_for_node(node)
        if keyed is None:
            return None
        scope_key, selector, _ref, _raw = keyed
        cached = self._history_latest.get((scope_key, selector))
        if cached is not None:
            try:
                from .memory_panel_history import history_value_text

                return history_value_text(cached, accent=self._accent)
            except Exception:
                return Text("…", style="dim")
        if (scope_key, selector) in self._history_failed:
            return Text(_HISTORY_UNAVAILABLE_TEXT, style="dim")
        self._ensure_history_load(scope_key, selector)
        return Text("…", style="dim")

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
            self._render_note_card()
        except Exception:
            pass

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
        """Open the selected note, web, or strand in the pager at now."""
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
                    return build_history_document(
                        scope=scope,
                        subject=core_selector,
                        initial_revision="now",
                        view="read",
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

    def action_open_changes(self) -> None:
        """Open the cross-file changes feed for the enabled scopes."""
        if not self._ring:
            return
        ring = tuple(self._ring)

        async def _open_feed() -> None:
            import asyncio

            def _build_feed() -> Any | None:
                try:
                    from sase.memory.history.feed_document import (
                        build_feed_document,
                        parse_feed_subject_target,
                        resolve_feed_subject,
                    )
                    from sase.pager.targets import LinkResolution

                    from .memory_panel_history import history_scopes_for_ring

                    history = self._ace_history()
                    if history is None:
                        return None
                    service = history.service
                    scopes = history_scopes_for_ring(ring, service)
                    if not scopes:
                        return None
                    feed = service.feed(
                        scopes, since=None, limit=None, include_hidden=True
                    )
                    scopes_label = " + ".join(
                        str(getattr(scope, "scope_key", "") or "") for scope in scopes
                    )
                    result = build_feed_document(feed, scopes_label)
                    scopes_by_key = {
                        str(getattr(scope, "scope_key", "")): scope for scope in scopes
                    }

                    def _resolve_ref(
                        ref: str, *, context: Any | None = None
                    ) -> Any | None:
                        if parse_feed_subject_target(ref) is not None:
                            target = resolve_feed_subject(service, scopes_by_key, ref)
                            if target is not None:
                                return target
                            return LinkResolution(
                                unresolved_message=f"{ref} could not be resolved.",
                                retryable=False,
                            )
                        try:
                            from sase.pager.resolve import resolve_link

                            return resolve_link(ref, context=context)
                        except Exception as exc:
                            return LinkResolution(
                                unresolved_message=str(exc), retryable=False
                            )

                    def _refresh() -> Any | None:
                        try:
                            fresh = service.feed(
                                scopes,
                                since=None,
                                limit=None,
                                include_hidden=True,
                            )
                            return build_feed_document(fresh, scopes_label).document
                        except Exception:
                            return None

                    return (result.document, _resolve_ref, _refresh)
                except Exception:
                    return None

            built = await asyncio.to_thread(_build_feed)
            if built is None:
                # This async worker already runs on the app thread, so
                # notify directly: call_from_thread would raise here.
                self.notify(
                    "could not open the memory changes feed",
                    severity="error",
                )
                return
            if self._closed or not self.is_mounted:
                return

            try:
                from sase.pager.screen import PagerScreen
                from sase.pager.syntax_policy import (
                    pager_syntax_session_from_config,
                )

                document, resolve_ref, refresh = built
                session = pager_syntax_session_from_config()
                self.app.push_screen(
                    PagerScreen(
                        document,
                        links_enabled=True,
                        resolve_ref_fn=resolve_ref,
                        syntax_enabled=session.syntax_enabled,
                        refresh_document_fn=refresh,
                    )
                )
            except Exception as exc:
                self.notify(f"Could not open pager: {exc}", severity="error")

        self._history_open_worker = self.run_worker(
            _open_feed(),
            exclusive=True,
            group="memory-panel-history-open",
            exit_on_error=False,
        )

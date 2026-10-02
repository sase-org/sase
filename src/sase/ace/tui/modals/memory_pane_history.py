"""Memory history rows and pager actions for the Memory pane.

Owns the phase memory-panel History integration behind :class:`MemoryPane`:
per-selection summary rows, off-thread summary loads, and the history/changes
pager actions. Method calls reach the rest of the widget through ``self``;
this module imports no ``_``-prefixed names from its sibling pane modules.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from textual.worker import Worker, WorkerState

if TYPE_CHECKING:
    from textual.widget import Widget as _MixinBase
else:
    _MixinBase = object


class MemoryPaneHistoryMixin(_MixinBase):
    """History summaries and pager actions for ``MemoryPane``."""

    if TYPE_CHECKING:
        _accent: str
        _closed: bool
        _history_cache: dict[tuple[str, str, str], dict]
        _history_failed: set[tuple[str, str]]
        _history_latest: dict[tuple[str, str], dict]
        _history_open_worker: Worker[None] | None
        _history_request: tuple[str, str] | None
        _history_service: Any | None
        _history_worker: Worker[tuple[str, str, dict | None]] | None
        _loading: bool
        _ring: tuple[Any, ...]
        _scope_index: int

        def _render_note_card(self) -> None: ...

        def _selected_row(self) -> Any | None: ...

    def _history_service_or_none(self) -> Any | None:
        if self._history_service is not None:
            return self._history_service
        try:
            from sase.memory.history.service import HistoryService

            self._history_service = HistoryService()
            return self._history_service
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
        selection). Otherwise returns the cached summary or a dim
        ``…`` placeholder and schedules the off-thread load.
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
                    history_scope_for_panel_ref,
                )

                service = self._history_service_or_none()
                if service is None:
                    return (scope_key, selector, None)
                scope = history_scope_for_panel_ref(ref, service)
                if scope is None:
                    return (scope_key, selector, None)
                summary = fetch_history_summary(service, scope, selector)
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
                # the placeholder instead of respawning on every render.
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
            # Fail-open: keep the "…" placeholder, and remember the miss so
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

    def action_open_history(self) -> None:
        """Open the selected note, web, or strand in the pager at now."""
        from .memory_panel_history import (
            history_scope_for_panel_ref,
            selector_for_node,
        )

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

                    service = self._history_service_or_none()
                    if service is None:
                        return None
                    scope = history_scope_for_panel_ref(ref, service)
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

                    service = self._history_service_or_none()
                    if service is None:
                        return None
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

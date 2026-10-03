"""Notes-only inert keys and pager hand-off for the Changes lens."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .memory_pane_lens import LENS_NOTES

if TYPE_CHECKING:
    from textual.widget import Widget as _MixinBase
else:
    _MixinBase = object


class MemoryPaneChangesHandoffMixin(_MixinBase):
    """Keep Notes actions inert and open the cursor changeset in the pager."""

    if TYPE_CHECKING:
        _changes_all_scopes: bool
        _changes_cursor: int
        _changes_failed: tuple[str, ...]
        _changes_feed: dict[str, Any] | None
        _changes_filter: str
        _changes_generation: int
        _changes_limit: int
        _changes_listed: tuple[dict[str, Any], ...]
        _changes_loading: bool
        _changes_mark_worker: Any | None
        _changes_older: int
        _changes_review: tuple[Any, ...]
        _changes_scheduled: int
        _changes_scope_label: str
        _changes_sections: dict[tuple[str, str, str], str]
        _changes_section_failed: set[tuple[str, str, str]]
        _changes_total: int
        _changes_worker: Any | None
        _current_note: str | None
        _debouncer: Any | None
        _filter_text: str
        _lens: Any
        _lens_snapshot: Any | None
        _loading: bool
        _ring: tuple[Any, ...]
        _rows: tuple[Any, ...]
        _scope_index: int
        _selection_guard: Any
        app: Any
        is_mounted: bool
        from textual.widgets import OptionList as _OptionList  # noqa: F401

        def _ace_history(self) -> Any | None: ...
        def _changes_clear_state(self) -> None: ...
        def _changes_cursor_view(self) -> Any | None: ...

        _closed: bool

        def _lens_is_changes(self) -> bool: ...
        def _note_list(self) -> _OptionList: ...
        def notify(self, *args: Any, **kwargs: Any) -> Any: ...
        def run_worker(self, *args: Any, **kwargs: Any) -> Any: ...

    # --- Notes-only actions are inert or re-homed in the lens -----------------

    def action_first_note(self) -> None:
        """Jump to the first lens row inside the Changes lens."""
        if self._lens_is_changes():
            try:
                option_list = self._note_list()
                guard = self._selection_guard
                if guard is not None:
                    try:
                        guard.prepare("changes:0", 0)
                    except Exception:
                        pass
                option_list.highlighted = 0
            except Exception:
                pass
            return
        try:
            super().action_first_note()  # type: ignore[misc]
        except Exception:
            pass

    def action_last_note(self) -> None:
        """Jump to the last lens row inside the Changes lens."""
        if self._lens_is_changes():
            try:
                option_list = self._note_list()
                listed = tuple(getattr(self, "_changes_listed", ()))
                target = max(0, len(listed) - 1)
                guard = self._selection_guard
                if guard is not None:
                    try:
                        guard.prepare(f"changes:{target}", target)
                    except Exception:
                        pass
                option_list.highlighted = target
            except Exception:
                pass
            return
        try:
            super().action_last_note()  # type: ignore[misc]
        except Exception:
            pass

    def action_toggle_web(self) -> None:
        """Web expansion is a Notes action; inert in the Changes lens."""
        if self._lens_is_changes():
            return
        try:
            super().action_toggle_web()  # type: ignore[misc]
        except Exception:
            pass

    def action_next_strand(self) -> None:
        """Strand jumps are Notes actions; inert in the Changes lens."""
        if self._lens_is_changes():
            return
        try:
            super().action_next_strand()  # type: ignore[misc]
        except Exception:
            pass

    def action_prev_strand(self) -> None:
        """Strand jumps are Notes actions; inert in the Changes lens."""
        if self._lens_is_changes():
            return
        try:
            super().action_prev_strand()  # type: ignore[misc]
        except Exception:
            pass

    def action_next_link(self) -> None:
        """Link chips are Notes actions; inert in the Changes lens."""
        if self._lens_is_changes():
            return
        try:
            super().action_next_link()  # type: ignore[misc]
        except Exception:
            pass

    def action_prev_link(self) -> None:
        """Link chips are Notes actions; inert in the Changes lens."""
        if self._lens_is_changes():
            return
        try:
            super().action_prev_link()  # type: ignore[misc]
        except Exception:
            pass

    def action_toggle_body_filter(self) -> None:
        """Body-match scope is a Notes filter; inert in the Changes lens."""
        if self._lens_is_changes():
            return
        try:
            super().action_toggle_body_filter()  # type: ignore[misc]
        except Exception:
            pass

    def _on_scope_picked(self, key: str | None) -> None:
        """Leave the lens before switching to the picked scope."""
        if self._lens_is_changes():
            try:
                self._changes_clear_state()
                self._lens = LENS_NOTES
                self._lens_snapshot = None
            except Exception:
                pass
        try:
            super()._on_scope_picked(key)  # type: ignore[misc]
        except Exception:
            pass

    # --- pager hand-off ---------------------------------------------------------

    def _changes_open_at_cursor(self, subject_number: int | None = None) -> None:
        """Open the cursor changeset in the pager diff view (``⏎``/``l``/``H``)."""
        view = self._changes_cursor_view()
        if view is None:
            try:
                self.notify("no changeset under the cursor", severity="warning")
            except Exception:
                pass
            return
        try:
            authored = tuple(getattr(view, "authored", ()) or ())
        except Exception:
            authored = ()
        if subject_number is not None:
            if not 1 <= int(subject_number) <= len(authored):
                try:
                    self.notify("no subject with that number", severity="warning")
                except Exception:
                    pass
                return
            subject = authored[int(subject_number) - 1]
        else:
            if not authored:
                try:
                    self.notify(
                        "this changeset has no authored subjects", severity="warning"
                    )
                except Exception:
                    pass
                return
            subject = authored[0]
        try:
            scope_key = str(getattr(view, "scope_key", "") or "")
            selector = str(getattr(subject, "selector", "") or "")
            revision = str(getattr(subject, "revision", "") or "")
        except Exception:
            return
        if not selector or not revision:
            try:
                self.notify("this subject cannot be opened", severity="warning")
            except Exception:
                pass
            return
        try:
            history = self._ace_history()
        except Exception:
            history = None
        if history is None:
            try:
                self.notify("history unavailable · r retry", severity="warning")
            except Exception:
                pass
            return
        try:
            service = history.service
        except Exception:
            service = history
        scope = None
        try:
            from .memory_panel_history import history_scopes_for_ring  # noqa: PLC0415

            ring = tuple(getattr(self, "_ring", ()) or ())
            for candidate in history_scopes_for_ring(ring, service):
                if str(getattr(candidate, "scope_key", "")) == scope_key:
                    scope = candidate
                    break
        except Exception:
            scope = None
        if scope is None:
            try:
                self.notify("history unavailable · r retry", severity="warning")
            except Exception:
                pass
            return
        identity = f"{scope_key}:{selector}@{revision}"

        async def _open() -> None:
            import asyncio

            def _build() -> Any | None:
                try:
                    from sase.memory.history.pager_provider import (  # noqa: PLC0415
                        build_history_document,
                    )

                    return build_history_document(
                        scope=scope,
                        subject=selector,
                        initial_revision=revision,
                        view="diff",
                        service=service,
                        title=selector,
                    )
                except Exception:
                    return None

            document = await asyncio.to_thread(_build)
            if document is None:
                try:
                    self.notify(
                        "could not open history for this selection",
                        severity="error",
                    )
                except Exception:
                    pass
                return
            if not self._lens_is_changes():
                return
            current = self._changes_cursor_view()
            try:
                current_identity = (
                    f"{getattr(current, 'scope_key', '')}:"
                    f"{getattr(current.authored[0], 'selector', '') if getattr(current, 'authored', ()) else ''}"
                    if current is not None
                    else ""
                )
            except Exception:
                current_identity = ""
            _ = current_identity
            if self._closed or not self.is_mounted:
                return
            try:
                from sase.pager.screen import PagerScreen  # noqa: PLC0415
                from sase.pager.syntax_policy import (  # noqa: PLC0415
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
                try:
                    self.notify(f"Could not open pager: {exc}", severity="error")
                except Exception:
                    pass
            _ = identity

        try:
            self._changes_worker = self.run_worker(
                _open(),
                exclusive=True,
                group="memory-panel-changes-open",
                exit_on_error=False,
            )
        except Exception:
            pass

    def _changes_open_subject_number(self, number: int) -> None:
        """Open subject N of the cursor changeset (``.N``)."""
        if not self._lens_is_changes():
            return
        try:
            armed = bool(getattr(self, "_pending_numbered_link", False))
        except Exception:
            armed = False
        if not armed:
            return  # Bare digits stay inert; the `.` prefix arms them.
        self._changes_open_at_cursor(subject_number=int(number))


__all__ = [
    "MemoryPaneChangesHandoffMixin",
]

"""Refetch, mark-reviewed, and filter for the Changes lens."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .memory_pane_review import (
    ScopeReview,
    changeset_is_unreviewed,
    entries_by_scope,
    feed_newest_commit,
    mark_reviewed_toast,
    review_entries,
)

if TYPE_CHECKING:
    from textual.widget import Widget as _MixinBase
else:
    _MixinBase = object


class MemoryPaneChangesMarkMixin(_MixinBase):
    """Persist review watermarks and filter every fetched changeset."""

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

        def _ace_history(self) -> Any | None: ...
        def _changes_cursor_view(self) -> Any | None: ...
        def _changes_fetch(self) -> None: ...
        def _changes_rebuild_rows(self) -> None: ...
        def _changes_scopes_for_lens(
            self,
        ) -> tuple[list[Any], tuple[str, ...], str]: ...
        def _lens_is_changes(self) -> bool: ...
        def notify(self, *args: Any, **kwargs: Any) -> Any: ...
        def _render_note_card(self) -> None: ...
        def _render_changes_rail(self) -> None: ...
        def run_worker(self, *args: Any, **kwargs: Any) -> Any: ...
        def _update_header(self) -> None: ...

    # --- refetch, review, filter ----------------------------------------------

    def action_refresh(self) -> None:
        """``r`` refetches the feed inside the Changes lens."""
        if self._lens_is_changes():
            try:
                self._changes_generation = (
                    int(getattr(self, "_changes_generation", 0) or 0) + 1
                )
                self._changes_sections = {}
                self._changes_section_failed = set()
                self._changes_loading = True
                self._render_changes_rail()
            except Exception:
                pass
            self._changes_fetch()
            return
        try:
            super().action_refresh()  # type: ignore[misc]
        except Exception:
            pass

    def action_mark_reviewed(self) -> None:
        """``m`` marks the shown scope(s) reviewed (Changes lens only).

        Clears the dots optimistically, persists the watermark
        off-thread through each shown scope's newest changeset, then
        toasts ``marked N changesets reviewed · <scope>``. A persist
        failure restores the dots and toasts instead. Never marks
        from Notes, the Timeline lens, or a card: opening the lens
        marks nothing, and neither does this key anywhere else.
        """
        if not self._lens_is_changes():
            return
        scopes, _failed, label = self._changes_scopes_for_lens()
        if not scopes:
            try:
                self.notify("nothing to mark reviewed", severity="warning")
            except Exception:
                pass
            return
        previous = tuple(getattr(self, "_changes_review", ()) or ())
        indexed = entries_by_scope(previous)
        listed = tuple(getattr(self, "_changes_listed", ()) or ())
        views = tuple(
            row.get("view")
            for row in listed
            if isinstance(row, dict)
            and row.get("kind") == "changeset"
            and row.get("view") is not None
        )
        targets: list[tuple[Any, str, str, int]] = []
        for scope in scopes:
            try:
                key = str(getattr(scope, "scope_key", "") or "")
            except Exception:
                continue
            if not key:
                continue
            entry = indexed.get(key)
            newest = ""
            try:
                newest = str(entry.newest_commit or "") if entry is not None else ""
            except Exception:
                newest = ""
            if not newest:
                newest = feed_newest_commit(views, key)
            if not newest:
                continue
            if entry is not None and entry.has_watermark:
                try:
                    count = max(0, int(entry.new_count or 0))
                except (TypeError, ValueError):
                    count = 0
            else:
                count = sum(
                    1
                    for row in listed
                    if isinstance(row, dict)
                    and row.get("kind") == "changeset"
                    and row.get("view") is not None
                    and str(getattr(row.get("view"), "scope_key", "") or "") == key
                    and changeset_is_unreviewed(row.get("view"), indexed)
                )
            targets.append((scope, key, newest, count))
        if not targets:
            try:
                self.notify("no changesets to mark reviewed", severity="warning")
            except Exception:
                pass
            return
        optimistic: dict[str, ScopeReview] = dict(indexed)
        for _scope, key, newest, _count in targets:
            try:
                latest = max(
                    [
                        int(getattr(view, "committer_time", 0) or 0)
                        for view in views
                        if str(getattr(view, "scope_key", "") or "") == key
                    ]
                    + [0]
                )
            except Exception:
                latest = 0
            old = optimistic.get(key)
            try:
                stamp = int(getattr(old, "watermark_time", 0) or 0) if old else 0
            except (TypeError, ValueError):
                stamp = 0
            optimistic[key] = ScopeReview(
                scope_key=key,
                new_count=0,
                watermark_time=max(stamp, latest),
                has_watermark=True,
                newest_commit=newest,
            )
        self._changes_review = tuple(optimistic.values())
        try:
            self._render_changes_rail()
            self._update_header()
        except Exception:
            pass
        try:
            all_scopes = bool(getattr(self, "_changes_all_scopes", False))
        except Exception:
            all_scopes = False
        total = sum(count for _, _, _, count in targets)
        toast_label = "all scopes" if all_scopes else str(label or "")
        try:
            generation = int(getattr(self, "_changes_generation", 0) or 0)
        except (TypeError, ValueError):
            generation = 0

        async def _mark() -> None:
            import asyncio

            def _persist() -> Any:
                try:
                    history = self._ace_history()
                    if history is None:
                        return None
                    service = history.service
                except Exception:
                    return None
                try:
                    for scope, _key, through, _count in targets:
                        service.mark_reviewed(scope, through)
                except Exception as exc:
                    return exc
                try:
                    return service.review_state(
                        [scope for scope, _k, _t, _c in targets]
                    )
                except Exception:
                    return True

            outcome = await asyncio.to_thread(_persist)
            failed = outcome is None or isinstance(outcome, BaseException)
            try:
                live = self._lens_is_changes() and (
                    int(getattr(self, "_changes_generation", 0) or 0) == generation
                )
            except (TypeError, ValueError):
                live = False
            if not failed and isinstance(outcome, dict) and live:
                # Confirm with core's exact post-mark state: new
                # changesets may have landed while the mark persisted.
                try:
                    self._changes_review = review_entries(outcome)
                    self._render_changes_rail()
                    self._update_header()
                except Exception:
                    pass
            elif failed:
                if live:
                    # Roll back to the pre-mark dots.
                    try:
                        self._changes_review = previous
                        self._render_changes_rail()
                        self._update_header()
                    except Exception:
                        pass
                try:
                    self.notify("could not mark reviewed", severity="error")
                except Exception:
                    pass
                return
            try:
                self.notify(mark_reviewed_toast(toast_label, total))
            except Exception:
                pass
            try:
                host = getattr(self, "_host", None)
                refresh = getattr(host, "refresh_memory_badge", None)
                if callable(refresh):
                    refresh()
            except Exception:
                pass

        try:
            self._changes_mark_worker = self.run_worker(
                _mark(),
                exclusive=True,
                group="memory-panel-changes-mark",
                exit_on_error=False,
            )
        except Exception:
            pass

    def on_input_changed(self, event: Any) -> None:
        """Route the ``/`` filter to the lens rows inside the Changes lens."""
        if not self._lens_is_changes():
            return
        try:
            from .memory_panel_state import _FILTER_INPUT_ID  # noqa: PLC0415

            if getattr(event.input, "id", None) == _FILTER_INPUT_ID:
                try:
                    event.prevent_default()
                    event.stop()
                except Exception:
                    pass
                self._apply_changes_filter(str(event.value or ""))
        except Exception:
            pass

    def _apply_changes_filter(self, pattern: str) -> None:
        """Filter every fetched changeset; the Notes filter is untouched."""
        try:
            self._changes_filter = pattern
        except Exception:
            pass
        try:
            keep = self._changes_cursor_view()
            keep_key = (
                (getattr(keep, "scope_key", ""), getattr(keep, "commit", ""))
                if keep is not None
                else None
            )
            self._changes_rebuild_rows()
            if keep_key is not None:
                for index, row in enumerate(
                    tuple(getattr(self, "_changes_listed", ()))
                ):
                    if not isinstance(row, dict) or row.get("kind") != "changeset":
                        continue
                    view = row.get("view")
                    if (
                        getattr(view, "scope_key", ""),
                        getattr(view, "commit", ""),
                    ) == keep_key:
                        self._changes_cursor = index
                        break
            self._render_changes_rail()
            self._render_note_card()
        except Exception:
            pass
        try:
            self._update_header()
        except Exception:
            pass


__all__ = [
    "MemoryPaneChangesMarkMixin",
]

"""Day-grouped changeset rows and feed fetching for the Changes lens."""

from __future__ import annotations

import datetime
from typing import TYPE_CHECKING, Any

from ._memory_pane_changes_shared import CHANGES_ROW_PREFIX, MORE_ROW_ID
from .memory_pane_review import review_entries

if TYPE_CHECKING:
    from textual.widget import Widget as _MixinBase
else:
    _MixinBase = object


def _changes_row_id(commit: str, scope_key: str) -> str:
    """Return the stable rail id for one changeset row."""
    digest = (commit or "")[:12]
    return f"{CHANGES_ROW_PREFIX}{scope_key}:{digest}"


def _changes_day_label(day_key: str, day_title: str, *, now_epoch: int = 0) -> str:
    """Return ``Today``/``Yesterday``/weekday title for a day group."""
    try:
        today = datetime.datetime.fromtimestamp(
            now_epoch or datetime.datetime.now().timestamp()
        ).strftime("%Y-%m-%d")
    except Exception:
        return day_title
    if day_key == today:
        return "Today"
    try:
        yesterday = (
            datetime.datetime.fromtimestamp(
                now_epoch or datetime.datetime.now().timestamp()
            )
            - datetime.timedelta(days=1)
        ).strftime("%Y-%m-%d")
    except Exception:
        return day_title
    if day_key == yesterday:
        return "Yesterday"
    return day_title


def _changes_lens_rows(
    feed: dict[str, Any] | None,
    *,
    query: str = "",
    limit: int = 100,
    now_epoch: int = 0,
) -> tuple[tuple[dict[str, Any], ...], int, int, int]:
    """Return ``(listed, total_visible, older_count, regen_folded)``.

    *listed* mixes disabled day headers, selectable changeset rows,
    per-day regen count rows, and one trailing window-extension row
    when the window is bounded. Day headers are disabled options so
    ``j``/``k`` skip them. Never raises.
    """
    try:
        from sase.memory.history.feed_model import (  # noqa: PLC0415
            FEED_WINDOW,
            dedupe_changesets,
            filter_changesets,
            flatten_visible,
            group_feed,
            window_changesets,
        )
    except Exception:
        return ((), 0, 0, 0)
    if not isinstance(feed, dict):
        return ((), 0, 0, 0)
    try:
        days = group_feed(feed)
    except Exception:
        return ((), 0, 0, 0)
    try:
        visible = dedupe_changesets(flatten_visible(days))
        total = len(visible)
    except Exception:
        return ((), 0, 0, 0)
    try:
        filtered = filter_changesets(visible, query)
    except Exception:
        filtered = visible
    try:
        bound = int(limit) if limit else FEED_WINDOW
    except (TypeError, ValueError):
        from sase.memory.history.feed_model import FEED_WINDOW as _W  # noqa: PLC0415

        bound = _W
    try:
        shown, older = window_changesets(filtered, bound)
    except Exception:
        shown, older = tuple(filtered), 0
    shown_keys = {(view.scope_key, view.commit) for view in shown}
    listed: list[dict[str, Any]] = []
    regen_folded = 0
    for day in days:
        day_views = [
            view for view in day.visible if (view.scope_key, view.commit) in shown_keys
        ]
        if not day_views and not day.hidden:
            continue
        if day_views:
            listed.append(
                {
                    "kind": "day",
                    "id": f"{CHANGES_ROW_PREFIX}day:{day.key}",
                    "key": day.key,
                    "title": _changes_day_label(
                        day.key, day.title, now_epoch=now_epoch
                    ),
                }
            )
            for view in day_views:
                listed.append(
                    {
                        "kind": "changeset",
                        "id": _changes_row_id(view.commit, view.scope_key),
                        "view": view,
                    }
                )
        if day.hidden:
            listed.append(
                {
                    "kind": "regen",
                    "id": f"{CHANGES_ROW_PREFIX}regen:{day.key}",
                    "key": day.key,
                    "count": len(day.hidden),
                }
            )
            regen_folded += len(day.hidden)
    if older:
        listed.append({"kind": "more", "id": MORE_ROW_ID, "older": older})
    return (tuple(listed), total, older, regen_folded)


def _changes_row_is_selectable(row: dict[str, Any] | None) -> bool:
    """Return whether a lens row carries a changeset (cursor stops here)."""
    return isinstance(row, dict) and row.get("kind") == "changeset"


class MemoryPaneChangesFeedMixin(_MixinBase):
    """Build Changes-lens rows from the shared feed model and fetch them."""

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
        def _lens_is_changes(self) -> bool: ...
        def notify(self, *args: Any, **kwargs: Any) -> Any: ...
        def _render_note_card(self) -> None: ...
        def _render_changes_rail(self) -> None: ...
        def run_worker(self, *args: Any, **kwargs: Any) -> Any: ...
        def _update_footer(self) -> None: ...
        def _update_header(self) -> None: ...

    # --- scopes -----------------------------------------------------------

    def _changes_scopes_for_lens(self) -> tuple[list[Any], tuple[str, ...], str]:
        """Return ``(scopes, failed_names, label)`` for the lens feed query."""
        try:
            from .memory_panel_history import (  # noqa: PLC0415
                history_scopes_for_ring,
            )
        except Exception:
            return ([], (), "")
        try:
            history = self._ace_history()
        except Exception:
            return ([], (), "")
        if history is None:
            return ([], (), "")
        try:
            service = history.service
        except Exception:
            service = history
        ring = tuple(getattr(self, "_ring", ()) or ())
        if not ring:
            return ([], (), "")
        try:
            all_scopes = bool(getattr(self, "_changes_all_scopes", False))
        except Exception:
            all_scopes = False
        if all_scopes:
            scopes = history_scopes_for_ring(ring, service)
            failed: list[str] = []
            try:
                built = {str(getattr(scope, "scope_key", "")) for scope in scopes}
                for ref in ring:
                    key = str(getattr(ref, "key", "") or "")
                    if key and key not in built:
                        failed.append(key)
            except Exception:
                pass
            label = "all scopes"
            return (scopes, tuple(failed), label)
        try:
            index = int(getattr(self, "_scope_index", 0) or 0) % max(1, len(ring))
        except Exception:
            index = 0
        scopes = history_scopes_for_ring((ring[index],), service)
        if not scopes:
            try:
                label = str(getattr(ring[index], "key", "") or "")
            except Exception:
                label = ""
            return ([], (label,) if label else (), label)
        try:
            label = str(getattr(scopes[0], "scope_key", "") or "")
        except Exception:
            label = ""
        return (scopes, (), label)

    # --- fetch / rows -----------------------------------------------------

    def _changes_fetch(self) -> None:
        """Fetch the whole feed once off-thread, then paint the window."""
        try:
            generation = int(getattr(self, "_changes_generation", 0) or 0)
        except Exception:
            generation = 0
        scopes, failed, label = self._changes_scopes_for_lens()
        try:
            self._changes_failed = tuple(failed)
            self._changes_scope_label = str(label or "")
        except Exception:
            pass
        if not scopes:
            try:
                self._changes_loading = False
                self._changes_feed = {"changesets": []}
                self._changes_rebuild_rows()
                self._render_changes_rail()
                self._render_note_card()
                self._update_header()
            except Exception:
                pass
            return

        async def _load() -> None:
            import asyncio

            def _query() -> Any:
                try:
                    history = self._ace_history()
                    if history is None:
                        return None
                    return history.feed(list(scopes))
                except Exception as exc:
                    return exc

            def _query_review() -> Any:
                try:
                    history = self._ace_history()
                    if history is None:
                        return None
                    return history.service.review_state(list(scopes))
                except Exception:
                    return None

            feed = await asyncio.to_thread(_query)
            review = await asyncio.to_thread(_query_review)
            if not self._lens_is_changes():
                return
            if int(getattr(self, "_changes_generation", 0) or 0) != generation:
                return  # Stale: the user left or refetched meanwhile.
            if isinstance(feed, BaseException):
                try:
                    self.notify(f"changes unavailable · {feed}", severity="warning")
                except Exception:
                    pass
                feed = {"changesets": []}
            if not isinstance(feed, dict):
                feed = {"changesets": []}
            try:
                self._changes_feed = dict(feed)
                self._changes_loading = False
                if isinstance(review, dict):
                    # Keep last good on failure: an unreadable store must
                    # not clear the dots the lens already showed.
                    self._changes_review = review_entries(review)
                self._changes_rebuild_rows()
                self._render_changes_rail()
                self._render_note_card()
                self._update_header()
                self._update_footer()
            except Exception:
                pass

        try:
            self._changes_loading = True
            self._changes_worker = self.run_worker(
                _load(),
                exclusive=True,
                group="memory-panel-changes-load",
                exit_on_error=False,
            )
        except Exception:
            pass

    def _changes_rebuild_rows(self) -> None:
        """Rebuild listed rows from the fetched feed, filter, and window."""
        import time as _time  # noqa: PLC0415

        feed = getattr(self, "_changes_feed", None)
        query = str(getattr(self, "_changes_filter", "") or "")
        try:
            limit = int(getattr(self, "_changes_limit", 100) or 100)
        except (TypeError, ValueError):
            limit = 100
        try:
            now_epoch = int(_time.time())
        except Exception:
            now_epoch = 0
        listed, total, older, _regen = _changes_lens_rows(
            feed if isinstance(feed, dict) else None,
            query=query,
            limit=limit,
            now_epoch=now_epoch,
        )
        self._changes_listed = tuple(listed)
        self._changes_total = int(total or 0)
        self._changes_older = int(older or 0)
        try:
            cursor = int(getattr(self, "_changes_cursor", 0) or 0)
        except (TypeError, ValueError):
            cursor = 0
        if self._changes_listed:
            self._changes_cursor = max(0, min(cursor, len(self._changes_listed) - 1))
        else:
            self._changes_cursor = 0

    def _changes_cursor_row(self) -> dict[str, Any] | None:
        """Return the listed row under the lens cursor, if any."""
        listed = tuple(getattr(self, "_changes_listed", ()) or ())
        try:
            cursor = int(getattr(self, "_changes_cursor", 0) or 0)
        except (TypeError, ValueError):
            return None
        if 0 <= cursor < len(listed):
            row = listed[cursor]
            return dict(row) if isinstance(row, dict) else None
        return None

    def _changes_cursor_view(self) -> Any | None:
        """Return the cursor row's changeset view, if it carries one."""
        row = self._changes_cursor_row()
        if row is None or row.get("kind") != "changeset":
            return None
        return row.get("view")


__all__ = [
    "MemoryPaneChangesFeedMixin",
    "_changes_day_label",
    "_changes_lens_rows",
    "_changes_row_id",
    "_changes_row_is_selectable",
]

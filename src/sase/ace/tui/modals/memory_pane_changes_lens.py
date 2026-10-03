"""Changes lens: the rail becomes a day-grouped changeset review (``C``).

Owns the phase changes-lens rail behind :class:`MemoryPane` (epic
design ``plan:202610/memory_history_tui.md`` §13 and §4.5). ``C``
re-skins the Notes rail into changesets across subjects: rows come
from the pure :mod:`sase.memory.history.feed_model` shared with the
pager feed document, so the lens and the pager group days, fold
regen-only changesets, and label subjects identically. The highlight
moves at once while the card follows through the existing 150 ms
detail debouncer; ``⏎``/``l``/``H`` hand the cursor changeset to the
pager in the diff view, ``.1``–``.9`` open one subject, ``p``/``P``
cycle the ring plus a lens-only ``All scopes`` entry, ``/`` filters
every fetched changeset, and ``r`` refetches.

The lens framework (snapshot/restore, Esc ladder) lives in
:mod:`sase.ace.tui.modals.memory_pane_lens`; this module never imports
history presentation except through ``sase.pager.history_kit`` (the
import-guard door) and the pure ``feed_model``.
"""

from __future__ import annotations

import datetime
from typing import TYPE_CHECKING, Any

from rich.text import Text
from textual.widgets import OptionList
from textual.widgets.option_list import Option

from .memory_pane_lens import LENS_CHANGES, LENS_NOTES, LENS_TIMELINE, lens_header_text
from .memory_pane_review import (
    ScopeReview,
    changeset_is_unreviewed,
    entries_by_scope,
    feed_newest_commit,
    mark_reviewed_toast,
    review_chip,
    review_entries,
)

if TYPE_CHECKING:
    from textual.widget import Widget as _MixinBase
else:
    _MixinBase = object

#: Rail row id prefix for lens rows (never collides with note identities,
#: which are repo-relative paths or ``web:strand`` selectors).
_CHANGES_ROW_PREFIX = "changes:"

#: Trailing rail row id for the window-extension line.
MORE_ROW_ID = f"{_CHANGES_ROW_PREFIX}more"

#: Rail width bounds mirror the Notes rail (see
#: ``sase.ace.tui.modals.memory_panel_rendering``).
_CHANGES_RAIL_MIN_WIDTH = 32
_CHANGES_RAIL_MAX_WIDTH = 52


def _changes_row_id(commit: str, scope_key: str) -> str:
    """Return the stable rail id for one changeset row."""
    digest = (commit or "")[:12]
    return f"{_CHANGES_ROW_PREFIX}{scope_key}:{digest}"


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
                    "id": f"{_CHANGES_ROW_PREFIX}day:{day.key}",
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
                    "id": f"{_CHANGES_ROW_PREFIX}regen:{day.key}",
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


def _changes_lens_header_detail(
    *,
    scope_label: str = "",
    shown: int = 0,
    total: int = 0,
    older: int = 0,
    regen_folded: int = 0,
    query: str = "",
    failed_scopes: tuple[str, ...] = (),
    all_scopes: bool = False,
    review: str = "",
) -> str:
    """Return the header detail (``● 3 new · last 100 of 489 · 9 regen``).

    The review chip (``● N new``, ``not reviewed yet · m to mark``,
    or ``✓ nothing new``) leads when the watermark state is known.
    """
    bits: list[str] = []
    if review:
        bits.append(review)
    if total:
        if older:
            bits.append(f"last {shown} of {total}")
        else:
            bits.append(f"{total} changeset{'s' if total != 1 else ''}")
    else:
        bits.append("no changes")
    if regen_folded:
        bits.append(f"{regen_folded} regen-only folded")
    if all_scopes:
        bits.append("all scopes")
    elif scope_label:
        bits.append(scope_label)
    for failed in failed_scopes:
        bits.append(f"{failed} unavailable")
    if query:
        bits.append(f"/ {query}")
    return " · ".join(bit for bit in bits if bit)


def _changes_lens_footer(keymaps: Any) -> str:
    """Return the Changes lens footer with the effective configured keys.

    Terse Timeline-style verbs: the one-line footer ellipsizes past
    about 103 cells, so the open verb hardcodes ``⏎`` (as the Timeline
    footer does) instead of the long ``Enter / l`` display name.
    """
    try:
        from sase.ace.tui.keymaps import key_display_name  # noqa: PLC0415

        def _key(value: Any, fallback: str) -> str:
            try:
                return key_display_name(value)
            except Exception:
                return fallback

        nxt = _key(getattr(keymaps, "next_scope", "p"), "p")
        prv = _key(getattr(keymaps, "prev_scope", "P"), "P")
        filt = _key(getattr(keymaps, "filter_notes", "/"), "/")
        refresh = _key(getattr(keymaps, "refresh", "r"), "r")
        mark = _key(getattr(keymaps, "mark_reviewed", "m"), "m")
    except Exception:
        nxt, prv, filt, refresh, mark = "p", "P", "/", "r", "m"
    return (
        f"j/k changeset  ·  ⏎/.N open  ·  "
        f"{nxt}/{prv} scope  ·  {filt} filter  ·  {refresh} refetch  ·  "
        f"{mark} reviewed  ·  esc notes"
    )


def _changes_provenance_text(view: Any) -> str:
    """Return the ``◈ bead ⬡ agent ◉ commit`` provenance chips for a card."""
    bits: list[str] = []
    try:
        bead = str(getattr(view, "bead", "") or "")
        agent = str(getattr(view, "agent", "") or "")
        commit = str(getattr(view, "commit", "") or "")
    except Exception:
        return ""
    if bead:
        bits.append(f"◈ {bead}")
    if agent:
        bits.append(f"⬡ {agent}")
    if commit:
        bits.append(f"◉ {commit[:7]}")
    return "   ".join(bits)


def _changes_totals_text(view: Any) -> str:
    """Return the ``3 subjects · +200w −3w · ⟳ 3 regenerated`` totals line."""
    try:
        count = len(getattr(view, "authored", ()) or ())
    except Exception:
        count = 0
    try:
        delta = str(getattr(view, "word_delta", "") or "")
    except Exception:
        delta = ""
    try:
        regen = len(getattr(view, "consequences", ()) or ())
    except Exception:
        regen = 0
    noun = "subject" if count == 1 else "subjects"
    parts = [f"{count} {noun}"]
    if delta:
        parts.append(delta)
    if regen:
        parts.append(f"⟳ {regen} regenerated")
    return " · ".join(parts)


def _changes_section_title(index: int, subject: Any) -> str:
    """Return the ``.1 ◆ display · meaning`` title for one card section."""
    try:
        glyph = str(getattr(subject, "glyph", "") or "◆")
        display = str(getattr(subject, "display", "") or "")
        meaning = str(getattr(subject, "meaning", "") or "")
    except Exception:
        return f".{index}"
    title = f".{index} {glyph} {display}".rstrip()
    if meaning:
        title += f" · {meaning}"
    words = ""
    try:
        words = str(getattr(subject, "words", "") or "")
    except Exception:
        words = ""
    if words:
        title += f"  {words}"
    return title


class MemoryPaneChangesLensMixin(_MixinBase):
    """The ``C`` Changes lens: rail rows, card sections, and hand-off."""

    if TYPE_CHECKING:
        from textual.widgets import OptionList as _OptionList  # noqa: F401

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
        def _current_note_row(self) -> int: ...
        def _lens_is_active(self) -> bool: ...
        def _lens_name(self) -> Any: ...
        def _lens_take_notes_snapshot(self, node: Any | None) -> Any: ...
        def _note_list(self) -> _OptionList: ...
        def notify(self, *args: Any, **kwargs: Any) -> Any: ...
        def query_one(self, *args: Any, **kwargs: Any) -> Any: ...
        def run_worker(self, *args: Any, **kwargs: Any) -> Any: ...

    # --- guards ---------------------------------------------------------

    def _lens_is_changes(self) -> bool:
        """Return whether the rail currently shows the Changes lens."""
        try:
            return self._lens_name() == LENS_CHANGES
        except Exception:
            return False

    # --- entry / exit ---------------------------------------------------

    def action_open_changes(self) -> None:
        """Toggle the Changes lens from Notes; inert inside Timeline."""
        try:
            lens = self._lens_name()
        except Exception:
            lens = LENS_NOTES
        if lens == LENS_CHANGES:
            self._lens_exit_to_notes()
            return
        if lens != LENS_NOTES:
            return  # The other lens key is inert inside a lens (D3).
        self._changes_enter()

    def _changes_enter(self) -> None:
        """Turn the rail into day-grouped changesets for the scope."""
        from sase.ace.tui.util.trace import tui_trace  # noqa: PLC0415

        with tui_trace("memory.history.lens_open", lens="changes"):
            try:
                node = self._selected_row()
            except Exception:
                node = None
            try:
                self._lens_snapshot = self._lens_take_notes_snapshot(node)
            except Exception:
                self._lens_snapshot = None
            try:
                self._lens = LENS_CHANGES
            except Exception:
                pass
            self._changes_all_scopes = False
            self._changes_filter = ""
            self._changes_limit = 100
            self._changes_cursor = 0
            self._changes_scheduled = -1
            self._changes_generation = (
                int(getattr(self, "_changes_generation", 0) or 0) + 1
            )
            self._changes_sections = {}
            self._changes_section_failed = set()
            self._changes_feed = None
            self._changes_listed = ()
            self._changes_loading = True
            self._changes_review = ()
            try:
                self._render_changes_rail()
            except Exception:
                pass
            try:
                self._update_header()
            except Exception:
                pass
            try:
                self._update_footer()
            except Exception:
                pass
            self._changes_fetch()

    def _lens_exit_to_notes(self) -> None:
        """Restore Notes from the Changes lens; delegate other lenses onward."""
        try:
            lens = self._lens_name()
        except Exception:
            lens = LENS_NOTES
        if lens != LENS_CHANGES:
            try:
                super()._lens_exit_to_notes()  # type: ignore[misc]
            except Exception:
                try:
                    from .memory_pane_lens import (  # noqa: PLC0415
                        MemoryPaneLensMixin as _Framework,
                    )

                    snapshot = getattr(self, "_lens_snapshot", None)
                    self._lens = LENS_NOTES
                    self._lens_snapshot = None
                    _Framework._lens_restore_notes_snapshot(self, snapshot)  # type: ignore[arg-type]
                except Exception:
                    pass
            return
        snapshot = getattr(self, "_lens_snapshot", None)
        self._changes_clear_state()
        try:
            self._lens = LENS_NOTES
        except Exception:
            pass
        try:
            self._lens_snapshot = None
        except Exception:
            pass
        try:
            from .memory_pane_lens import MemoryPaneLensMixin  # noqa: PLC0415

            MemoryPaneLensMixin._lens_restore_notes_snapshot(self, snapshot)  # type: ignore[arg-type]
        except Exception:
            pass

    def _changes_clear_state(self) -> None:
        """Forget lens rows, cursor, filter, window, and section cache."""
        for attr, value in (
            ("_changes_feed", None),
            ("_changes_listed", ()),
            ("_changes_cursor", 0),
            ("_changes_scheduled", -1),
            ("_changes_filter", ""),
            ("_changes_limit", 100),
            ("_changes_all_scopes", False),
            ("_changes_failed", ()),
            ("_changes_scope_label", ""),
            ("_changes_total", 0),
            ("_changes_older", 0),
            ("_changes_loading", False),
            ("_changes_sections", {}),
            ("_changes_section_failed", set()),
            # The review watermark survives a mark worker: clearing the
            # lens must never cancel the off-thread persist. The worker
            # repaints only while the lens is still open.
            ("_changes_review", ()),
        ):
            try:
                setattr(self, attr, value)
            except Exception:
                pass
        try:
            worker = getattr(self, "_changes_worker", None)
            if worker is not None and not worker.is_finished:
                worker.cancel()
        except Exception:
            pass

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

    # --- rail rendering ---------------------------------------------------

    def _render_changes_rail(self) -> None:
        """Paint the lens rows into the Notes rail widget."""
        try:
            option_list = self._note_list()
        except Exception:
            return
        listed = tuple(getattr(self, "_changes_listed", ()) or ())
        try:
            cursor = int(getattr(self, "_changes_cursor", 0) or 0)
        except (TypeError, ValueError):
            cursor = 0
        try:
            from sase.memory.history.feed_model import (  # noqa: PLC0415
                changeset_row_text,
                older_window_text,
                regen_count_text,
            )
        except Exception:
            return
        options: list[Option] = []
        try:
            review_indexed = entries_by_scope(
                tuple(getattr(self, "_changes_review", ()) or ())
            )
        except Exception:
            review_indexed = {}
        try:
            dot_accent = str(getattr(self, "_accent", "") or "")
        except Exception:
            dot_accent = ""
        for row in listed:
            if not isinstance(row, dict):
                continue
            kind = str(row.get("kind", "") or "")
            if kind == "day":
                title = str(row.get("title", "") or "")
                options.append(
                    Option(
                        Text(f"━ {title} ━", style="dim"),
                        id=str(row.get("id", "") or None),
                        disabled=True,
                    )
                )
            elif kind == "changeset":
                view = row.get("view")
                if view is None:
                    line = ""
                else:
                    try:
                        line = changeset_row_text(view)
                    except Exception:
                        line = ""
                try:
                    dotted = view is not None and changeset_is_unreviewed(
                        view, review_indexed
                    )
                except Exception:
                    dotted = False
                if dotted:
                    prompt = Text()
                    prompt.append(
                        "● ",
                        style=f"bold {dot_accent}" if dot_accent else "bold",
                    )
                    prompt.append(line or "(changeset)")
                    options.append(Option(prompt, id=str(row.get("id", "") or None)))
                else:
                    options.append(
                        Option(
                            Text(line or "(changeset)"),
                            id=str(row.get("id", "") or None),
                        )
                    )
            elif kind == "regen":
                try:
                    count = int(row.get("count", 0) or 0)
                except (TypeError, ValueError):
                    count = 0
                options.append(
                    Option(
                        Text(regen_count_text(count), style="dim"),
                        id=str(row.get("id", "") or None),
                        disabled=True,
                    )
                )
            elif kind == "more":
                try:
                    older = int(row.get("older", 0) or 0)
                except (TypeError, ValueError):
                    older = 0
                options.append(
                    Option(
                        Text(older_window_text(older), style="dim"),
                        id=MORE_ROW_ID,
                    )
                )
        if not options:
            try:
                loading = bool(getattr(self, "_changes_loading", False))
            except Exception:
                loading = False
            options.append(
                Option(
                    Text(
                        "loading changes…"
                        if loading
                        else "(no memory changes in this window)",
                        style="dim",
                    ),
                    id=f"{_CHANGES_ROW_PREFIX}empty",
                    disabled=True,
                )
            )
        try:
            guard = self._selection_guard
        except Exception:
            guard = None
        try:
            option_list.clear_options()
            option_list.add_options(options)
            if options:
                target = max(0, min(cursor, len(options) - 1))
                if guard is not None:
                    try:
                        guard.prepare(f"changes:{target}", target)
                    except Exception:
                        pass
                option_list.highlighted = target
        except Exception:
            pass
        try:
            self._resize_changes_rail()
        except Exception:
            pass

    def _resize_changes_rail(self) -> None:
        """Pin the rail to its maximum width in the Changes lens."""
        try:
            from textual.containers import Horizontal  # noqa: PLC0415

            body = self.query_one("#memory-panel-body", Horizontal)
            note_list = self._note_list()
            available = int(body.size.width or 0)
        except Exception:
            return
        width = _CHANGES_RAIL_MAX_WIDTH
        if available > 0:
            room = available - 56 - 1
            width = min(width, max(_CHANGES_RAIL_MIN_WIDTH, room))
        width = max(_CHANGES_RAIL_MIN_WIDTH, width)
        try:
            current = note_list.styles.width
            if current is not None and current.is_cells and int(current.value) == width:
                return
            note_list.styles.width = width
        except Exception:
            pass

    # --- highlight, preview, stale drops ----------------------------------

    def on_option_list_option_highlighted(self, event: Any) -> None:
        """Route rail motion to the lens cursor; Notes falls through."""
        if not self._lens_is_changes():
            return
        try:
            event.prevent_default()
            event.stop()
        except Exception:
            pass
        try:
            from .memory_panel_state import _NOTE_LIST_ID  # noqa: PLC0415

            if getattr(event.option_list, "id", None) != _NOTE_LIST_ID:
                return
            idx = int(event.option_index)
        except Exception:
            return
        listed = tuple(getattr(self, "_changes_listed", ()) or ())
        if not 0 <= idx < len(listed):
            return
        try:
            current = self._note_list().highlighted
            current = int(current) if current is not None else idx
        except Exception:
            current = idx
        try:
            guard = self._selection_guard
            if guard is not None and guard.should_ignore(
                f"changes:{idx}",
                idx,
                current_identity=f"changes:{current}",
                current_row=current,
            ):
                return
        except Exception:
            pass
        row = listed[idx] if isinstance(listed[idx], dict) else None
        kind = str((row or {}).get("kind", "") or "")
        if kind == "more":
            self._changes_cursor = idx
            self._changes_extend_window()
            return
        if kind != "changeset":
            return  # Day and regen rows hold the card; they move nothing.
        self._changes_cursor = idx
        self._changes_scheduled = idx
        try:
            debouncer = self._debouncer
            if debouncer is not None:
                debouncer.schedule(self._changes_preview_fire)
            else:
                self._changes_preview_fire()
        except Exception:
            pass

    def _changes_preview_fire(self) -> None:
        """Apply the scheduled lens cursor to the card (last wins)."""
        if not self._lens_is_changes():
            return
        try:
            cursor = int(getattr(self, "_changes_cursor", 0) or 0)
            scheduled = int(getattr(self, "_changes_scheduled", -1) or -1)
        except (TypeError, ValueError):
            return
        if cursor != scheduled:
            return  # A newer motion already won.
        try:
            self._render_note_card()
        except Exception:
            pass

    def _changes_extend_window(self) -> None:
        """Extend the bounded window by 100 when the cursor hits the tail."""
        try:
            older = int(getattr(self, "_changes_older", 0) or 0)
        except (TypeError, ValueError):
            older = 0
        if older <= 0:
            return
        try:
            self._changes_limit = int(getattr(self, "_changes_limit", 100) or 100) + 100
        except (TypeError, ValueError):
            self._changes_limit = 200
        try:
            keep = self._changes_cursor_row()
            keep_key = None
            if isinstance(keep, dict) and keep.get("kind") == "changeset":
                view = keep.get("view")
                keep_key = (getattr(view, "scope_key", ""), getattr(view, "commit", ""))
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
            self._update_header()
        except Exception:
            pass

    # --- card ---------------------------------------------------------------

    def _render_note_card(self) -> None:
        """Render the changeset card in the lens; Notes otherwise."""
        if not self._lens_is_changes():
            try:
                super()._render_note_card()  # type: ignore[misc]
            except Exception:
                pass
            return
        try:
            from textual.widgets import Static  # noqa: PLC0415
        except Exception:
            return
        view = self._changes_cursor_view()
        try:
            title_widget = self.query_one("#memory-panel-card-title", Static)
            strip_widget = self.query_one("#memory-panel-time-strip", Static)
            description_widget = self.query_one(
                "#memory-panel-card-description", Static
            )
            meta_widget = self.query_one("#memory-panel-card-meta", Static)
        except Exception:
            return
        try:
            from textual.widgets import Markdown as _Markdown  # noqa: PLC0415

            body_widget: Any | None = self.query_one(
                "#memory-panel-card-body", _Markdown
            )
        except Exception:
            body_widget = None
        try:
            diff_widget: Any | None = self.query_one("#memory-panel-card-diff", Static)
        except Exception:
            diff_widget = None
        if view is None:
            row = self._changes_cursor_row()
            kind = str((row or {}).get("kind", "") or "")
            if kind == "more":
                notice = "loading more changesets…"
            elif bool(getattr(self, "_changes_loading", False)):
                notice = "loading changes…"
            else:
                notice = "select a changeset to review it"
            try:
                title_widget.update(Text("Changes", style="bold"))
                strip_widget.update(Text(notice, style="dim"))
                strip_widget.display = True
                description_widget.update("")
                if body_widget is not None:
                    body_widget.update("")
                if diff_widget is not None:
                    diff_widget.display = False
                    diff_widget.update("")
                meta_widget.update("")
            except Exception:
                pass
            return
        try:
            import time as _time  # noqa: PLC0415

            now_epoch = int(_time.time())
        except Exception:
            now_epoch = 0
        try:
            from sase.pager.history_kit import format_age  # noqa: PLC0415
        except Exception:
            format_age = None  # type: ignore[assignment]
        try:
            epoch = int(getattr(view, "committer_time", 0) or 0)
        except (TypeError, ValueError):
            epoch = 0
        try:
            import datetime as _dt  # noqa: PLC0415

            absolute = (
                _dt.datetime.fromtimestamp(epoch).strftime("%a %b %d %H:%M")
                if epoch
                else "undated"
            )
        except Exception:
            absolute = "undated"
        try:
            relative = (
                format_age(now_epoch, epoch)
                if (format_age is not None and epoch)
                else ""
            )
        except Exception:
            relative = ""
        try:
            subject = str(getattr(view, "subject_line", "") or "(no subject)")
            scope_key = str(getattr(view, "scope_key", "") or "")
        except Exception:
            subject, scope_key = "(no subject)", ""
        path_line = f"{absolute}"
        if relative:
            path_line += f" · {relative} ago"
        if scope_key:
            path_line += f" · {scope_key}"
        try:
            title_widget.update(Text(subject, style="bold"))
            strip_widget.update(Text(_changes_provenance_text(view) or "·", style=""))
            strip_widget.display = True
            description_widget.update(Text(path_line, style="dim"))
            meta_widget.update(Text(_changes_totals_text(view), style="dim"))
        except Exception:
            pass
        try:
            if diff_widget is not None:
                diff_widget.display = False
                diff_widget.update("")
        except Exception:
            pass
        sections_text = self._changes_sections_text(view)
        try:
            if body_widget is not None:
                body_widget.update(sections_text)
        except Exception:
            pass
        self._changes_ensure_sections(view)

    def _changes_sections_text(self, view: Any) -> str:
        """Return the progressive per-subject card body for a changeset."""
        try:
            from sase.memory.history.feed_model import (  # noqa: PLC0415
                MAX_INLINE_SECTIONS,
            )
        except Exception:
            MAX_INLINE_SECTIONS = 6
        try:
            authored = tuple(getattr(view, "authored", ()) or ())
        except Exception:
            authored = ()
        try:
            commit = str(getattr(view, "commit", "") or "")
        except Exception:
            commit = ""
        lines: list[str] = []
        shown = authored[:MAX_INLINE_SECTIONS]
        for position, subject in enumerate(shown, start=1):
            title = _changes_section_title(position, subject)
            lines.append(title)
            try:
                key = (
                    commit,
                    str(getattr(subject, "selector", "") or ""),
                    str(getattr(subject, "revision", "") or ""),
                )
            except Exception:
                key = (commit, "", "")
            sections: dict[tuple[str, str, str], Any] = (
                getattr(self, "_changes_sections", {}) or {}
            )
            failed: set[tuple[str, str, str]] = (
                getattr(self, "_changes_section_failed", set()) or set()
            )
            if key in sections:
                body = str(sections.get(key, "") or "")
                lines.append(body if body else "(empty)")
            elif key in failed:
                lines.append("diff unavailable for this subject")
            else:
                lines.append("loading diff…")
            lines.append("")
        try:
            hidden = max(0, len(authored) - len(shown))
        except Exception:
            hidden = 0
        if hidden:
            lines.append(f"+{hidden} more · .N or ⏎ to open")
            lines.append("")
        try:
            consequences = tuple(getattr(view, "consequences", ()) or ())
        except Exception:
            consequences = ()
        if consequences:
            lines.append(f"⟳ {' · '.join(consequences)}")
        return "\n".join(lines).rstrip() + "\n" if lines else "(no authored subjects)\n"

    def _changes_ensure_sections(self, view: Any) -> None:
        """Fill per-subject diff sections progressively (generation-guarded)."""
        try:
            from sase.memory.history.feed_model import (  # noqa: PLC0415
                MAX_INLINE_SECTIONS,
            )
        except Exception:
            MAX_INLINE_SECTIONS = 6
        try:
            authored = tuple(getattr(view, "authored", ()) or ())
        except Exception:
            return
        try:
            commit = str(getattr(view, "commit", "") or "")
            scope_key = str(getattr(view, "scope_key", "") or "")
        except Exception:
            return
        shown = authored[:MAX_INLINE_SECTIONS]
        try:
            generation = int(getattr(self, "_changes_generation", 0) or 0)
        except Exception:
            generation = 0
        try:
            sections: dict[tuple[str, str, str], Any] = (
                getattr(self, "_changes_sections", {}) or {}
            )
            failed: set[tuple[str, str, str]] = (
                getattr(self, "_changes_section_failed", set()) or set()
            )
        except Exception:
            sections, failed = {}, set()
        pending: list[tuple[tuple[str, str, str], Any]] = []
        for subject in shown:
            try:
                key = (
                    commit,
                    str(getattr(subject, "selector", "") or ""),
                    str(getattr(subject, "revision", "") or ""),
                )
            except Exception:
                continue
            if key in sections or key in failed:
                continue
            pending.append((key, subject))
        if not pending:
            return

        async def _fill() -> None:
            import asyncio

            def _query() -> dict[tuple[str, str, str], str]:
                results: dict[tuple[str, str, str], str] = {}
                try:
                    history = self._ace_history()
                except Exception:
                    return results
                if history is None:
                    return results
                try:
                    service = history.service
                except Exception:
                    service = history
                scope = None
                try:
                    from .memory_panel_history import (  # noqa: PLC0415
                        history_scopes_for_ring,
                    )

                    ring = tuple(getattr(self, "_ring", ()) or ())
                    scopes = history_scopes_for_ring(ring, service)
                    for candidate in scopes:
                        if str(getattr(candidate, "scope_key", "")) == scope_key:
                            scope = candidate
                            break
                    if scope is None:
                        scope = (
                            history.scope_for_ref(
                                next(
                                    (
                                        ref
                                        for ref in ring
                                        if str(getattr(ref, "key", "")) == scope_key
                                    ),
                                    None,
                                )
                            )
                            if hasattr(history, "scope_for_ref")
                            else None
                        )
                except Exception:
                    scope = None
                if scope is None:
                    return results
                for key, subject in pending:
                    _commit, selector, revision = key
                    if not selector or not revision:
                        continue
                    try:
                        class_name = str(getattr(subject, "class_name", "") or "")
                    except Exception:
                        class_name = ""
                    if class_name == "deleted":
                        results[key] = "deleted · last content shown"
                        continue
                    try:
                        body_wire = history.version_body(scope, selector, revision)
                    except Exception:
                        continue
                    try:
                        target_body = str(body_wire.get("body", "") or "")
                    except Exception:
                        target_body = ""
                    try:
                        ordinal = int(str(revision).lstrip("v") or 0)
                    except (TypeError, ValueError):
                        ordinal = 0
                    try:
                        if ordinal <= 1:
                            base = "empty"
                        else:
                            base = f"v{ordinal - 1}"
                        comparison = history.comparison(scope, selector, base, revision)
                    except Exception:
                        comparison = None
                    try:
                        if comparison is None:
                            results[key] = (
                                target_body.splitlines()[0]
                                if target_body
                                else "(empty)"
                            )
                            continue
                        from sase.pager.history_kit import (  # noqa: PLC0415
                            build_diff_body,
                        )

                        rendered = build_diff_body(comparison, target_body)
                        results[key] = rendered.text.plain.strip() or "(no changes)"
                    except Exception:
                        try:
                            results[key] = (
                                target_body.splitlines()[0]
                                if target_body
                                else "(empty)"
                            )
                        except Exception:
                            pass
                return results

            filled = await asyncio.to_thread(_query)
            if not self._lens_is_changes():
                return
            if int(getattr(self, "_changes_generation", 0) or 0) != generation:
                return  # Stale: the cursor moved to another changeset.
            current = self._changes_cursor_view()
            try:
                current_commit = str(getattr(current, "commit", "") or "")
            except Exception:
                current_commit = ""
            if current_commit != commit:
                return  # Stale: a newer changeset won.
            if not isinstance(filled, dict):
                return
            try:
                sections = dict(getattr(self, "_changes_sections", {}) or {})
                sections.update(filled)
                self._changes_sections = sections
                self._render_note_card()
            except Exception:
                pass

        try:
            self.run_worker(
                _fill(),
                exclusive=True,
                group="memory-panel-changes-sections",
                exit_on_error=False,
            )
        except Exception:
            pass

    # --- selection, header, footer ------------------------------------------

    def _selected_row(self) -> Any | None:
        """The Changes card is a changeset, not a note; Notes otherwise."""
        if self._lens_is_changes():
            return None
        try:
            return super()._selected_row()  # type: ignore[misc]
        except Exception:
            return None

    def _update_header(self) -> None:
        """Name the lens, scope, and window in the Changes lens."""
        if not self._lens_is_changes():
            try:
                super()._update_header()  # type: ignore[misc]
            except Exception:
                pass
            return
        try:
            from textual.widgets import Static  # noqa: PLC0415
            from rich.text import Text as _Text  # noqa: PLC0415

            try:
                shown = sum(
                    1
                    for row in tuple(getattr(self, "_changes_listed", ()) or ())
                    if isinstance(row, dict) and row.get("kind") == "changeset"
                )
            except Exception:
                shown = 0
            try:
                from sase.memory.history.feed_model import (  # noqa: PLC0415
                    flatten_visible,
                    group_feed,
                )

                feed = getattr(self, "_changes_feed", None)
                regen = 0
                if isinstance(feed, dict):
                    for day in group_feed(feed):
                        regen += len(day.hidden)
            except Exception:
                regen = 0
            try:
                scope_name = str(getattr(self, "_changes_scope_label", "") or "")
                if not scope_name:
                    snapshot = getattr(self, "_snapshot", None)
                    scope = (
                        getattr(snapshot, "scope", None)
                        if snapshot is not None
                        else None
                    )
                    scope_name = str(getattr(scope, "display_name", "") or "")
            except Exception:
                scope_name = ""
            try:
                chip = review_chip(tuple(getattr(self, "_changes_review", ()) or ()))
            except Exception:
                chip = ""
            detail = _changes_lens_header_detail(
                scope_label=scope_name,
                shown=shown,
                total=int(getattr(self, "_changes_total", 0) or 0),
                older=int(getattr(self, "_changes_older", 0) or 0),
                regen_folded=regen,
                query=str(getattr(self, "_changes_filter", "") or ""),
                failed_scopes=tuple(getattr(self, "_changes_failed", ()) or ()),
                all_scopes=bool(getattr(self, "_changes_all_scopes", False)),
                review=chip,
            )
            header = lens_header_text(
                lens=LENS_CHANGES,
                scope_display_name=scope_name,
                detail=detail,
            )
            accent = str(getattr(self, "_accent", "#87D7FF") or "#87D7FF")
            text = _Text(header or "MEMORY · changes", style=f"bold {accent}")
            self.query_one("#memory-panel-header", Static).update(text)
        except Exception:
            pass

    def _update_footer(self) -> None:
        """Show the lens footer in the Changes lens."""
        if not self._lens_is_changes():
            try:
                super()._update_footer()  # type: ignore[misc]
            except Exception:
                pass
            return
        try:
            from textual.widgets import Static  # noqa: PLC0415

            footer = _changes_lens_footer(getattr(self, "_keymaps", None))
            widget = self.query_one("#memory-panel-footer", Static)
            widget.update(footer)
            widget.display = bool(footer)
        except Exception:
            pass

    # --- travel, follow, scope -----------------------------------------------

    def action_open_history(self) -> None:
        """``H`` opens the cursor changeset in the pager diff view."""
        if self._lens_is_changes():
            self._changes_open_at_cursor()
            return
        try:
            super().action_open_history()  # type: ignore[misc]
        except Exception:
            pass

    def action_travel_back(self) -> None:
        """Exit the lens on ``h``/backspace; walk the trail in Notes."""
        if self._lens_is_changes():
            self._lens_exit_to_notes()
            return
        try:
            super().action_travel_back()  # type: ignore[misc]
        except Exception:
            pass

    def action_follow_link(self) -> None:
        """Open the pager in diff view at the cursor changeset (lens ``⏎``)."""
        if self._lens_is_changes():
            self._changes_open_at_cursor()
            return
        try:
            super().action_follow_link()  # type: ignore[misc]
        except Exception:
            pass

    def action_follow_link_number(self, number: int) -> None:
        """``.N`` opens subject N of the cursor changeset in the pager."""
        if self._lens_is_changes():
            self._changes_open_subject_number(int(number))
            return
        try:
            super().action_follow_link_number(number)  # type: ignore[misc]
        except Exception:
            pass

    def action_history_timeline(self) -> None:
        """``@`` is inert inside the Changes lens (D3)."""
        if self._lens_is_changes():
            return
        try:
            super().action_history_timeline()  # type: ignore[misc]
        except Exception:
            pass

    def action_next_scope(self) -> None:
        """Cycle the ring plus ``All scopes`` inside the Changes lens."""
        if self._lens_is_changes():
            self._changes_cycle_scope(1)
            return
        try:
            super().action_next_scope()  # type: ignore[misc]
        except Exception:
            pass

    def action_prev_scope(self) -> None:
        """Cycle the ring plus ``All scopes`` inside the Changes lens."""
        if self._lens_is_changes():
            self._changes_cycle_scope(-1)
            return
        try:
            super().action_prev_scope()  # type: ignore[misc]
        except Exception:
            pass

    def action_pick_scope(self) -> None:
        """The scope picker stays Notes-only; inert in the Changes lens."""
        if self._lens_is_changes():
            return
        try:
            super().action_pick_scope()  # type: ignore[misc]
        except Exception:
            pass

    def _changes_cycle_scope(self, delta: int) -> None:
        """Move through the ring plus the lens-only ``All scopes`` entry."""
        ring = tuple(getattr(self, "_ring", ()) or ())
        if not ring:
            return
        try:
            all_scopes = bool(getattr(self, "_changes_all_scopes", False))
            index = int(getattr(self, "_scope_index", 0) or 0) % len(ring)
        except Exception:
            all_scopes, index = False, 0
        if delta > 0:
            if all_scopes:
                self._changes_all_scopes = False
                self._scope_index = 0
            elif index >= len(ring) - 1:
                self._changes_all_scopes = True
            else:
                self._scope_index = index + 1
        else:
            if all_scopes:
                self._changes_all_scopes = False
                self._scope_index = len(ring) - 1
            elif index <= 0:
                self._changes_all_scopes = True
            else:
                self._scope_index = index - 1
        try:
            self._changes_generation = (
                int(getattr(self, "_changes_generation", 0) or 0) + 1
            )
            self._changes_limit = 100
            self._changes_cursor = 0
            self._changes_scheduled = -1
            self._changes_sections = {}
            self._changes_section_failed = set()
            self._changes_feed = None
            self._changes_listed = ()
            self._changes_loading = True
            # The scope changed, so the old watermark chip must not
            # linger while the new scope loads.
            self._changes_review = ()
            self._render_changes_rail()
            self._update_header()
        except Exception:
            pass
        self._changes_fetch()

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
    "MORE_ROW_ID",
    "MemoryPaneChangesLensMixin",
    "_changes_day_label",
    "_changes_lens_footer",
    "_changes_lens_header_detail",
    "_changes_lens_rows",
    "_changes_provenance_text",
    "_changes_row_id",
    "_changes_row_is_selectable",
    "_changes_section_title",
    "_changes_totals_text",
]

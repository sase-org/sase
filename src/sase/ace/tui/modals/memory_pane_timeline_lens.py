"""Timeline lens: the rail becomes the subject's version timeline (``@``).

Owns the phase timeline-lens rail behind :class:`MemoryPane` (epic
design ``plan:202610/memory_history_tui.md`` §12 and §4.4). ``@``
re-skins the Notes rail into the selected subject's timeline: rows
come from :func:`sase.pager.history_kit.build_picker_rows` laid out by
the kit's picker column fitter, so these are the pager picker's exact
cells. The highlight moves at once while the card follows through the
existing 150 ms detail debouncer; ``b`` sets a compare base, ``.``
reveals hidden versions, and ``⏎``/``l``/``H`` hand the cursor's pin,
view, and base to the pager.

The lens framework (snapshot/restore, Esc ladder) lives in
:mod:`sase.ace.tui.modals.memory_pane_lens`; this module never imports
history presentation except through ``sase.pager.history_kit`` (the
import-guard door).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from rich.text import Text
from textual.widgets import OptionList
from textual.widgets.option_list import Option

from .memory_pane_lens import LENS_NOTES, LENS_TIMELINE, lens_header_text

if TYPE_CHECKING:
    from textual.widget import Widget as _MixinBase
else:
    _MixinBase = object

#: Rail row id prefix for lens rows (never collides with note identities,
#: which are repo-relative paths or ``web:strand`` selectors).
_TIMELINE_ROW_PREFIX = "timeline:"

#: Trailing rail row id for the hidden-versions summary line.
HIDDEN_SUMMARY_ID = f"{_TIMELINE_ROW_PREFIX}hidden-summary"

#: Rail width bounds mirror the Notes rail (see
#: ``sase.ace.tui.modals.memory_panel_rendering``): never narrower than
#: the historical width, never wider than the card's share.
_TIMELINE_RAIL_MIN_WIDTH = 32
_TIMELINE_RAIL_MAX_WIDTH = 52


def _timeline_row_id(label: str, class_name: str, ordinal: int) -> str:
    """Return the stable rail id for one picker row."""
    return f"{_TIMELINE_ROW_PREFIX}{label}:{class_name}:{int(ordinal)}"


def _timeline_lens_rows(
    timeline: dict[str, Any] | None,
    *,
    now_epoch: int,
    show_hidden: bool,
) -> tuple[tuple[dict[str, Any], ...], int, int]:
    """Return ``(listed, hidden_count, total_committed)`` for the rail.

    Rows come from the kit's :func:`build_picker_rows` (the pager
    picker's exact cells). *listed* excludes hidden rows unless
    *show_hidden*; *hidden_count* counts the rows ``.`` would reveal;
    *total_committed* counts non-pseudo rows. Never raises: ``None``
    or malformed timelines list nothing.
    """
    try:
        from sase.pager.history_kit import (
            build_picker_rows,
            hidden_picker_rows,
            visible_picker_rows,
        )
    except Exception:
        return ((), 0, 0)
    if not isinstance(timeline, dict):
        return ((), 0, 0)
    try:
        newest = 0
        versions = timeline.get("versions", ())
        if isinstance(versions, (list, tuple)):
            for version in versions:
                if isinstance(version, dict):
                    try:
                        ordinal = int(version.get("ordinal", 0) or 0)
                    except (TypeError, ValueError):
                        continue
                    newest = max(newest, ordinal)
        now_matches = newest > 0 and not bool(timeline.get("dirty", False))
        rows = build_picker_rows(
            timeline, now_epoch=int(now_epoch), now_matches_newest=now_matches
        )
    except Exception:
        return ((), 0, 0)
    try:
        hidden = hidden_picker_rows(tuple(rows))
        hidden_count = len(hidden)
    except Exception:
        hidden_count = 0
    try:
        if show_hidden:
            listed = cast(tuple[dict[str, Any], ...], tuple(rows))
        else:
            listed = cast(
                tuple[dict[str, Any], ...],
                tuple(visible_picker_rows(tuple(rows), show_hidden=False)),
            )
    except Exception:
        listed = cast(tuple[dict[str, Any], ...], tuple(rows))
    try:
        total = sum(1 for row in rows if not bool(row.get("pseudo", False)))
    except Exception:
        total = 0
    return (listed, hidden_count, total)


def _timeline_hidden_rows(
    timeline: dict[str, Any] | None,
    *,
    now_epoch: int,
) -> tuple[dict[str, Any], ...]:
    """Return the committed rows hidden unless ``.`` is pressed.

    Counts reflows and moves through the kit, exactly like the pager
    picker. Never raises.
    """
    if not isinstance(timeline, dict):
        return ()
    try:
        from sase.pager.history_kit import (  # noqa: PLC0415
            build_picker_rows,
            hidden_picker_rows,
        )

        rows = build_picker_rows(timeline, now_epoch=int(now_epoch))
        return tuple(hidden_picker_rows(tuple(rows)))
    except Exception:
        return ()


def _timeline_hidden_summary_text(
    hidden_rows: tuple[dict[str, Any], ...],
) -> str:
    """Return the trailing rail line counting hidden rows (``· . show``)."""
    if not hidden_rows:
        return ""
    try:
        from sase.pager.history_kit import hidden_summary_text  # noqa: PLC0415

        text = hidden_summary_text(tuple(hidden_rows))
        if text:
            return str(text)
    except Exception:
        pass
    total = len(hidden_rows)
    noun = "version" if total == 1 else "versions"
    return f"·· {total} hidden {noun} · . show"


def _version_name(ordinal: int) -> str:
    """Return the display name for an ordinal (``now`` for live)."""
    return "now" if int(ordinal) <= 0 else f"v{int(ordinal)}"


def _timeline_compare_text(cursor_ordinal: int, base_ordinal: int | None) -> str | None:
    """Return the compare status for a set base, or ``None``.

    Endpoints always read older to newer; equal endpoints read
    ``Same version``. Never raises.
    """
    if base_ordinal is None:
        return None
    try:
        cursor = int(cursor_ordinal)
        base = int(base_ordinal)
    except (TypeError, ValueError):
        return None
    if cursor == base:
        return "Same version · b clear"

    def _newest_key(ordinal: int) -> float:
        # ``now`` (ordinal 0) is always the newest endpoint.
        return float("inf") if int(ordinal) <= 0 else float(int(ordinal))

    older, newer = (
        (base, cursor) if _newest_key(base) < _newest_key(cursor) else (cursor, base)
    )
    return f"Compare {_version_name(older)} → {_version_name(newer)} · b clear"


def _timeline_lens_header_detail(
    *,
    total_committed: int,
    hidden_count: int,
    show_hidden: bool,
    query: str = "",
) -> str:
    """Return the header detail (``25 versions · 3 hidden``)."""
    noun = "version" if total_committed == 1 else "versions"
    detail = f"{total_committed} {noun}"
    if hidden_count and not show_hidden:
        detail += f" · {hidden_count} hidden"
    if query:
        detail += f" — / {query}"
    return detail


def _timeline_lens_footer(
    keymaps: Any,
    *,
    compare_text: str | None = None,
    show_hidden: bool = False,
) -> str:
    """Return the Timeline lens footer with the effective configured keys."""
    try:
        from sase.ace.tui.keymaps import key_display_name  # noqa: PLC0415

        def _key(value: Any, fallback: str) -> str:
            try:
                return key_display_name(value)
            except Exception:
                return fallback

        at = _key(getattr(keymaps, "history_timeline", "@"), "@")
        base = _key(getattr(keymaps, "history_compare_base", "b"), "b")
        hidden = _key(getattr(keymaps, "history_toggle_hidden", "."), ".")
        filt = _key(getattr(keymaps, "filter_notes", "/"), "/")
        diff = _key(getattr(keymaps, "history_toggle_diff", "="), "=")
        pager = _key(getattr(keymaps, "open_history", "H"), "H")
    except Exception:
        at, base, hidden, filt, diff, pager = "@", "b", ".", "/", "=", "H"
    parts = [
        "j/k version",
        f"{diff} read",
        f"{base} base",
        f"{hidden} hidden",
        f"{filt} filter",
        "⏎ open in pager",
        f"{pager} pager",
        "esc notes",
        f"{at} notes",
    ]
    if compare_text:
        parts.insert(3, compare_text)
    return "  ·  ".join(parts)


def _timeline_subject_display(node: Any) -> str:
    """Return the short subject name for the lens header."""
    try:
        identity = str(getattr(node, "identity", "") or "")
    except Exception:
        identity = ""
    if not identity:
        return ""
    if ":" in identity and "/" not in identity.rsplit(":", 1)[-1]:
        return identity
    try:
        from pathlib import Path  # noqa: PLC0415

        return Path(identity).stem or identity
    except Exception:
        return identity


class MemoryPaneTimelineLensMixin(_MixinBase):
    """The ``@`` Timeline lens: rail rows, preview, base, and hand-off."""

    if TYPE_CHECKING:
        from textual.widgets import OptionList as _OptionList  # noqa: F401

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
        _time_applied: dict[tuple[str, str], int]
        _time_diff_view: bool
        _time_pending: dict[tuple[str, str], str]
        _time_pins: dict[tuple[str, str], int]
        _timeline_base: int | None
        _timeline_cursor: int
        _timeline_filter: str
        _timeline_has_hidden_line: bool
        _timeline_listed: tuple[dict[str, Any], ...]
        _timeline_open_key: tuple[str, str] | None
        _timeline_preview_pending: bool
        _timeline_rows_all: tuple[dict[str, Any], ...]
        _timeline_scheduled: int
        _timeline_show_hidden: bool
        _timeline_subject_identity: str | None
        _timeline_subject_key: tuple[str, str] | None
        _timeline_subject_node: Any | None
        app: Any
        is_mounted: bool

        def _ace_history(self) -> Any | None: ...
        def _apply_time_pin(
            self, key: tuple[str, str], node: Any, ordinal: int
        ) -> None: ...
        def _current_note_row(self) -> int: ...
        def _ensure_history_load(self, scope_key: str, selector: str) -> None: ...
        def _ensure_time_body(
            self, key: tuple[str, str], node: Any, ordinal: int
        ) -> bool: ...
        def _history_key_for_node(
            self, node: Any | None
        ) -> tuple[str, str, Any, str] | None: ...
        def _lens_is_timeline(self) -> bool: ...
        def _lens_name(self) -> Any: ...
        def _lens_take_notes_snapshot(self, node: Any | None) -> Any: ...
        def _note_list(self) -> _OptionList: ...
        def _time_applied_ordinal(self, node: Any | None) -> int: ...
        def _time_key(self, node: Any | None) -> tuple[str, str] | None: ...
        def _time_pinned_ordinal(self, node: Any | None) -> int: ...
        def _time_timeline(self, node: Any | None) -> dict[str, Any] | None: ...
        def notify(self, *args: Any, **kwargs: Any) -> Any: ...
        def query_one(self, *args: Any, **kwargs: Any) -> Any: ...
        def run_worker(self, *args: Any, **kwargs: Any) -> Any: ...

    # --- entry / exit ---------------------------------------------------

    def action_history_timeline(self) -> None:
        """Open the Timeline lens from Notes, or close it inside one."""
        if self._lens_name() == LENS_TIMELINE:
            self._lens_exit_to_notes()
            return
        if self._lens_name() != LENS_NOTES:
            return  # The other lens key is inert inside a lens.
        node = self._selected_row()
        if node is None:
            return
        try:
            from .memory_pane_instructions import (
                INSTRUCTION_GROUP_TOAST,
                is_instruction_group_row,
            )

            if is_instruction_group_row(node):
                self.notify(INSTRUCTION_GROUP_TOAST, severity="warning")
                return
        except Exception:
            pass
        self._timeline_enter(node)

    def _timeline_enter(self, node: Any) -> None:
        """Turn the rail into the subject's timeline at the card's version."""
        from sase.ace.tui.util.trace import tui_trace  # noqa: PLC0415

        with tui_trace("memory.history.lens_open", lens="timeline"):
            timeline = self._time_timeline(node)
            if timeline is None:
                key = self._time_key(node)
                failed = False
                if key is not None:
                    try:
                        failed = key in getattr(self, "_history_failed", set())
                    except Exception:
                        failed = False
                    if not failed:
                        try:
                            self._ensure_history_load(key[0], key[1])
                        except Exception:
                            pass
                if failed:
                    self.notify("history unavailable · r retry", severity="warning")
                else:
                    self.notify("indexing history… · @ retries", severity="warning")
                return
            try:
                keyed = self._history_key_for_node(node)
            except Exception:
                keyed = None
            if keyed is None:
                return
            self._lens_snapshot = self._lens_take_notes_snapshot(node)
            self._lens = LENS_TIMELINE
            self._timeline_subject_node = node
            self._timeline_subject_key = (keyed[0], keyed[1])
            try:
                self._timeline_subject_identity = str(node.identity)
            except Exception:
                self._timeline_subject_identity = None
            try:
                applied = int(self._time_applied_ordinal(node) or 0)
            except (TypeError, ValueError):
                applied = 0
            self._timeline_base = None
            self._timeline_show_hidden = False
            self._timeline_filter = ""
            self._timeline_preview_pending = False
            self._timeline_scheduled = -1
            self._timeline_open_key = self._timeline_key_for_ordinal(timeline, applied)
            self._timeline_rebuild_rows(timeline)
            self._render_timeline_rail()
            try:
                self._update_header()
            except Exception:
                pass
            try:
                self._update_footer()
            except Exception:
                pass

    def _lens_exit_to_notes(self) -> None:
        """Restore Notes, keeping the card on the cursor's version (D3)."""
        snapshot = getattr(self, "_lens_snapshot", None)
        self._timeline_clear_state()
        try:
            self._lens = LENS_NOTES
        except Exception:
            pass
        try:
            self._lens_snapshot = None
        except Exception:
            pass
        from .memory_pane_lens import MemoryPaneLensMixin  # noqa: PLC0415

        try:
            MemoryPaneLensMixin._lens_restore_notes_snapshot(self, snapshot)  # type: ignore[arg-type]
        except Exception:
            pass

    def _timeline_clear_state(self) -> None:
        """Forget lens rows, cursor, base, and filter (base never carries)."""
        for attr, value in (
            ("_timeline_subject_node", None),
            ("_timeline_subject_key", None),
            ("_timeline_subject_identity", None),
            ("_timeline_rows_all", ()),
            ("_timeline_listed", ()),
            ("_timeline_cursor", 0),
            ("_timeline_open_key", None),
            ("_timeline_base", None),
            ("_timeline_show_hidden", False),
            ("_timeline_filter", ""),
            ("_timeline_preview_pending", False),
            ("_timeline_scheduled", -1),
        ):
            try:
                setattr(self, attr, value)
            except Exception:
                pass

    # --- rows -----------------------------------------------------------

    def _timeline_key_for_ordinal(
        self, timeline: dict[str, Any], ordinal: int
    ) -> tuple[str, str] | None:
        """Return the ``(label, class)`` key for *ordinal* (0 means now)."""
        import time as _time  # noqa: PLC0415

        listed, _, _ = _timeline_lens_rows(
            timeline, now_epoch=int(_time.time()), show_hidden=True
        )
        if int(ordinal) <= 0:
            for row in listed:
                if str(row.get("label", "")) == "now":
                    return ("now", str(row.get("class", "") or ""))
            return ("now", "")
        wanted = f"v{int(ordinal)}"
        for row in listed:
            if str(row.get("label", "")) == wanted and not bool(
                row.get("pseudo", False)
            ):
                return (wanted, str(row.get("class", "") or ""))
        return None

    def _timeline_rebuild_rows(self, timeline: dict[str, Any] | None) -> None:
        """Rebuild listed rows from the timeline and the lens filter."""
        import time as _time  # noqa: PLC0415

        if timeline is None:
            node = getattr(self, "_timeline_subject_node", None)
            timeline = self._time_timeline(node)
        if not isinstance(timeline, dict):
            self._timeline_rows_all = ()
            self._timeline_listed = ()
            return
        listed, _, _ = _timeline_lens_rows(
            timeline,
            now_epoch=int(_time.time()),
            show_hidden=bool(getattr(self, "_timeline_show_hidden", False)),
        )
        self._timeline_rows_all = tuple(listed)
        query = str(getattr(self, "_timeline_filter", "") or "").strip()
        if query:
            try:
                from sase.pager.history_kit import filter_picker_rows  # noqa: PLC0415

                listed = cast(
                    tuple[dict[str, Any], ...],
                    tuple(filter_picker_rows(tuple(listed), query)),
                )
            except Exception:
                pass
        self._timeline_listed = tuple(listed)
        cursor = int(getattr(self, "_timeline_cursor", 0) or 0)
        if self._timeline_listed:
            self._timeline_cursor = max(0, min(cursor, len(self._timeline_listed)))
        else:
            self._timeline_cursor = 0

    def _timeline_cursor_row(self) -> dict[str, Any] | None:
        """Return the listed row under the lens cursor, if any."""
        listed = getattr(self, "_timeline_listed", ())
        cursor = int(getattr(self, "_timeline_cursor", 0) or 0)
        if 0 <= cursor < len(listed):
            row = listed[cursor]
            return dict(row) if isinstance(row, dict) else None
        return None

    def _timeline_ordinal_for_row(self, row: dict[str, Any] | None) -> int | None:
        """Return the card pin ordinal for a lens row; None for summary."""
        if row is None:
            return None
        if str(row.get("id", "")) == HIDDEN_SUMMARY_ID:
            return None
        try:
            return int(row.get("ordinal", 0) or 0)
        except (TypeError, ValueError):
            return None

    def _timeline_row_index_for_ordinal(self, ordinal: int) -> int:
        """Return the listed index showing *ordinal* (0 means the now row)."""
        listed = getattr(self, "_timeline_listed", ())
        if int(ordinal) <= 0:
            for index, row in enumerate(listed):
                if isinstance(row, dict) and str(row.get("label", "")) == "now":
                    return index
            return 0
        wanted = f"v{int(ordinal)}"
        for index, row in enumerate(listed):
            if (
                isinstance(row, dict)
                and str(row.get("label", "")) == wanted
                and not bool(row.get("pseudo", False))
            ):
                return index
        return 0

    # --- rail rendering ---------------------------------------------------

    def _render_timeline_rail(self) -> None:
        """Paint the lens rows into the Notes rail widget."""
        try:
            option_list = self._note_list()
        except Exception:
            return
        listed = tuple(getattr(self, "_timeline_listed", ()))
        cursor = int(getattr(self, "_timeline_cursor", 0) or 0)
        open_key = getattr(self, "_timeline_open_key", None)
        base = getattr(self, "_timeline_base", None)
        pending = bool(getattr(self, "_timeline_preview_pending", False))
        try:
            width = int(option_list.size.width or 0) - 2
        except Exception:
            width = 0
        available = max(20, width or 40)
        try:
            from sase.pager.history_kit import (  # noqa: PLC0415
                format_picker_row,
                picker_columns,
            )

            columns = picker_columns(listed, available)
        except Exception:
            columns = None
        options: list[Option] = []
        for index, row in enumerate(listed):
            if not isinstance(row, dict):
                continue
            label = str(row.get("label", "") or "")
            class_name = str(row.get("class", "") or "")
            is_cursor = index == cursor
            is_open = open_key == (label, class_name)
            try:
                if columns is None:
                    text: Any = Text(f"{label} {row.get('change', '')}".strip())
                else:
                    text = format_picker_row(
                        row, columns, is_open=is_open, is_cursor=is_cursor
                    )
            except Exception:
                text = Text(label)
            try:
                if (
                    base is not None
                    and int(row.get("ordinal", -1) or 0) == int(base)
                    and not is_cursor
                ):
                    text = Text.assemble(text, Text("  ◇", style="dim"))
            except Exception:
                pass
            try:
                if pending and is_cursor and not is_open:
                    text = Text.assemble(text, Text(" …", style="dim"))
            except Exception:
                pass
            options.append(Option(text, id=_timeline_row_id(label, class_name, 0)))
        hidden_line = ""
        try:
            import time as _time  # noqa: PLC0415

            node = getattr(self, "_timeline_subject_node", None)
            timeline = self._time_timeline(node)
            hidden_rows = _timeline_hidden_rows(
                timeline if isinstance(timeline, dict) else None,
                now_epoch=int(_time.time()),
            )
            if hidden_rows and not bool(getattr(self, "_timeline_show_hidden", False)):
                hidden_line = _timeline_hidden_summary_text(hidden_rows)
        except Exception:
            hidden_line = ""
        if hidden_line:
            options.append(Option(Text(hidden_line, style="dim"), id=HIDDEN_SUMMARY_ID))
        try:
            self._timeline_has_hidden_line = bool(hidden_line)
        except Exception:
            pass
        try:
            guard = self._selection_guard
        except Exception:
            guard = None
        try:
            option_list.clear_options()
            # One batched add: per-row adds reflow the list every time
            # and miss the warm-open budget on long timelines.
            option_list.add_options(options)
            if options:
                row = max(0, min(cursor, len(options) - 1))
                if guard is not None:
                    try:
                        guard.prepare(f"timeline:{row}", row)
                    except Exception:
                        pass
                option_list.highlighted = row
        except Exception:
            pass
        try:
            self._resize_timeline_rail()
        except Exception:
            pass

    def _resize_timeline_rail(self) -> None:
        """Pin the rail to its maximum width in the Timeline lens."""
        try:
            from textual.containers import Horizontal  # noqa: PLC0415

            body = self.query_one("#memory-panel-body", Horizontal)
            note_list = self._note_list()
            available = int(body.size.width or 0)
        except Exception:
            return
        width = _TIMELINE_RAIL_MAX_WIDTH
        if available > 0:
            room = available - 56 - 1
            width = min(width, max(_TIMELINE_RAIL_MIN_WIDTH, room))
        width = max(_TIMELINE_RAIL_MIN_WIDTH, width)
        try:
            current = note_list.styles.width
            if current is not None and current.is_cells and int(current.value) == width:
                return
            note_list.styles.width = width
        except Exception:
            pass

    # --- highlight, preview, stale drops ----------------------------------

    def on_option_list_option_highlighted(self, event: Any) -> None:
        """Route rail motion to the lens cursor; Notes falls through.

        Textual invokes every ``on_*`` override along the MRO, so the
        lens branch stops the event to keep the Notes handler from
        treating a version highlight as a subject change; outside the
        lens this handler does nothing and the Notes handler runs once.
        """
        if not self._lens_is_timeline():
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
        listed = tuple(getattr(self, "_timeline_listed", ()))
        summary_index = len(listed)
        if not 0 <= idx <= summary_index:
            return
        try:
            current = self._note_list().highlighted
            current = int(current) if current is not None else idx
        except Exception:
            current = idx
        try:
            guard = self._selection_guard
            if guard is not None and guard.should_ignore(
                f"timeline:{idx}",
                idx,
                current_identity=f"timeline:{current}",
                current_row=current,
            ):
                return
        except Exception:
            pass
        if idx == summary_index:
            return  # The hidden-summary row holds the pin, it moves nothing.
        self._timeline_cursor = idx
        self._timeline_scheduled = idx
        try:
            row = listed[idx] if 0 <= idx < len(listed) else None
            ordinal = self._timeline_ordinal_for_row(
                dict(row) if isinstance(row, dict) else None
            )
            needs_load = False
            if ordinal is not None and int(ordinal) > 0:
                node = getattr(self, "_timeline_subject_node", None)
                key = self._time_key(node)
                if key is not None and (key[0], key[1], int(ordinal)) not in getattr(
                    self, "_time_bodies", {}
                ):
                    needs_load = True
            self._timeline_preview_pending = bool(needs_load)
            if needs_load:
                self._render_timeline_rail()
        except Exception:
            pass
        try:
            debouncer = self._debouncer
            if debouncer is not None:
                debouncer.schedule(self._timeline_preview_fire)
            else:
                self._timeline_preview_fire()
        except Exception:
            pass

    def _timeline_preview_fire(self) -> None:
        """Apply the scheduled lens cursor to the card (last wins)."""
        if not self._lens_is_timeline():
            return
        cursor = int(getattr(self, "_timeline_cursor", 0) or 0)
        if cursor != int(getattr(self, "_timeline_scheduled", -1) or -1):
            return  # A newer motion already won.
        row = self._timeline_cursor_row()
        ordinal = self._timeline_ordinal_for_row(row)
        if ordinal is None:
            return
        node = getattr(self, "_timeline_subject_node", None)
        if node is None:
            return
        key = self._time_key(node)
        if key is None:
            return
        if int(ordinal) <= 0:
            self._timeline_preview_pending = False
            try:
                self._time_pins.pop(key, None)
                self._time_applied.pop(key, None)
                self._time_pending.pop(key, None)
            except Exception:
                pass
            try:
                self._render_note_card()
            except Exception:
                pass
            return
        try:
            self._time_pins[key] = int(ordinal)
            self._time_pending.pop(key, None)
        except Exception:
            pass
        try:
            if self._ensure_time_body(key, node, int(ordinal)):
                self._timeline_preview_pending = False
                self._apply_time_pin(key, node, int(ordinal))
            else:
                self._render_note_card()
        except Exception:
            pass

    def _render_note_card(self) -> None:
        """Render the card, then settle the lens rail's pending marker."""
        try:
            from .memory_panel_view import (  # noqa: PLC0415
                MemoryPanelViewMixin,
            )

            MemoryPanelViewMixin._render_note_card(self)  # type: ignore[arg-type]
        except Exception:
            return
        if not self._lens_is_timeline():
            return
        try:
            node = getattr(self, "_timeline_subject_node", None)
            applied = int(self._time_applied_ordinal(node) or 0)
            cursor_row = self._timeline_cursor_row()
            cursor_ordinal = self._timeline_ordinal_for_row(cursor_row)
            settled = cursor_ordinal is None or int(cursor_ordinal) == applied
            if settled and bool(getattr(self, "_timeline_preview_pending", False)):
                self._timeline_preview_pending = False
                self._render_timeline_rail()
        except Exception:
            pass

    def _timeline_sync_cursor_to_pin(self) -> None:
        """Move the lens cursor onto the card's pin after a step key."""
        if not self._lens_is_timeline():
            return
        try:
            node = getattr(self, "_timeline_subject_node", None)
            pinned = int(self._time_pinned_ordinal(node) or 0)
        except (TypeError, ValueError):
            return
        except Exception:
            return
        try:
            index = self._timeline_row_index_for_ordinal(pinned)
        except Exception:
            return
        self._timeline_cursor = index
        self._timeline_scheduled = index
        self._timeline_preview_pending = False
        try:
            option_list = self._note_list()
            guard = self._selection_guard
            if guard is not None:
                try:
                    guard.prepare(f"timeline:{index}", index)
                except Exception:
                    pass
            listed = tuple(getattr(self, "_timeline_listed", ()))
            if 0 <= index < len(listed):
                option_list.highlighted = index
        except Exception:
            pass

    def _step_time_pin(self, intent: str) -> None:
        """Step the card, then carry the lens cursor with the pin."""
        try:
            from .memory_pane_time import MemoryPaneTimeMixin  # noqa: PLC0415

            MemoryPaneTimeMixin._step_time_pin(self, intent)  # type: ignore[arg-type]
        except Exception:
            return
        try:
            self._timeline_sync_cursor_to_pin()
        except Exception:
            pass

    # --- base, hidden, filter ----------------------------------------------

    def action_history_compare_base(self) -> None:
        """Set the cursor row as the compare base; again clears it."""
        if not self._lens_is_timeline():
            return
        row = self._timeline_cursor_row()
        ordinal = self._timeline_ordinal_for_row(row)
        if ordinal is None:
            self.notify("no version under the cursor", severity="warning")
            return
        try:
            if self._timeline_base is not None and int(self._timeline_base) == int(
                ordinal
            ):
                self._timeline_base = None
                self.notify("compare base cleared")
            else:
                self._timeline_base = int(ordinal)
                cursor_label = str((row or {}).get("label", "") or "")
                base_label = _version_name(int(ordinal))
                if cursor_label and cursor_label != base_label:
                    self.notify(f"comparing {base_label} → {cursor_label}")
                else:
                    self.notify(f"compare base {base_label}")
        except Exception:
            return
        try:
            self._render_timeline_rail()
        except Exception:
            pass
        try:
            self._update_footer()
        except Exception:
            pass

    def action_history_toggle_hidden(self) -> None:
        """Reveal hidden versions in the Timeline lens (``.``)."""
        if not self._lens_is_timeline():
            return
        try:
            self._timeline_show_hidden = not bool(
                getattr(self, "_timeline_show_hidden", False)
            )
        except Exception:
            self._timeline_show_hidden = False
        try:
            node = getattr(self, "_timeline_subject_node", None)
            timeline = self._time_timeline(node)
            cursor_row = self._timeline_cursor_row()
            keep = self._timeline_ordinal_for_row(cursor_row)
            self._timeline_rebuild_rows(timeline)
            if keep is not None:
                self._timeline_cursor = self._timeline_row_index_for_ordinal(keep)
            self._render_timeline_rail()
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

    def on_input_changed(self, event: Any) -> None:
        """Route the ``/`` filter to the lens rows inside the Timeline lens.

        Textual invokes every ``on_*`` override along the MRO, so the
        lens branch stops the event to keep the Notes filter (and its
        body flag) untouched; outside the lens this handler does
        nothing and the Notes handler runs once.
        """
        if not self._lens_is_timeline():
            return
        try:
            from .memory_panel_state import _FILTER_INPUT_ID  # noqa: PLC0415

            if getattr(event.input, "id", None) == _FILTER_INPUT_ID:
                try:
                    event.prevent_default()
                    event.stop()
                except Exception:
                    pass
                self._apply_timeline_filter(str(event.value or ""))
        except Exception:
            pass

    def _apply_timeline_filter(self, pattern: str) -> None:
        """Filter lens rows; the Notes filter is untouched underneath."""
        try:
            self._timeline_filter = pattern
        except Exception:
            pass
        try:
            node = getattr(self, "_timeline_subject_node", None)
            timeline = self._time_timeline(node)
            cursor_row = self._timeline_cursor_row()
            keep = self._timeline_ordinal_for_row(cursor_row)
            self._timeline_rebuild_rows(timeline)
            if keep is not None:
                self._timeline_cursor = self._timeline_row_index_for_ordinal(keep)
            self._render_timeline_rail()
        except Exception:
            pass
        try:
            self._update_header()
        except Exception:
            pass

    # --- selection, header, footer ------------------------------------------

    def _selected_row(self) -> Any | None:
        """Return the lens subject in the Timeline lens; Notes otherwise."""
        if self._lens_is_timeline():
            return getattr(self, "_timeline_subject_node", None)
        try:
            from .memory_panel_state import (  # noqa: PLC0415
                MemoryPanelStateMixin,
            )

            return MemoryPanelStateMixin._selected_row(self)  # type: ignore[arg-type]
        except Exception:
            return None

    def _update_header(self) -> None:
        """Name the lens, scope, and subject in the Timeline lens."""
        if not self._lens_is_timeline():
            try:
                from .memory_panel_view import (  # noqa: PLC0415
                    MemoryPanelViewMixin,
                )

                MemoryPanelViewMixin._update_header(self)  # type: ignore[arg-type]
            except Exception:
                pass
            return
        try:
            from textual.widgets import Static  # noqa: PLC0415
            from rich.text import Text as _Text  # noqa: PLC0415

            node = getattr(self, "_timeline_subject_node", None)
            timeline = self._time_timeline(node)
            _, hidden_count, total = _timeline_lens_rows(
                timeline if isinstance(timeline, dict) else None,
                now_epoch=0,
                show_hidden=True,
            )
            scope_name = ""
            try:
                snapshot = getattr(self, "_snapshot", None)
                scope = (
                    getattr(snapshot, "scope", None) if snapshot is not None else None
                )
                scope_name = str(getattr(scope, "display_name", "") or "")
            except Exception:
                scope_name = ""
            detail = _timeline_lens_header_detail(
                total_committed=total,
                hidden_count=hidden_count,
                show_hidden=bool(getattr(self, "_timeline_show_hidden", False)),
                query=str(getattr(self, "_timeline_filter", "") or ""),
            )
            header = lens_header_text(
                lens=LENS_TIMELINE,
                scope_display_name=scope_name,
                subject_display=_timeline_subject_display(node),
                detail=detail,
            )
            accent = str(getattr(self, "_accent", "#87D7FF") or "#87D7FF")
            text = _Text(header or "MEMORY · timeline", style=f"bold {accent}")
            self.query_one("#memory-panel-header", Static).update(text)
        except Exception:
            pass

    def _update_footer(self) -> None:
        """Show the lens footer (inert keys hidden) in the Timeline lens."""
        if not self._lens_is_timeline():
            try:
                from .memory_panel_view import (  # noqa: PLC0415
                    MemoryPanelViewMixin,
                )

                MemoryPanelViewMixin._update_footer(self)  # type: ignore[arg-type]
            except Exception:
                pass
            return
        try:
            from textual.widgets import Static  # noqa: PLC0415

            row = self._timeline_cursor_row()
            cursor_ordinal = self._timeline_ordinal_for_row(row)
            compare = _timeline_compare_text(
                int(cursor_ordinal or 0) if cursor_ordinal is not None else 0,
                getattr(self, "_timeline_base", None),
            )
            footer = _timeline_lens_footer(
                getattr(self, "_keymaps", None),
                compare_text=compare,
                show_hidden=bool(getattr(self, "_timeline_show_hidden", False)),
            )
            widget = self.query_one("#memory-panel-footer", Static)
            widget.update(footer)
            widget.display = bool(footer)
        except Exception:
            pass

    # --- travel, follow, scope -----------------------------------------------

    def action_travel_back(self) -> None:
        """Exit the lens on ``h``/backspace; walk the trail in Notes."""
        if self._lens_is_timeline():
            self._lens_exit_to_notes()
            return
        try:
            from .memory_panel_travel import (  # noqa: PLC0415
                MemoryPanelTravelMixin,
            )

            MemoryPanelTravelMixin.action_travel_back(self)  # type: ignore[arg-type]
        except Exception:
            pass

    def action_follow_link(self) -> None:
        """Open the pager at the cursor's pin, view, and base (lens ``⏎``)."""
        if self._lens_is_timeline():
            self._timeline_open_at_cursor()
            return
        try:
            from .memory_panel_travel import (  # noqa: PLC0415
                MemoryPanelTravelMixin,
            )

            MemoryPanelTravelMixin.action_follow_link(self)  # type: ignore[arg-type]
        except Exception:
            pass

    def action_follow_link_number(self, number: int) -> None:
        """Chip shortcuts are inert in the Timeline lens."""
        if self._lens_is_timeline():
            return
        try:
            from .memory_panel_travel import (  # noqa: PLC0415
                MemoryPanelTravelMixin,
            )

            MemoryPanelTravelMixin.action_follow_link_number(self, number)  # type: ignore[arg-type]
        except Exception:
            pass

    # --- Notes-only actions are inert or re-homed in the lens -----------------

    def action_first_note(self) -> None:
        """Jump to the first lens row inside the Timeline lens."""
        if self._lens_is_timeline():
            try:
                option_list = self._note_list()
                guard = self._selection_guard
                if guard is not None:
                    try:
                        guard.prepare("timeline:0", 0)
                    except Exception:
                        pass
                option_list.highlighted = 0
            except Exception:
                pass
            return
        try:
            from .memory_panel_navigation import (  # noqa: PLC0415
                MemoryPanelNavigationMixin,
            )

            MemoryPanelNavigationMixin.action_first_note(self)  # type: ignore[arg-type]
        except Exception:
            pass

    def action_last_note(self) -> None:
        """Jump to the last lens row inside the Timeline lens."""
        if self._lens_is_timeline():
            try:
                option_list = self._note_list()
                listed = tuple(getattr(self, "_timeline_listed", ()))
                target = max(0, len(listed) - 1)
                if bool(getattr(self, "_timeline_has_hidden_line", False)):
                    target += 1
                guard = self._selection_guard
                if guard is not None:
                    try:
                        guard.prepare(f"timeline:{target}", target)
                    except Exception:
                        pass
                option_list.highlighted = target
            except Exception:
                pass
            return
        try:
            from .memory_panel_navigation import (  # noqa: PLC0415
                MemoryPanelNavigationMixin,
            )

            MemoryPanelNavigationMixin.action_last_note(self)  # type: ignore[arg-type]
        except Exception:
            pass

    def action_toggle_web(self) -> None:
        """Web expansion is a Notes action; inert in the Timeline lens."""
        if self._lens_is_timeline():
            return
        try:
            from .memory_panel_navigation import (  # noqa: PLC0415
                MemoryPanelNavigationMixin,
            )

            MemoryPanelNavigationMixin.action_toggle_web(self)  # type: ignore[arg-type]
        except Exception:
            pass

    def action_next_strand(self) -> None:
        """Strand jumps are Notes actions; inert in the Timeline lens."""
        if self._lens_is_timeline():
            return
        try:
            from .memory_panel_navigation import (  # noqa: PLC0415
                MemoryPanelNavigationMixin,
            )

            MemoryPanelNavigationMixin.action_next_strand(self)  # type: ignore[arg-type]
        except Exception:
            pass

    def action_prev_strand(self) -> None:
        """Strand jumps are Notes actions; inert in the Timeline lens."""
        if self._lens_is_timeline():
            return
        try:
            from .memory_panel_navigation import (  # noqa: PLC0415
                MemoryPanelNavigationMixin,
            )

            MemoryPanelNavigationMixin.action_prev_strand(self)  # type: ignore[arg-type]
        except Exception:
            pass

    def action_next_link(self) -> None:
        """Link chips are Notes actions; inert in the Timeline lens."""
        if self._lens_is_timeline():
            return
        try:
            from .memory_panel_travel import (  # noqa: PLC0415
                MemoryPanelTravelMixin,
            )

            MemoryPanelTravelMixin.action_next_link(self)  # type: ignore[arg-type]
        except Exception:
            pass

    def action_prev_link(self) -> None:
        """Link chips are Notes actions; inert in the Timeline lens."""
        if self._lens_is_timeline():
            return
        try:
            from .memory_panel_travel import (  # noqa: PLC0415
                MemoryPanelTravelMixin,
            )

            MemoryPanelTravelMixin.action_prev_link(self)  # type: ignore[arg-type]
        except Exception:
            pass

    def action_toggle_body_filter(self) -> None:
        """Body-match scope is a Notes filter; inert in the Timeline lens."""
        if self._lens_is_timeline():
            return
        try:
            from .memory_panel_navigation import (  # noqa: PLC0415
                MemoryPanelNavigationMixin,
            )

            MemoryPanelNavigationMixin.action_toggle_body_filter(self)  # type: ignore[arg-type]
        except Exception:
            pass

    def action_refresh(self) -> None:
        """Leave the lens before reloading the scope (pins never carry)."""
        if self._lens_is_timeline():
            try:
                self._lens_exit_to_notes()
            except Exception:
                pass
        try:
            from .memory_panel_navigation import (  # noqa: PLC0415
                MemoryPanelNavigationMixin,
            )

            MemoryPanelNavigationMixin.action_refresh(self)  # type: ignore[arg-type]
        except Exception:
            pass

    def _on_scope_picked(self, key: str | None) -> None:
        """Leave the lens before switching to the picked scope."""
        if self._lens_is_timeline():
            try:
                self._timeline_clear_state()
                self._lens = LENS_NOTES
                self._lens_snapshot = None
            except Exception:
                pass
        try:
            from .memory_pane_loading import (  # noqa: PLC0415
                MemoryPaneLoadingMixin,
            )

            MemoryPaneLoadingMixin._on_scope_picked(self, key)  # type: ignore[arg-type]
        except Exception:
            pass

    def _cycle_scope(self, delta: int) -> None:
        """Leave the lens (base never carries) before cycling scopes."""
        if self._lens_is_timeline():
            try:
                self._timeline_clear_state()
                self._lens = LENS_NOTES
                self._lens_snapshot = None
            except Exception:
                pass
        try:
            from .memory_panel_navigation import (  # noqa: PLC0415
                MemoryPanelNavigationMixin,
            )

            MemoryPanelNavigationMixin._cycle_scope(self, delta)  # type: ignore[arg-type]
        except Exception:
            pass

    # --- hand-off --------------------------------------------------------------

    def _history_initial_revision(self) -> str:
        """Return the pager revision for the lens cursor (``H``/``⏎``)."""
        if self._lens_is_timeline():
            try:
                row = self._timeline_cursor_row()
                label = str((row or {}).get("label", "") or "")
                if label == "stg":
                    return "staged"
                if label and label != "now":
                    ordinal = self._timeline_ordinal_for_row(row)
                    if ordinal is not None and int(ordinal) > 0:
                        return f"v{int(ordinal)}"
                return "now"
            except Exception:
                return "now"
        try:
            from .memory_pane_time import MemoryPaneTimeMixin  # noqa: PLC0415

            return MemoryPaneTimeMixin._history_initial_revision(self)  # type: ignore[arg-type]
        except Exception:
            return "now"

    def _history_diff_carry(self) -> tuple[str, str | None]:
        """Return the pager ``(view, compare_base)`` for the lens cursor."""
        if self._lens_is_timeline():
            try:
                view = (
                    "diff" if bool(getattr(self, "_time_diff_view", False)) else "read"
                )
            except Exception:
                view = "read"
            try:
                base = getattr(self, "_timeline_base", None)
                return (
                    view,
                    f"v{int(base)}" if base is not None and int(base) > 0 else None,
                )
            except Exception:
                return (view, None)
        try:
            from .memory_pane_diff import MemoryPaneDiffMixin  # noqa: PLC0415

            return MemoryPaneDiffMixin._history_diff_carry(self)  # type: ignore[arg-type]
        except Exception:
            return ("read", None)

    def _history_explicit_base(self) -> bool:
        """Carry the lens ``b`` base when the cursor sits on now."""
        if self._lens_is_timeline():
            try:
                return getattr(self, "_timeline_base", None) is not None
            except Exception:
                return False
        return False

    def _timeline_open_at_cursor(self) -> None:
        """Push the pager at the cursor's pin, view, and base."""
        row = self._timeline_cursor_row()
        if self._timeline_ordinal_for_row(row) is None:
            self.notify("no version under the cursor", severity="warning")
            return
        try:
            from .memory_pane_history import (  # noqa: PLC0415
                MemoryPaneHistoryMixin,
            )

            MemoryPaneHistoryMixin.action_open_history(self)  # type: ignore[arg-type]
        except Exception as exc:
            try:
                self.notify(f"Could not open pager: {exc}", severity="error")
            except Exception:
                pass


__all__ = [
    "HIDDEN_SUMMARY_ID",
    "MemoryPaneTimelineLensMixin",
]

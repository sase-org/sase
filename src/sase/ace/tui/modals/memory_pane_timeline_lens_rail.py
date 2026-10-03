"""Timeline lens rail rendering (``@`` timeline lens)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from rich.text import Text
from textual.widgets import OptionList
from textual.widgets.option_list import Option

from ._memory_pane_timeline_lens_shared import (
    HIDDEN_SUMMARY_ID,
    TIMELINE_ROW_PREFIX,
    newest_first,
)

if TYPE_CHECKING:
    from textual.widget import Widget as _MixinBase
else:
    _MixinBase = object

#: Rail width bounds mirror the Notes rail (see
#: ``sase.ace.tui.modals.memory_panel_rendering``): never narrower than
#: the historical width, never wider than the card's share.
_TIMELINE_RAIL_MIN_WIDTH = 32
_TIMELINE_RAIL_MAX_WIDTH = 52


def _timeline_row_id(label: str, class_name: str, ordinal: int) -> str:
    """Return the stable rail id for one picker row."""
    return f"{TIMELINE_ROW_PREFIX}{label}:{class_name}:{int(ordinal)}"


def _timeline_row_text(
    row: dict[str, Any],
    columns: Any,
    format_picker_row: Any,
    *,
    is_cursor: bool,
    is_open: bool,
    base: int | None,
    pending: bool,
) -> Any:
    """Return one lens row's prompt: picker cells plus ``◇``/``…`` marks."""
    label = str(row.get("label", "") or "")
    try:
        if columns is None:
            text: Any = Text(f"{label} {row.get('change', '')}".strip())
        else:
            text = format_picker_row(row, columns, is_open=is_open, is_cursor=is_cursor)
    except Exception:
        text = Text(label)
    try:
        if (
            base is not None
            and int(row.get("ordinal", -1) or 0) == int(base)
            and not is_cursor
        ):
            # ``◇`` takes the cursor cell of the picker's two-cell marker
            # column, so the row keeps its width and never wraps.
            if columns is not None and text.plain[1:2] == " ":
                text = Text.assemble(text[:1], Text("◇", style="dim"), text[2:])
            else:
                text = Text.assemble(Text("◇ ", style="dim"), text)
    except Exception:
        pass
    if pending and is_cursor and not is_open:
        text = Text.assemble(text, Text(" …", style="dim"))
    return text


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

        rows = build_picker_rows(newest_first(timeline), now_epoch=int(now_epoch))
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


class MemoryPaneTimelineLensRailMixin(_MixinBase):
    """Timeline lens rail rows, repaint, and width."""

    if TYPE_CHECKING:
        _selection_guard: Any
        _timeline_base: int | None
        _timeline_columns: Any
        _timeline_cursor: int
        _timeline_has_hidden_line: bool
        _timeline_listed: tuple[dict[str, Any], ...]
        _timeline_open_key: tuple[str, str] | None
        _timeline_preview_pending: bool
        _timeline_show_hidden: bool
        _timeline_subject_node: Any | None

        def _note_list(self) -> OptionList: ...
        def _time_timeline(self, node: Any | None) -> dict[str, Any] | None: ...
        def _timeline_ordinal_for_row(
            self, row: dict[str, Any] | None
        ) -> int | None: ...

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
        self._timeline_columns = columns
        options: list[Option] = []
        for index, row in enumerate(listed):
            if not isinstance(row, dict):
                continue
            label = str(row.get("label", "") or "")
            class_name = str(row.get("class", "") or "")
            text = _timeline_row_text(
                row,
                columns,
                format_picker_row,
                is_cursor=index == cursor,
                is_open=open_key == (label, class_name),
                base=base,
                pending=pending,
            )
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

    def _repaint_timeline_rows(self, *indices: int) -> None:
        """Repaint only *indices* so cursor and base marks follow motion.

        A full rail render reflows every row; motion only changes the
        rows it leaves and lands on, so this keeps ``j``/``k`` cheap.
        """
        columns = getattr(self, "_timeline_columns", None)
        if columns is None:
            self._render_timeline_rail()
            return
        try:
            from sase.pager.history_kit import format_picker_row  # noqa: PLC0415

            option_list = self._note_list()
        except Exception:
            return
        listed = tuple(getattr(self, "_timeline_listed", ()))
        cursor = int(getattr(self, "_timeline_cursor", 0) or 0)
        open_key = getattr(self, "_timeline_open_key", None)
        base = getattr(self, "_timeline_base", None)
        pending = bool(getattr(self, "_timeline_preview_pending", False))
        for index in sorted(set(indices)):
            if not 0 <= index < len(listed) or not isinstance(listed[index], dict):
                continue
            row = listed[index]
            label = str(row.get("label", "") or "")
            class_name = str(row.get("class", "") or "")
            try:
                option_list.replace_option_prompt_at_index(
                    index,
                    _timeline_row_text(
                        row,
                        columns,
                        format_picker_row,
                        is_cursor=index == cursor,
                        is_open=open_key == (label, class_name),
                        base=base,
                        pending=pending,
                    ),
                )
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


__all__ = [
    "MemoryPaneTimelineLensRailMixin",
    "_timeline_hidden_rows",
    "_timeline_hidden_summary_text",
    "_timeline_row_id",
]

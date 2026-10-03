"""Timeline lens entry, exit, and rows state (``@`` timeline lens)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from ._memory_pane_timeline_lens_shared import HIDDEN_SUMMARY_ID
from .memory_pane_lens import LENS_NOTES, LENS_TIMELINE

if TYPE_CHECKING:
    from textual.widget import Widget as _MixinBase
else:
    _MixinBase = object


def _no_history_refusal(timeline: dict[str, Any]) -> str | None:
    """Return the honest ``@`` refusal when *timeline* has no versions.

    An untracked subject or a no-VCS scope has nothing to step through,
    so ``@`` names that state instead of opening an empty lens.
    """
    from .memory_pane_history import honest_no_history_toast

    try:
        committed = any(
            isinstance(row, dict) and int(row.get("ordinal", 0) or 0) > 0
            for row in timeline.get("versions", ()) or ()
        )
    except (AttributeError, TypeError, ValueError):
        committed = False
    if committed:
        return None
    return honest_no_history_toast(timeline)


class MemoryPaneTimelineLensStateMixin(_MixinBase):
    """Lens open/close and the listed-rows cursor model."""

    if TYPE_CHECKING:
        _history_failed: set[Any]
        _lens: Any
        _lens_snapshot: Any | None
        _timeline_base: int | None
        _timeline_cursor: int
        _timeline_filter: str
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

        def _ensure_history_load(self, scope_key: str, selector: str) -> None: ...
        def _history_key_for_node(
            self, node: Any | None
        ) -> tuple[str, str, Any, str] | None: ...
        def _lens_is_timeline(self) -> bool: ...
        def _lens_name(self) -> Any: ...
        def _lens_take_notes_snapshot(self, node: Any | None) -> Any: ...
        def _render_timeline_rail(self) -> None: ...
        def _selected_row(self) -> Any | None: ...
        def _time_applied_ordinal(self, node: Any | None) -> int: ...
        def _time_key(self, node: Any | None) -> tuple[str, str] | None: ...
        def _time_timeline(self, node: Any | None) -> dict[str, Any] | None: ...
        def _update_footer(self) -> None: ...
        def _update_header(self) -> None: ...
        def notify(self, *args: Any, **kwargs: Any) -> Any: ...

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
            refusal = _no_history_refusal(timeline)
            if refusal is not None:
                self.notify(refusal, severity="warning")
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

        from ._memory_pane_timeline_lens_shared import (  # noqa: PLC0415
            timeline_lens_rows,
        )

        listed, _, _ = timeline_lens_rows(
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

        from ._memory_pane_timeline_lens_shared import (  # noqa: PLC0415
            timeline_lens_rows,
        )

        if timeline is None:
            node = getattr(self, "_timeline_subject_node", None)
            timeline = self._time_timeline(node)
        if not isinstance(timeline, dict):
            self._timeline_rows_all = ()
            self._timeline_listed = ()
            return
        listed, _, _ = timeline_lens_rows(
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


__all__ = [
    "MemoryPaneTimelineLensStateMixin",
    "_no_history_refusal",
]

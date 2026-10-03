"""Timeline lens base, filter, header, and footer (``@`` lens)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .memory_pane_lens import LENS_TIMELINE, lens_header_text

if TYPE_CHECKING:
    from textual.widget import Widget as _MixinBase
else:
    _MixinBase = object


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


class MemoryPaneTimelineLensActionsMixin(_MixinBase):
    """Lens base, hidden toggle, filter, header, and footer."""

    if TYPE_CHECKING:
        _keymaps: Any
        _timeline_base: int | None
        _timeline_cursor: int
        _timeline_filter: str
        _timeline_listed: tuple[dict[str, Any], ...]
        _timeline_show_hidden: bool
        _timeline_subject_node: Any | None

        def _lens_is_timeline(self) -> bool: ...
        def _render_timeline_rail(self) -> None: ...
        def _time_timeline(self, node: Any | None) -> dict[str, Any] | None: ...
        def _timeline_cursor_row(self) -> dict[str, Any] | None: ...
        def _timeline_ordinal_for_row(
            self, row: dict[str, Any] | None
        ) -> int | None: ...
        def _timeline_rebuild_rows(self, timeline: dict[str, Any] | None) -> None: ...
        def _timeline_row_index_for_ordinal(self, ordinal: int) -> int: ...
        def notify(self, *args: Any, **kwargs: Any) -> Any: ...
        def query_one(self, *args: Any, **kwargs: Any) -> Any: ...

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

            from ._memory_pane_timeline_lens_shared import (  # noqa: PLC0415
                timeline_lens_rows,
            )

            node = getattr(self, "_timeline_subject_node", None)
            timeline = self._time_timeline(node)
            _, hidden_count, total = timeline_lens_rows(
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


__all__ = [
    "MemoryPaneTimelineLensActionsMixin",
    "_timeline_compare_text",
    "_timeline_lens_footer",
    "_timeline_lens_header_detail",
    "_timeline_subject_display",
]

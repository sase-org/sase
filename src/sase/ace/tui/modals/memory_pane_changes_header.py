"""Header, footer, selection, and scope travel for the Changes lens."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .memory_pane_lens import LENS_CHANGES, lens_header_text
from .memory_pane_review import review_chip

if TYPE_CHECKING:
    from textual.widget import Widget as _MixinBase
else:
    _MixinBase = object


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


class MemoryPaneChangesHeaderMixin(_MixinBase):
    """Name the lens window and home pager hand-off from rail actions."""

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

        def _changes_fetch(self) -> None: ...
        def _changes_open_at_cursor(
            self, subject_number: int | None = None
        ) -> None: ...
        def _changes_open_subject_number(self, number: int) -> None: ...
        def _lens_is_changes(self) -> bool: ...
        def _lens_exit_to_notes(self) -> None: ...
        def query_one(self, *args: Any, **kwargs: Any) -> Any: ...
        def _render_changes_rail(self) -> None: ...

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


__all__ = [
    "MemoryPaneChangesHeaderMixin",
    "_changes_lens_footer",
    "_changes_lens_header_detail",
]

"""Notes/Timeline/Changes lens framework for the Memory pane.

Owns the phase timeline-lens framework behind :class:`MemoryPane`
(epic design ``plan:202610/memory_history_tui.md`` §12 and §4.4): the
lens state (Notes default, Timeline, Changes), the Notes
snapshot/restore round trip, per-lens headers, and the shared Esc
ladder and travel-back routing. The Timeline and Changes lenses keep
their rows and keys in their own modules; this module never imports
them, so the framework stays dependency-free.

Lenses reuse the pane's list/detail grammar: entering a lens freezes
the Notes rail (cursor, filter, expansion, scroll, focus, trail, card
pin and view) and leaving restores it exactly. Rail motion inside a
lens pushes no trail entries.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from textual.widgets import OptionList

if TYPE_CHECKING:
    from textual.widget import Widget as _MixinBase
else:
    _MixinBase = object

#: Lens names. Notes is the default rail; Timeline and Changes re-skin
#: the same rail/detail grammar for one subject or for changesets.
LensName = Literal["notes", "timeline", "changes"]

LENS_NOTES: LensName = "notes"
LENS_TIMELINE: LensName = "timeline"
LENS_CHANGES: LensName = "changes"


@dataclass(frozen=True)
class _NotesSnapshot:
    """Everything leaving a lens restores on the Notes rail."""

    scope_index: int
    selected_identity: str | None
    filter_text: str
    filter_bodies: bool
    expanded_webs: frozenset[str]
    rail_row: int
    trail: tuple[str, ...]
    card_pin: int
    diff_view: bool


def lens_header_text(
    *,
    lens: str,
    scope_display_name: str,
    subject_display: str = "",
    detail: str = "",
) -> str:
    """Return the pane header line naming the lens, scope, and subject.

    Pure: ``MEMORY · <scope> › <subject> · timeline · <detail>`` in a
    lens, so the header always says where the rail came from and how
    to leave. Never raises.
    """
    try:
        if lens == LENS_TIMELINE:
            header = f"MEMORY · {scope_display_name} › {subject_display} · timeline"
        elif lens == LENS_CHANGES:
            header = f"MEMORY · {scope_display_name} · changes"
        else:
            return ""
        if detail:
            header += f" · {detail}"
        return header
    except Exception:
        return ""


class MemoryPaneLensMixin(_MixinBase):
    """Lens state, Notes snapshot/restore, and shared lens routing."""

    if TYPE_CHECKING:
        _current_note: str | None
        _expanded_webs: set[str]
        _filter_bodies: bool
        _filter_text: str
        _lens: LensName
        _lens_snapshot: _NotesSnapshot | None
        _ring: tuple[Any, ...]
        _scope_index: int
        _time_diff_view: bool
        _trail: list[str]
        app: Any
        is_mounted: bool

        def _apply_filter(
            self,
            pattern: str,
            *,
            include_bodies: bool,
            preferred_note: str | None = None,
        ) -> None: ...
        def _current_note_row(self) -> int: ...
        def _render_note_card(self) -> None: ...
        def _selected_row(self) -> Any | None: ...
        def _time_applied_ordinal(self, node: Any | None) -> int: ...
        def _time_pinned_ordinal(self, node: Any | None) -> int: ...
        def _update_footer(self) -> None: ...
        def _update_header(self) -> None: ...
        def notify(self, *args: Any, **kwargs: Any) -> Any: ...

    # --- state ----------------------------------------------------------

    def _lens_name(self) -> LensName:
        """Return the active lens (Notes when unset)."""
        try:
            lens = self._lens
        except AttributeError:
            return LENS_NOTES
        return lens if lens in ("notes", "timeline", "changes") else LENS_NOTES

    def _lens_is_timeline(self) -> bool:
        """Return whether the rail currently shows a Timeline lens."""
        return self._lens_name() == LENS_TIMELINE

    def _lens_is_active(self) -> bool:
        """Return whether any lens (Timeline or Changes) is open."""
        return self._lens_name() != LENS_NOTES

    # --- snapshot / restore ---------------------------------------------

    def _lens_take_notes_snapshot(self, node: Any | None) -> _NotesSnapshot:
        """Freeze the Notes rail so leaving the lens restores it exactly."""
        try:
            rail_row = self._current_note_row()
        except Exception:
            rail_row = 0
        try:
            pin = self._time_applied_ordinal(node)
        except Exception:
            pin = 0
        try:
            diff_view = bool(self._time_diff_view)
        except Exception:
            diff_view = False
        return _NotesSnapshot(
            scope_index=int(getattr(self, "_scope_index", 0) or 0),
            selected_identity=getattr(self, "_current_note", None),
            filter_text=str(getattr(self, "_filter_text", "") or ""),
            filter_bodies=bool(getattr(self, "_filter_bodies", False)),
            expanded_webs=frozenset(getattr(self, "_expanded_webs", set())),
            rail_row=max(0, int(rail_row or 0)),
            trail=tuple(getattr(self, "_trail", ())),
            card_pin=max(0, int(pin or 0)),
            diff_view=diff_view,
        )

    def _lens_restore_notes_snapshot(self, snapshot: _NotesSnapshot | None) -> None:
        """Restore a Notes snapshot taken on lens entry (D3).

        Re-applies filter text and body flag, expanded webs, the trail,
        the rail cursor, and the card pin/view the subject showed when
        the lens opened. Never raises: a partial restore still leaves a
        usable Notes rail.
        """
        if snapshot is None:
            return
        try:
            self._expanded_webs = set(snapshot.expanded_webs)
        except Exception:
            pass
        try:
            self._trail = list(snapshot.trail)
        except Exception:
            pass
        try:
            from .memory_panel_state import _NOTE_LIST_ID  # noqa: PLC0415
        except Exception:
            return
        try:
            option_list = self.query_one(f"#{_NOTE_LIST_ID}", OptionList)
        except Exception:
            option_list = None
        try:
            self._apply_filter(
                snapshot.filter_text,  # type: ignore[attr-defined]
                include_bodies=snapshot.filter_bodies,
                preferred_note=snapshot.selected_identity,
            )
        except Exception:
            pass
        if option_list is not None:
            try:
                from sase.ace.tui.util.selection import (  # noqa: PLC0415
                    restore_selection_by_identity,
                )

                rows = getattr(self, "_rows", ())
                row = restore_selection_by_identity(
                    rows,
                    prior_identity=snapshot.selected_identity,
                    prior_visual_row=snapshot.rail_row,
                    identity_fn=lambda node: node.identity,
                )
                if rows and 0 <= row < len(rows):
                    guard = getattr(self, "_selection_guard", None)
                    if guard is not None:
                        guard.prepare(rows[row].identity, row)
                    option_list.highlighted = row
                    self._current_note = rows[row].identity
            except Exception:
                pass
        try:
            self._render_note_card()
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
        try:
            if getattr(self, "is_mounted", False):
                option_list = self.query_one(f"#{_NOTE_LIST_ID}", OptionList)
                option_list.focus()
        except Exception:
            pass

    def _lens_force_close(self) -> None:
        """Drop lens state without restoring (scope changed under it)."""
        try:
            self._lens = LENS_NOTES
        except Exception:
            pass
        try:
            self._lens_snapshot = None
        except Exception:
            pass

    # --- shared routing ---------------------------------------------------

    def _lens_exit_if_in_lens(self) -> bool:
        """Leave the lens, restoring Notes; True when a rung was consumed.

        Exiting keeps the card on the lens cursor's version (D3): the
        pin set while previewing is intentionally left in place, so a
        second Esc returns it to now.
        """
        if not self._lens_is_active():
            return False
        try:
            self._lens_exit_to_notes()
        except Exception:
            self._lens_force_close()
        return True

    def _lens_exit_to_notes(self) -> None:
        """Leave the active lens; implemented by the lens mixins."""
        snapshot = getattr(self, "_lens_snapshot", None)
        self._lens_force_close()
        self._lens_restore_notes_snapshot(snapshot)


__all__ = [
    "LENS_CHANGES",
    "LENS_NOTES",
    "LENS_TIMELINE",
    "LensName",
    "MemoryPaneLensMixin",
    "lens_header_text",
]

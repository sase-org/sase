"""Timeline lens travel, Notes-inert actions, and pager hand-off."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .memory_pane_lens import LENS_NOTES

if TYPE_CHECKING:
    from textual.widget import Widget as _MixinBase
else:
    _MixinBase = object


class MemoryPaneTimelineLensNavigationMixin(_MixinBase):
    """Lens-aware travel, inert Notes keys, scope exits, and hand-off."""

    if TYPE_CHECKING:
        _lens: Any
        _lens_snapshot: Any | None
        _selection_guard: Any
        _time_diff_view: bool
        _timeline_base: int | None
        _timeline_has_hidden_line: bool
        _timeline_listed: tuple[dict[str, Any], ...]

        def _lens_exit_to_notes(self) -> None: ...
        def _lens_is_timeline(self) -> bool: ...
        def _note_list(self) -> Any: ...
        def _timeline_clear_state(self) -> None: ...
        def _timeline_cursor_row(self) -> dict[str, Any] | None: ...
        def _timeline_ordinal_for_row(
            self, row: dict[str, Any] | None
        ) -> int | None: ...
        def notify(self, *args: Any, **kwargs: Any) -> Any: ...

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
    "MemoryPaneTimelineLensNavigationMixin",
]

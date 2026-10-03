"""Armed ``ctrl+w`` target capture for ``PagerScreen``.

Owns the MRU other-pane preview, its capture, and opening a document in
the captured pane. Split layout, focus movement, and ratio stepping live
in :mod:`sase.pager._screen_split`; this module never imports that sibling.
"""

from __future__ import annotations

from typing import Any

from textual.containers import Vertical

from sase.ace.tui.util.pane_grid import (
    PaneGrid,
    focus_pane as grid_focus_pane,
    free_pane_id,
    other_target as grid_other_target,
)
from sase.pager.document import PagerDocument
from sase.pager.split import (
    PagerSplitLayout,
    split_axis,
    split_fits,
)
from sase.pager.view import PagerView, PagerViewSeed

__all__ = ["PagerScreenSplitArmMixin"]


class PagerScreenSplitArmMixin:
    """Own the armed ``ctrl+w`` capture and other-pane navigation."""

    def _clear_other_preview(self: Any) -> None:
        """Drop an armed ``ctrl+w`` capture and every lifted frame."""
        try:
            self._armed_other_target = None
        except Exception:
            pass
        try:
            by_id = self._views_by_id
        except AttributeError:
            return
        for view in list(by_id.values()):
            try:
                view.set_pane_preview(False)
            except Exception:
                pass

    def _disarm_other(self: Any) -> None:
        """Cancel an armed ``ctrl+w`` completely.

        Clears the preview, the captured target, any pending ``other``
        action on the hosted views, and repaints the footer so it no
        longer announces a target.
        """
        self._clear_other_preview()
        try:
            by_id = self._views_by_id
        except AttributeError:
            return
        for view in list(by_id.values()):
            try:
                if getattr(view, "_pending_action", "follow") == "other":
                    view._pending_action = "follow"  # type: ignore[attr-defined]
                    try:
                        view._label_pending_prefix = ""  # type: ignore[attr-defined]
                    except Exception:
                        pass
                    try:
                        repaint = getattr(view, "_repaint_label_state", None)
                        if callable(repaint):
                            repaint()
                    except Exception:
                        pass
            except Exception:
                pass
        try:
            self.focused_view._update_footer()  # type: ignore[attr-defined]
        except Exception:
            pass

    def _other_arm_pending(self: Any) -> bool:
        """Return whether any hosted view still holds an ``other`` arm."""
        try:
            by_id = self._views_by_id
        except AttributeError:
            return False
        for view in list(by_id.values()):
            try:
                if getattr(view, "_pending_action", "follow") == "other":
                    return True
            except Exception:
                continue
        return False

    def _disarm_if_armed(self: Any) -> None:
        """Cancel a pending ``other`` arm before a focus/structure change."""
        try:
            if self._other_arm_pending():
                self._disarm_other()
        except Exception:
            pass

    def _arm_other_preview(self: Any, source: PagerView) -> None:
        """Capture the MRU other pane and lift its frame while armed."""
        self._clear_other_preview()
        try:
            grid = self._grid
            source_id = self._pane_id_of(source)
            if source_id is None or source_id not in grid.panes:
                return
            target = grid_other_target(grid_focus_pane(grid, source_id))
            if target is None:
                return
            view = self._views_by_id.get(target)
            if view is None:
                return
            self._armed_other_target = (target, view)
            view.set_pane_preview(True)
        except Exception:
            try:
                self._armed_other_target = None
            except Exception:
                pass

    def _take_armed_target(self: Any) -> Any | None:
        """Consume the armed ``ctrl+w`` target, clearing its preview.

        Returns the captured view only when it still hosts the captured
        pane ID — the result is never redirected to a substitute pane.
        """
        try:
            slot = self._armed_other_target
        except AttributeError:
            slot = None
        self._clear_other_preview()
        if slot is None:
            return None
        try:
            pane_id, view = slot
        except (TypeError, ValueError):
            return None
        try:
            grid = self._grid
            by_id = self._views_by_id
        except AttributeError:
            return None
        if pane_id not in grid.panes or by_id.get(pane_id) is not view:
            return None
        return view

    def focus_other_view(self: Any, source: PagerView) -> None:
        """Focus the armed (else MRU) other pane; a no-op when single.

        Doubled ``ctrl+w`` lands on the pane the arm captured; any other
        caller lands on the most recently focused other pane.
        """
        if len(self._grid.panes) < 2:
            return
        target = self._take_armed_target()
        if target is None:
            grid = self._grid
            source_id = self._pane_id_of(source)
            if source_id in grid.panes:
                grid = grid_focus_pane(grid, source_id)
            pane_id = grid_other_target(grid)
            target = self._views_by_id.get(pane_id) if pane_id is not None else None
        if target is None:
            return
        self.focus_view(target)

    def show_in_other_view(
        self: Any,
        source: PagerView,
        document: PagerDocument,
        line: int | None,
        end_line: int | None = None,
    ) -> None:
        """Open *document* in the captured ``ctrl+w`` target pane.

        With two or more panes the captured target pushes a trail entry
        and navigates; when the captured pane vanished before an async
        result landed the action cancels with a short message and never
        redirects to a substitute. With one pane this opens a split
        clone of the source — stacked when it fits, else side by side —
        and the new pane then pushes its current view onto its trail and
        navigates, so backspace in it returns to the source document. When
        neither orientation fits, the source follows in place with an
        information toast. Focus never moves.
        """
        try:
            armed_slot = getattr(self, "_armed_other_target", None)
        except Exception:
            armed_slot = None
        try:
            source_armed = getattr(source, "_pending_action", "follow") == "other"
        except Exception:
            source_armed = False
        if armed_slot is not None or source_armed:
            target = self._take_armed_target()
            try:
                if getattr(source, "_pending_action", "follow") == "other":
                    source._pending_action = "follow"  # type: ignore[attr-defined]
                    try:
                        source._label_pending_prefix = ""  # type: ignore[attr-defined]
                    except Exception:
                        pass
            except Exception:
                pass
            if target is None:
                try:
                    source.notify(
                        "The other pane closed before the link landed.",
                        severity="information",
                    )
                except Exception:
                    pass
                try:
                    self.focused_view._update_footer()
                except Exception:
                    pass
                return
            try:
                target._bump_history_generation()
                target._push_trail_entry()
                target._navigate_to_document(document, line=line, end_line=end_line)
            except Exception:
                pass
            return
        try:
            split = len(self._grid.panes) > 1
        except AttributeError:
            try:
                split = self._split_state.layout is not PagerSplitLayout.SINGLE
            except Exception:
                split = len(getattr(self, "_views", ())) > 1
        if split:
            target = self._take_armed_target()
            if target is None:
                try:
                    source.notify(
                        "The other pane closed before the link landed.",
                        severity="information",
                    )
                except Exception:
                    pass
                try:
                    self.focused_view._update_footer()
                except Exception:
                    pass
                return
            try:
                target._bump_history_generation()
                target._push_trail_entry()
                target._navigate_to_document(document, line=line, end_line=end_line)
            except Exception:
                pass
            return
        if self._split_in_flight:
            return
        width, height = self._panes_size()
        if split_fits(PagerSplitLayout.BELOW, 50, width, height):
            layout = PagerSplitLayout.BELOW
        elif split_fits(PagerSplitLayout.BESIDE, 50, width, height):
            layout = PagerSplitLayout.BESIDE
        else:
            try:
                source._bump_history_generation()
                source._push_trail_entry()
                source._navigate_to_document(document, line=line, end_line=end_line)
            except Exception:
                pass
            self.notify("No room for a split — opened here.", severity="information")
            return
        try:
            source_id = self._pane_id_of(source)
        except Exception:
            source_id = None
        if source_id is None:
            try:
                source = self.focused_view
                source_id = self._pane_id_of(source)
            except Exception:
                return
        if source_id is None:
            return
        self._split_in_flight = True

        async def _open() -> None:
            try:
                grid = self._grid
                if source_id not in grid.panes or len(grid.panes) > 1:
                    return
                seed: PagerViewSeed = source.split_seed()
                try:
                    panes = self.query_one("#pager-panes", Vertical)
                except Exception:
                    return
                new_id = free_pane_id(grid)
                if new_id is None:
                    return
                new_view = self._new_split_view(source, seed)
                await panes.mount(new_view)
                if source_id not in self._grid.panes or len(self._grid.panes) > 1:
                    try:
                        await new_view.remove()
                    except Exception:
                        pass
                    return
                self._views_by_id[new_id] = new_view
                axis = split_axis(layout)
                self._grid = PaneGrid(
                    panes=(source_id, new_id),
                    focused=source_id,
                    axis=axis,
                    ratio=50,
                    recent=(source_id, new_id),
                )
                self._sync_split_compat()
                self._apply_split_state()
                try:
                    new_view._push_trail_entry()
                    new_view._navigate_to_document(
                        document, line=line, end_line=end_line
                    )
                except Exception:
                    pass
            finally:
                self._split_in_flight = False

        self.run_worker(_open(), exclusive=True)

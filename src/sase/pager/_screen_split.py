"""Split-pane state and layout for ``PagerScreen``.

Owns open/nest/erase/turn, focus movement, ratio stepping, and
opening a document in the other pane, all computed on the shared
:class:`PaneGrid` model and rendered through one flat ``#pager-panes``
CSS grid. Panes are keyed by stable pane ID: widgets move cells on swap
and the survivor is never remounted on close. Host chrome, forwarding,
and key routing live in :mod:`sase.pager._screen_host`; this module
never imports that sibling.
"""

from __future__ import annotations

import weakref
from typing import Any

from textual.containers import Vertical
from textual.widgets import Static

from sase.ace.tui.util.pane_grid import (
    Axis,
    GridSpec,
    PaneGrid,
    close_focused as grid_close_focused,
    cycle_focus as grid_cycle_focus,
    focus_pane as grid_focus_pane,
    free_pane_id,
    grid_spec,
    press_split as grid_press_split,
    step_ratio as grid_step_ratio,
    swap_focused as grid_swap_focused,
    turn as grid_turn,
)
from sase.pager._screen_split_arm import PagerScreenSplitArmMixin
from sase.pager.app import PagerExit
from sase.pager.split import (
    PagerSplitLayout,
    layout_for_axis,
    pager_grid_fits,
    split_axis,
    split_fits,
    state_for_grid,
)
from sase.pager.view import PagerView, PagerViewSeed

__all__ = ["PagerScreenSplitMixin"]


class PagerScreenSplitMixin(PagerScreenSplitArmMixin):
    """Own split layout, focus, and other-pane navigation."""

    def _pane_id_of(self: Any, view: PagerView) -> int | None:
        """Return the stable pane ID hosting *view*, if any."""
        try:
            by_id = self._views_by_id
        except AttributeError:
            by_id = {}
        for pane_id, hosted in by_id.items():
            if hosted is view:
                return pane_id
        try:
            return self._grid.panes[self._views.index(view)]
        except (AttributeError, ValueError, IndexError):
            return None

    def _sync_split_compat(self: Any) -> None:
        """Mirror the grid into the legacy ``_views``/``_split_state`` shape.

        ``_grid`` plus ``_views_by_id`` is the source of truth; the list,
        focused index, and two-pane state stay synced so existing readers
        keep working.
        """
        try:
            grid = self._grid
            by_id = self._views_by_id
        except AttributeError:
            return
        ordered = [by_id[pane_id] for pane_id in grid.panes if pane_id in by_id]
        if ordered:
            self._views = ordered
        try:
            self._focused_index = grid.panes.index(grid.focused)
        except ValueError:
            self._focused_index = 0
        self._split_state = state_for_grid(grid)

    def focus_view(self: Any, view: PagerView) -> None:
        """Move logical focus to *view* (a no-op when already focused)."""
        pane_id = self._pane_id_of(view)
        if pane_id is None:
            return
        try:
            grid = self._grid
        except AttributeError:
            return
        if len(grid.panes) < 2:
            return
        if pane_id == grid.focused:
            return
        self._disarm_if_armed()
        self._grid = grid_focus_pane(grid, pane_id)
        self._sync_split_compat()
        self._apply_split_state()

    def close_view(
        self: Any, view: PagerView, *, trail_exhausted: bool = False
    ) -> None:
        """Close *view*; with one view this dismisses the pager."""
        try:
            is_split = len(self._grid.panes) > 1
        except AttributeError:
            try:
                is_split = self._split_state.layout is not PagerSplitLayout.SINGLE
            except Exception:
                is_split = len(getattr(self, "_views", ())) > 1
        if not is_split:
            self.dismiss(PagerExit(trail_exhausted=trail_exhausted))
            return
        pane_id = self._pane_id_of(view)
        if pane_id is None:
            return
        if self._split_in_flight:
            return
        self._disarm_if_armed()
        self._split_in_flight = True

        async def _remove() -> None:
            try:
                grid = self._grid
                if pane_id not in grid.panes or len(grid.panes) < 2:
                    return
                if any(p not in self._views_by_id for p in grid.panes):
                    return
                # Focus the closing pane first so close picks the MRU
                # survivor; only the discarded widget leaves the tree.
                self._grid = grid_close_focused(grid_focus_pane(grid, pane_id))
                survivor = self._views_by_id.get(self._grid.focused)
                discarded = self._views_by_id.pop(pane_id, None)
                if survivor is None or discarded is None:
                    return
                try:
                    await discarded.remove()
                except Exception:
                    pass
                self._sync_split_compat()
                if len(self._grid.panes) <= 1:
                    # The survivor fills the screen: clear its frame.
                    try:
                        survivor.set_pane_role(framed=False, focused=True)
                    except Exception:
                        pass
                self._apply_split_state()
            finally:
                self._split_in_flight = False

        self.run_worker(_remove(), exclusive=True)

    @property
    def is_split(self: Any) -> bool:
        """Return whether two panes are currently shown."""
        try:
            return len(self._grid.panes) > 1
        except AttributeError:
            pass
        try:
            return self._split_state.layout is not PagerSplitLayout.SINGLE
        except Exception:
            return len(getattr(self, "_views", ())) > 1

    def _panes_size(self: Any) -> tuple[int, int]:
        """Return the ``#pager-panes`` width and height for fit checks."""
        try:
            panes = self.query_one("#pager-panes", Vertical)
            return (max(int(panes.size.width), 0), max(int(panes.size.height), 0))
        except Exception:
            pass
        try:
            return (max(int(self.size.width), 0), max(int(self.size.height), 0))
        except Exception:
            return (0, 0)

    def _refuse_split_toast(
        self: Any, target: PagerSplitLayout, width: int, height: int
    ) -> None:
        """Toast why *target* cannot open, suggesting what would fit."""
        other = (
            PagerSplitLayout.BESIDE
            if target is PagerSplitLayout.BELOW
            else PagerSplitLayout.BELOW
        )
        if split_fits(other, 50, width, height):
            hint = (
                "try | for side by side"
                if target is PagerSplitLayout.BELOW
                else "try \\ for below"
            )
            where = "below" if target is PagerSplitLayout.BELOW else "side by side"
            self.notify(
                f"Not enough room to split {where} — {hint}.",
                severity="information",
            )
            return
        self.notify("Window too small to split.", severity="information")

    def _new_split_view(self: Any, source: PagerView, seed: PagerViewSeed) -> PagerView:
        """Build a clone view of *source* primed with *seed*."""
        new_view = PagerView(
            seed.document,
            links_enabled=source.links_enabled,
            attached_handlers=source._attached_handlers,
            resolve_ref=source._resolve_ref,
            syntax_enabled=source.syntax_enabled,
            refresh_document_fn=source._refresh_document_fn,
        )
        new_view.apply_split_seed(seed)
        return new_view

    def _refuse_third_pane_toast(
        self: Any, grid: PaneGrid, axis: Axis, width: int, height: int
    ) -> None:
        """Toast why a third pane cannot open, naming what would fit."""
        other = Axis.COLS if axis is Axis.ROWS else Axis.ROWS
        new_id = free_pane_id(grid)
        if new_id is not None:
            alternative = grid_press_split(grid, other, new_id)
            if len(alternative.panes) == 3 and pager_grid_fits(
                alternative, width, height
            ):
                hint = (
                    "try | for side by side"
                    if axis is Axis.ROWS
                    else "try \\ for stacked"
                )
                # Toasts run on the focused view so screen-level notify
                # patches in tests keep capturing them after focus moves.
                self.focused_view.notify(
                    f"Not enough room for a third pane — {hint}.",
                    severity="information",
                )
                return
        self.focused_view.notify(
            "Not enough room for a third pane.", severity="information"
        )

    async def _toggle_split(self: Any, target: PagerSplitLayout) -> None:
        """Open, nest, erase, or turn for *target* behind the in-flight guard.

        From a single pane, open *target* with the new pane focused. From
        two panes, the same key keeps the focused pane (vim's ``ctrl-w o``)
        while the other key nests a third pane. From three panes, the
        outer-axis key erases the full-span divider and the other key turns
        the layout. Mounts are transactions: validate fit, mount, revalidate
        after the await, then publish state.
        """
        if self._split_in_flight:
            return
        axis = split_axis(target)
        if axis is None:
            return
        self._disarm_if_armed()
        grid = self._grid
        if len(grid.panes) <= 1:
            width, height = self._panes_size()
            if not split_fits(target, 50, width, height):
                self._refuse_split_toast(target, width, height)
                return
            self._split_in_flight = True
            try:
                source = self.focused_view
                seed: PagerViewSeed = source.split_seed()
                try:
                    panes = self.query_one("#pager-panes", Vertical)
                except Exception:
                    self._split_in_flight = False
                    return
                source_id = self._pane_id_of(source)
                if source_id is None:
                    source_id = grid.panes[0] if grid.panes else 0
                new_id = free_pane_id(grid)
                if new_id is None:
                    self._split_in_flight = False
                    return
                new_view = self._new_split_view(source, seed)
                await panes.mount(new_view)
                self._views_by_id[new_id] = new_view
                self._grid = grid_press_split(grid, axis, new_id)
                self._sync_split_compat()
                self._apply_split_state()
            finally:
                self._split_in_flight = False
            return
        if len(grid.panes) == 2 and axis is not grid.axis:
            new_id = free_pane_id(grid)
            if new_id is None:
                return
            candidate = grid_press_split(grid, axis, new_id)
            if len(candidate.panes) != 3:
                return
            width, height = self._panes_size()
            if not pager_grid_fits(candidate, width, height):
                self._refuse_third_pane_toast(grid, axis, width, height)
                return
            self._split_in_flight = True
            try:
                source = self.focused_view
                seed = source.split_seed()
                try:
                    panes = self.query_one("#pager-panes", Vertical)
                except Exception:
                    self._split_in_flight = False
                    return
                source_id = self._pane_id_of(source)
                if source_id is None or source_id not in grid.panes:
                    self._split_in_flight = False
                    return
                new_view = self._new_split_view(source, seed)
                await panes.mount(new_view)
                if self._grid is not grid:
                    try:
                        await new_view.remove()
                    except Exception:
                        pass
                    self._split_in_flight = False
                    return
                self._views_by_id[new_id] = new_view
                self._grid = candidate
                self._sync_split_compat()
                self._apply_split_state()
            finally:
                self._split_in_flight = False
            return
        candidate = grid_press_split(grid, axis, grid.focused)
        if candidate == grid:
            return
        if len(candidate.panes) == len(grid.panes):
            # Turn: a three-pane transpose.
            width, height = self._panes_size()
            if len(candidate.panes) == 3:
                if not pager_grid_fits(candidate, width, height):
                    self.focused_view.notify(
                        "Not enough room to turn the panes.",
                        severity="information",
                    )
                    return
            elif not split_fits(target, grid.ratio, width, height) and not split_fits(
                target, 50, width, height
            ):
                self._refuse_split_toast(target, width, height)
                return
            self._grid = candidate
            self._sync_split_compat()
            self._apply_split_state()
            return
        # Erase to fewer panes: remove only the views outside the
        # candidate so every survivor keeps its workers, reading anchor,
        # labels, and chrome.
        if self._split_in_flight:
            return
        self._split_in_flight = True
        try:
            self._grid = candidate
            for pane_id in [p for p in grid.panes if p not in candidate.panes]:
                discarded = self._views_by_id.pop(pane_id, None)
                if discarded is None:
                    continue
                try:
                    await discarded.remove()
                except Exception:
                    pass
            self._sync_split_compat()
            if len(candidate.panes) <= 1:
                survivor = self.focused_view
                try:
                    survivor.set_pane_role(framed=False, focused=True)
                except Exception:
                    pass
            self._apply_split_state()
        finally:
            self._split_in_flight = False

    def _reorder_pane_widgets(self: Any, panes: Any, ordered: list[Any]) -> None:
        """Put mounted pane widgets into *ordered* without remounting."""
        try:
            current = [c for c in list(panes.children) if c in ordered]
        except Exception:
            return
        if current == ordered:
            return
        move_child = getattr(panes, "move_child", None)
        if not callable(move_child):
            return
        for idx, widget in enumerate(ordered):
            try:
                showing = [c for c in list(panes.children) if c in ordered]
            except Exception:
                return
            if idx < len(showing) and showing[idx] is widget:
                continue
            try:
                if idx == 0:
                    if showing and showing[0] is not widget:
                        move_child(widget, before=showing[0])
                else:
                    move_child(widget, after=ordered[idx - 1])
            except Exception:
                return

    def _apply_split_state(self: Any) -> None:
        """Push the grid into the flat container, panes, and footer."""
        try:
            grid = self._grid
        except AttributeError:
            return
        try:
            panes = self.query_one("#pager-panes", Vertical)
        except Exception:
            return
        single = len(grid.panes) <= 1
        try:
            panes.remove_class("-single", "-below", "-beside")
            if single:
                panes.add_class("-single")
            elif layout_for_axis(grid.axis) is PagerSplitLayout.BELOW:
                panes.add_class("-below")
            else:
                panes.add_class("-beside")
        except Exception:
            pass
        try:
            spec: GridSpec = grid_spec(grid)
            panes.styles.grid_size_columns = len(spec.columns)
            panes.styles.grid_size_rows = len(spec.rows)
            panes.styles.grid_columns = " ".join(f"{w}fr" for w in spec.columns)
            panes.styles.grid_rows = " ".join(f"{h}fr" for h in spec.rows)
        except Exception:
            pass
        try:
            by_id = self._views_by_id
            ordered = [by_id[p] for p in spec.dom_order if p in by_id]
            self._reorder_pane_widgets(panes, ordered)
            if not single:
                for pane_id in spec.dom_order:
                    view = by_id.get(pane_id)
                    if view is None:
                        continue
                    try:
                        cell = spec.cells[pane_id]
                        view.styles.column_span = cell[2]
                        view.styles.row_span = cell[3]
                        view.styles.width = "1fr"
                        view.styles.height = "1fr"
                    except Exception:
                        pass
                    try:
                        view.set_pane_role(
                            framed=True, focused=(pane_id == grid.focused)
                        )
                    except Exception:
                        pass
            elif ordered:
                only = by_id.get(grid.focused, ordered[0])
                try:
                    only.styles.height = "1fr"
                    only.styles.width = "1fr"
                except Exception:
                    pass
                try:
                    only.set_pane_role(framed=False, focused=True)
                except Exception:
                    pass
        except Exception:
            pass
        try:
            rule = self.query_one("#pager-footer-rule", Static)
            if single:
                rule.remove_class("hidden")
            else:
                rule.add_class("hidden")
        except Exception:
            pass
        try:
            focused = self.focused_view
        except Exception:
            return
        try:
            focused._update_footer()
        except Exception:
            pass
        try:
            from sase.pager._screen_widgets import PagerBodyScroll

            scroll = focused.query_one("#pager-body-scroll", PagerBodyScroll)
            scroll_ref = weakref.ref(scroll)

            # Hold the scroll widget weakly: a strong bound method would
            # pin the scroll, its view, and its screen when the callback
            # outlives them, and focusing a pruned widget would leave the
            # app pointed at a dead node.
            def _focus_body_if_mounted() -> None:
                target = scroll_ref()
                if target is None:
                    return
                try:
                    if target.is_mounted:
                        target.focus()
                except Exception:
                    pass

            self.call_after_refresh(_focus_body_if_mounted)  # type: ignore[attr-defined]
        except Exception:
            pass

    async def action_split_below(self: Any) -> None:
        await self._toggle_split(PagerSplitLayout.BELOW)

    async def action_split_beside(self: Any) -> None:
        await self._toggle_split(PagerSplitLayout.BESIDE)

    def action_focus_other(self: Any) -> None:
        if len(self._grid.panes) < 2:
            return
        self._disarm_if_armed()
        self._grid = grid_cycle_focus(self._grid, 1)
        self._sync_split_compat()
        self._apply_split_state()

    def action_focus_other_reverse(self: Any) -> None:
        """Focus the previous pane in reading order, wrapping."""
        if len(self._grid.panes) < 2:
            return
        self._disarm_if_armed()
        self._grid = grid_cycle_focus(self._grid, -1)
        self._sync_split_compat()
        self._apply_split_state()

    def action_swap_pane_next(self: Any) -> None:
        """Swap the focused pane with the next pane; focus follows content."""
        if len(self._grid.panes) < 2:
            return
        self._disarm_if_armed()
        self._grid = grid_swap_focused(self._grid, 1)
        self._sync_split_compat()
        self._apply_split_state()

    def action_swap_pane_prev(self: Any) -> None:
        """Swap the focused pane with the previous pane; focus follows."""
        if len(self._grid.panes) < 2:
            return
        self._disarm_if_armed()
        self._grid = grid_swap_focused(self._grid, -1)
        self._sync_split_compat()
        self._apply_split_state()

    def action_close_focused_pane(self: Any) -> None:
        """Close the focused pane (a no-op when single)."""
        try:
            if len(self._grid.panes) < 2:
                return
        except AttributeError:
            return
        self.close_view(self.focused_view)

    def action_turn_split(self: Any) -> None:
        """Transpose the split (stacked ↔ side by side); widgets stay put."""
        if len(self._grid.panes) < 2:
            return
        self._disarm_if_armed()
        candidate = grid_turn(self._grid)
        if len(candidate.panes) == 3:
            width, height = self._panes_size()
            if not pager_grid_fits(candidate, width, height):
                self.focused_view.notify(
                    "Not enough room to turn the panes.", severity="information"
                )
                return
        self._grid = candidate
        self._sync_split_compat()
        self._apply_split_state()

    def action_grow_pane(self: Any) -> None:
        self._step_pane_ratio(+1)

    def action_shrink_pane(self: Any) -> None:
        self._step_pane_ratio(-1)

    def _step_pane_ratio(self: Any, direction: int) -> None:
        """Grow/shrink the focused pane one step, clamping silently."""
        try:
            grid = self._grid
        except AttributeError:
            return
        if len(grid.panes) < 2:
            return
        self._disarm_if_armed()
        candidate = grid_step_ratio(grid, grow=direction > 0)
        if candidate == grid:
            return
        width, height = self._panes_size()
        if not pager_grid_fits(candidate, width, height):
            return
        self._grid = candidate
        self._sync_split_compat()
        self._apply_split_state()

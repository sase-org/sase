"""Split-pane state and layout for ``PagerScreen``.

Owns two-pane open/rotate/unsplit, focus movement, ratio stepping, and
opening a document in the other pane. Host chrome, forwarding, and key
routing live in :mod:`sase.pager._screen_host`; this module never imports
that sibling.
"""

from __future__ import annotations

from typing import Any

from textual.containers import Vertical
from textual.widgets import Static

from sase.pager.app import PagerExit
from sase.pager.document import PagerDocument
from sase.pager.split import (
    PagerSplitLayout,
    PagerSplitState,
    close_focused_pane,
    split_fits,
    step_ratio,
    toggle_focus,
    toggle_split,
)
from sase.pager.view import PagerView, PagerViewSeed

__all__ = ["PagerScreenSplitMixin"]


class PagerScreenSplitMixin:
    """Own split layout, focus, and other-pane navigation."""

    def focus_view(self: Any, view: PagerView) -> None:
        """Move logical focus to *view* (a no-op when already focused)."""
        try:
            index = self._views.index(view)
        except ValueError:
            return
        if index == self._focused_index:
            return
        if self._split_state.layout is PagerSplitLayout.SINGLE:
            return
        self._focused_index = index
        self._split_state = PagerSplitState(
            layout=self._split_state.layout,
            focused=index,
            ratio=self._split_state.ratio,
        )
        self._apply_split_state()

    def close_view(
        self: Any, view: PagerView, *, trail_exhausted: bool = False
    ) -> None:
        """Close *view*; with one view this dismisses the pager."""
        try:
            is_split = self._split_state.layout is not PagerSplitLayout.SINGLE
        except Exception:
            is_split = len(getattr(self, "_views", ())) > 1
        if not is_split:
            self.dismiss(PagerExit(trail_exhausted=trail_exhausted))
            return
        try:
            index = self._views.index(view)
        except ValueError:
            return
        if self._split_in_flight:
            return
        self._split_in_flight = True

        async def _remove() -> None:
            try:
                other_index = 1 - index if len(self._views) == 2 else 0
                survivor = self._views[other_index]
                await self.query_one("#pager-panes", Vertical).remove_children()
                self._views = [survivor]
                self._focused_index = 0
                self._split_state = close_focused_pane(self._split_state)
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

    async def _toggle_split(self: Any, target: PagerSplitLayout) -> None:
        """Open, rotate, or unsplit for *target* behind the in-flight guard."""
        if self._split_in_flight:
            return
        current = self._split_state
        if current.layout is PagerSplitLayout.SINGLE:
            width, height = self._panes_size()
            if not split_fits(target, 50, width, height):
                self._refuse_split_toast(target, width, height)
                return
            self._split_in_flight = True
            try:
                source = self.focused_view
                seed: PagerViewSeed = source.split_seed()
                try:
                    first = self.query_one("#pager-panes", Vertical)
                except Exception:
                    self._split_in_flight = False
                    return
                new_view = PagerView(
                    seed.document,
                    links_enabled=source.links_enabled,
                    attached_handlers=source._attached_handlers,
                    resolve_ref=source._resolve_ref,
                    syntax_enabled=source.syntax_enabled,
                    refresh_document_fn=source._refresh_document_fn,
                )
                new_view.apply_split_seed(seed)
                await first.mount(new_view)
                self._views = [source, new_view]
                self._focused_index = 1
                self._split_state = toggle_split(current, target)
                self._apply_split_state()
            finally:
                self._split_in_flight = False
            return
        if current.layout is target:
            # Same key keeps the focused pane (vim's ctrl-w o).
            if self._split_in_flight:
                return
            self._split_in_flight = True
            try:
                survivor = self.focused_view
                await self.query_one("#pager-panes", Vertical).remove_children()
                self._views = [survivor]
                self._focused_index = 0
                self._split_state = toggle_split(current, target)
                try:
                    survivor.set_pane_role(framed=False, focused=True)
                except Exception:
                    pass
                self._apply_split_state()
            finally:
                self._split_in_flight = False
            return
        width, height = self._panes_size()
        if not split_fits(target, current.ratio, width, height) and not split_fits(
            target, 50, width, height
        ):
            self._refuse_split_toast(target, width, height)
            return
        self._split_state = toggle_split(current, target)
        self._apply_split_state()

    def _apply_split_state(self: Any) -> None:
        """Push the pure split state into container, panes, and footer."""
        try:
            state = self._split_state
        except Exception:
            return
        try:
            panes = self.query_one("#pager-panes", Vertical)
        except Exception:
            return
        single = state.layout is PagerSplitLayout.SINGLE
        try:
            panes.remove_class("-single", "-below", "-beside")
            if single:
                panes.add_class("-single")
            elif state.layout is PagerSplitLayout.BELOW:
                panes.add_class("-below")
            else:
                panes.add_class("-beside")
        except Exception:
            pass
        try:
            views = list(self._views)
            if len(views) == 2 and not single:
                first, second = views
                ratio = int(state.ratio)
                if state.layout is PagerSplitLayout.BELOW:
                    first.styles.height = f"{ratio}fr"
                    second.styles.height = f"{100 - ratio}fr"
                    first.styles.width = "1fr"
                    second.styles.width = "1fr"
                else:
                    first.styles.width = f"{ratio}fr"
                    second.styles.width = f"{100 - ratio}fr"
                    first.styles.height = "1fr"
                    second.styles.height = "1fr"
                first.set_pane_role(framed=True, focused=(state.focused == 0))
                second.set_pane_role(framed=True, focused=(state.focused == 1))
            elif views:
                only = views[0] if len(views) == 1 else views[state.focused]
                try:
                    only.styles.height = "1fr"
                    only.styles.width = "1fr"
                except Exception:
                    pass
                try:
                    only.set_pane_role(framed=False, focused=True)
                except Exception:
                    pass
                self._focused_index = 0
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
            scroll = focused.query_one("#pager-body-scroll", Static)
            self.call_after_refresh(scroll.focus)  # type: ignore[attr-defined]
        except Exception:
            pass

    async def action_split_below(self: Any) -> None:
        await self._toggle_split(PagerSplitLayout.BELOW)

    async def action_split_beside(self: Any) -> None:
        await self._toggle_split(PagerSplitLayout.BESIDE)

    def action_focus_other(self: Any) -> None:
        if self._split_state.layout is PagerSplitLayout.SINGLE:
            return
        self._focused_index = 1 - self._focused_index
        self._split_state = toggle_focus(self._split_state)
        self._apply_split_state()

    def focus_other_view(self: Any, source: PagerView) -> None:
        """Focus the pane that is not *source* (a no-op when single)."""
        if self._split_state.layout is PagerSplitLayout.SINGLE:
            return
        for view in list(self._views):
            if view is not source:
                self.focus_view(view)
                return

    def show_in_other_view(
        self: Any,
        source: PagerView,
        document: PagerDocument,
        line: int | None,
        end_line: int | None = None,
    ) -> None:
        """Open *document* in the pane that is not *source*.

        With two panes the other pane pushes a trail entry and navigates.
        With one pane this opens a split clone of the source — stacked when
        it fits, else side by side — and the new pane then pushes its
        current view onto its trail and navigates, so backspace in it
        returns to the source document. When neither orientation fits, the
        source follows in place with an information toast. Focus never
        moves.
        """
        try:
            split = self._split_state.layout is not PagerSplitLayout.SINGLE
        except Exception:
            split = len(getattr(self, "_views", ())) > 1
        if split:
            for view in list(self._views):
                if view is not source:
                    try:
                        view._bump_history_generation()
                        view._push_trail_entry()
                        view._navigate_to_document(
                            document, line=line, end_line=end_line
                        )
                    except Exception:
                        pass
                    return
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
        if source not in self._views:
            try:
                source = self.focused_view
            except Exception:
                return
        self._split_in_flight = True

        async def _open() -> None:
            try:
                if source not in self._views:
                    return
                seed: PagerViewSeed = source.split_seed()
                try:
                    first = self.query_one("#pager-panes", Vertical)
                except Exception:
                    return
                new_view = PagerView(
                    seed.document,
                    links_enabled=source.links_enabled,
                    attached_handlers=source._attached_handlers,
                    resolve_ref=source._resolve_ref,
                    syntax_enabled=source.syntax_enabled,
                    refresh_document_fn=source._refresh_document_fn,
                )
                new_view.apply_split_seed(seed)
                await first.mount(new_view)
                if source not in self._views:
                    try:
                        await new_view.remove()
                    except Exception:
                        pass
                    return
                self._views = [source, new_view]
                self._focused_index = 0
                self._split_state = PagerSplitState(layout=layout, focused=0, ratio=50)
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

    def action_grow_pane(self: Any) -> None:
        self._step_pane_ratio(+1)

    def action_shrink_pane(self: Any) -> None:
        self._step_pane_ratio(-1)

    def _step_pane_ratio(self: Any, direction: int) -> None:
        """Grow/shrink the focused pane one step, clamping silently."""
        if self._split_state.layout is PagerSplitLayout.SINGLE:
            return
        candidate = step_ratio(self._split_state, direction)
        if candidate == self._split_state:
            return
        width, height = self._panes_size()
        if not split_fits(candidate.layout, candidate.ratio, width, height):
            return
        self._split_state = candidate
        self._apply_split_state()

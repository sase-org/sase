"""Tab-agnostic debouncer for j/k detail-panel updates.

Phase 4 of sdd/plans/202604/instant_jk_navigation.md (bead sase-u.4). The cheap
navigation path (cursor highlight, position counter) runs inline on every
keypress; the expensive follow-up (detail rendering, syntax highlighting,
footer/ancestors panel updates) is funneled through a single shared
:class:`DetailPanelDebouncer` per tab so rapid bursts of j/k collapse to
exactly one final paint when the user quiesces.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from textual.app import App
    from textual.timer import Timer


DEFAULT_DEBOUNCE_S = 0.15


class DetailPanelDebouncer:
    """Coalesce expensive detail-panel updates across rapid input bursts.

    Each :meth:`schedule` call cancels and replaces the previously pending
    timer instead of stacking work — the most recent callback wins. A long
    press on j/k therefore produces exactly one detail-panel paint when
    the user releases the key.
    """

    def __init__(self, app: App, *, delay_s: float = DEFAULT_DEBOUNCE_S) -> None:
        self._app = app
        self._delay_s = delay_s
        self._timer: Timer | None = None
        self._callback: Callable[[], None] | None = None

    @property
    def is_pending(self) -> bool:
        """True when a debounced update is scheduled but has not yet fired."""
        return self._timer is not None

    def schedule(self, callback: Callable[[], None]) -> None:
        """Reset the timer to run *callback* after the debounce delay.

        If a timer is already pending it is cancelled and replaced. The
        most recent callback wins; intermediate ones are discarded.
        """
        if self._timer is not None:
            self._timer.stop()
        self._callback = callback
        self._timer = self._app.set_timer(self._delay_s, self._fire)

    def cancel(self) -> None:
        """Cancel any pending timer without firing.

        Used when a full refresh is about to run (which supersedes the
        pending detail update) or when the user leaves the tab.
        """
        if self._timer is not None:
            self._timer.stop()
            self._timer = None
        self._callback = None

    def _fire(self) -> None:
        cb = self._callback
        self._timer = None
        self._callback = None
        if cb is not None:
            cb()

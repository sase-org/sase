"""Card time state: ``(`` ``)`` ``{`` ``}`` stepping through versions.

Facade preserving the original :mod:`sase.ace.tui.modals.memory_pane_time`
public import path. The implementation lives in the sibling
``memory_pane_time_*`` modules: moment views in
:mod:`sase.ace.tui.modals.memory_pane_time_moments`, pin state in
:mod:`sase.ace.tui.modals.memory_pane_time_pins`, step intents in
:mod:`sase.ace.tui.modals.memory_pane_time_steps`, and body loads,
arrival freshness, and guards in
:mod:`sase.ace.tui.modals.memory_pane_time_bodies`. Shared moment
construction lives in the private
:mod:`sase.ace.tui.modals._memory_pane_time_shared` module under public
names so siblings never import ``_``-prefixed names across modules.

Pins are keyed per ``(scope_key, selector)`` so they never carry across
subjects (arrival rule D7). The displayed (applied) ordinal only ever
advances together with its body bytes: one immutable moment is applied
atomically, and a slow body shows an explicit ``loading vN…`` strip
instead of another version's text (§5.4 rules 1, 2, 6).
"""

from __future__ import annotations

from .memory_pane_time_bodies import (
    PIN_EDIT_REFUSAL as PIN_EDIT_REFUSAL,
)
from .memory_pane_time_bodies import (
    MemoryPaneTimeBodiesMixin,
)
from .memory_pane_time_moments import (
    card_moment_for_view as card_moment_for_view,
)
from .memory_pane_time_moments import (
    step_footer_verbs as step_footer_verbs,
)
from .memory_pane_time_pins import MemoryPaneTimePinsMixin
from .memory_pane_time_steps import MemoryPaneTimeStepsMixin


class MemoryPaneTimeMixin(
    MemoryPaneTimePinsMixin,
    MemoryPaneTimeStepsMixin,
    MemoryPaneTimeBodiesMixin,
):
    """Past pins, step actions, and guards for ``MemoryPane``."""


__all__ = [
    "MemoryPaneTimeMixin",
    "PIN_EDIT_REFUSAL",
    "card_moment_for_view",
    "step_footer_verbs",
]

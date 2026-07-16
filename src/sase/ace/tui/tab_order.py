"""Single source of truth for the visible ACE tab order and cycling.

Both the rendered top-bar tab labels and the keyboard tab-cycling actions
derive their ordering from :data:`TAB_ORDER` so the two can never drift
apart.
"""

from __future__ import annotations

from typing import Literal

TabName = Literal["changespecs", "agents", "axe"]

# The user-facing Artifacts tab deliberately retains the historical internal
# ``changespecs`` id.  Keeping that id stable avoids invalidating saved state,
# query routing, repro captures, and downstream integrations while giving new
# code a name that matches the UI.
ARTIFACTS_TAB: TabName = "changespecs"

# Left-to-right order of the top-bar tabs.  The Agents tab leads because
# it is the app's default startup tab.
TAB_ORDER: tuple[TabName, ...] = ("agents", "changespecs", "axe")


def adjacent_tab(current: TabName, direction: int) -> TabName:
    """Return the tab ``direction`` steps from ``current`` in TAB_ORDER.

    ``direction`` is ``+1`` for the next tab and ``-1`` for the previous
    tab; the walk wraps around the ends of :data:`TAB_ORDER`.
    """
    idx = TAB_ORDER.index(current)
    return TAB_ORDER[(idx + direction) % len(TAB_ORDER)]

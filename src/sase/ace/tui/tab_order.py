"""Single source of truth for the visible ACE tab order and cycling.

Both the rendered top-bar tab labels and the keyboard tab-cycling actions
derive their ordering from :data:`TAB_ORDER` so the two can never drift
apart.
"""

from __future__ import annotations

from typing import Literal, cast

TabName = Literal["artifacts", "agents", "axe"]
LegacyTabName = Literal[
    "changespecs",  # legacy compatibility tab id persisted by older sessions
    "patches",
]
TabInput = TabName | LegacyTabName | str

# ``changespecs`` is the legacy compatibility tab id persisted by older
# sessions; ``patches`` appeared in short-lived development captures during the
# Patch terminology migration.
LEGACY_ARTIFACTS_TABS: frozenset[str] = frozenset({"changespecs", "patches"})
ARTIFACTS_TAB: TabName = "artifacts"

# Left-to-right order of the top-bar tabs.  The Agents tab leads because
# it is the app's default startup tab.
TAB_ORDER: tuple[TabName, ...] = ("agents", "artifacts", "axe")


def normalize_tab_name(tab: TabInput | None, *, default: TabName = "agents") -> TabName:
    """Return the canonical ACE tab id for user or persisted input."""
    if tab is None:
        return default
    value = str(tab).strip()
    if value in LEGACY_ARTIFACTS_TABS:
        return ARTIFACTS_TAB
    if value in TAB_ORDER:
        return cast(TabName, value)
    return default


def adjacent_tab(current: TabName, direction: int) -> TabName:
    """Return the tab ``direction`` steps from ``current`` in TAB_ORDER.

    ``direction`` is ``+1`` for the next tab and ``-1`` for the previous
    tab; the walk wraps around the ends of :data:`TAB_ORDER`.
    """
    idx = TAB_ORDER.index(normalize_tab_name(current))
    return TAB_ORDER[(idx + direction) % len(TAB_ORDER)]

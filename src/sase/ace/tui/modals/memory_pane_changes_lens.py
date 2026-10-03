"""Changes lens: the rail becomes a day-grouped changeset review (``C``).

Facade preserving the original ``memory_pane_changes_lens`` import path.
``C`` re-skins the Notes rail into changesets across subjects: rows come
from the pure ``sase.memory.history.feed_model`` shared with the pager
feed document, so the lens and the pager group days, fold regen-only
changesets, and label subjects identically. The mixin is composed from
the ``memory_pane_changes_*`` siblings (feed, rail, card, header, mark,
and hand-off); the lens framework (snapshot/restore, Esc ladder) lives
in :mod:`sase.ace.tui.modals.memory_pane_lens`."""

from __future__ import annotations

from ._memory_pane_changes_shared import MORE_ROW_ID
from .memory_pane_changes_card import MemoryPaneChangesCardMixin
from .memory_pane_changes_feed import MemoryPaneChangesFeedMixin
from .memory_pane_changes_handoff import MemoryPaneChangesHandoffMixin
from .memory_pane_changes_header import MemoryPaneChangesHeaderMixin
from .memory_pane_changes_mark import MemoryPaneChangesMarkMixin
from .memory_pane_changes_rail import MemoryPaneChangesRailMixin


class MemoryPaneChangesLensMixin(
    MemoryPaneChangesFeedMixin,
    MemoryPaneChangesRailMixin,
    MemoryPaneChangesCardMixin,
    MemoryPaneChangesHeaderMixin,
    MemoryPaneChangesMarkMixin,
    MemoryPaneChangesHandoffMixin,
):
    """The ``C`` Changes lens: rail rows, card sections, and hand-off."""


__all__ = ["MORE_ROW_ID", "MemoryPaneChangesLensMixin"]

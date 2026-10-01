"""Modeless history navigation for ``PagerScreen``.

``(``/``)`` step through visible committed versions, ``{`` selects the
first version and ``}`` follows now or its deletion tombstone. Worker
scheduling runs after first paint; service calls stay off the pump via
``asyncio.to_thread`` with generation guards so stale loads cannot
overwrite a newer view.

This module is the public import path facade: the implementation lives
in the sibling ``_screen_history_*`` modules and is re-exported here as
:class:`PagerHistoryMixin`.
"""

from __future__ import annotations

from sase.pager._screen_history_discovery import PagerHistoryDiscoveryMixin
from sase.pager._screen_history_state import PagerHistoryStateMixin
from sase.pager._screen_history_steps import PagerHistoryStepsMixin
from sase.pager._screen_history_swap import PagerHistorySwapMixin

__all__ = ["PagerHistoryMixin"]


class PagerHistoryMixin(
    PagerHistoryStateMixin,
    PagerHistoryDiscoveryMixin,
    PagerHistoryStepsMixin,
    PagerHistorySwapMixin,
):
    """Own per-section history state and version-step navigation."""

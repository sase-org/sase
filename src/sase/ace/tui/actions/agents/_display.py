"""Agent display and refresh methods for sase's TUI app.

Top-level orchestration: holds the panel-index cache, the public refresh
entry points (``_refresh_agents_display`` and friends), and aggregates
:class:`._display_panels._PanelsMixin` and
:class:`._display_detail._DetailMixin` into the single
:class:`AgentDisplayMixin` consumed by :mod:`._core`.
"""

from __future__ import annotations

from ._display_cache import AgentDisplayCacheMixin
from ._display_detail import DetailMixin
from ._display_helpers import TabName
from ._display_incremental import AgentDisplayIncrementalMixin
from ._display_panels import PanelsMixin
from ._display_refresh import AgentDisplayRefreshMixin
from ._neighbors import AgentNeighborMixin

__all__ = ["AgentDisplayMixin"]


class AgentDisplayMixin(
    AgentDisplayCacheMixin,
    AgentDisplayIncrementalMixin,
    AgentDisplayRefreshMixin,
    AgentNeighborMixin,
    PanelsMixin,
    DetailMixin,
):
    """Mixin providing agent display and refresh methods."""

    current_tab: TabName

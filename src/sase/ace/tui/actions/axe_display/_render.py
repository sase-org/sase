"""Backward-compatible entry point for the AXE render mixins.

The render logic used to live here in a single 700+ line module. It is now
split by concern; this module only recombines the pieces so existing import
and patch targets keep resolving:

- :mod:`._render_dashboard` — dashboard refresh, info panel, chop-run stepping.
- :mod:`._render_panels` — side-panel painting, titles, highlights, layout.
- :mod:`._render_footer` — keybinding footer and axe state setters.
"""

from __future__ import annotations

from ._render_dashboard import (
    AxeDisplayDashboardMixin,
    chop_allows_auto_scroll as _chop_allows_auto_scroll,
)
from ._render_footer import AxeDisplayFooterMixin
from ._render_panels import AxeDisplayPanelsMixin


class AxeDisplayRenderMixin(AxeDisplayDashboardMixin):
    """Mixin providing the axe display rendering and state-setter methods."""


__all__ = [
    "AxeDisplayDashboardMixin",
    "AxeDisplayFooterMixin",
    "AxeDisplayPanelsMixin",
    "AxeDisplayRenderMixin",
    "_chop_allows_auto_scroll",
]

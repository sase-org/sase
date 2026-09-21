"""Backward-compatible entry point for the AXE refresh mixins.

The refresh logic used to live here in a single 700+ line module. It is now
split by concern; this module only recombines the pieces so existing import
and patch targets keep resolving:

- :mod:`._refresh_collect` — collector kwargs, sync load, cache application.
- :mod:`._refresh_full` — async full-fleet refresh and startup init.
- :mod:`._refresh_targeted` — selected-item fast path and live ticks.
"""

from __future__ import annotations

from sase.axe.state import (
    read_lumberjack_log_tail,
    read_lumberjack_metrics,
    read_lumberjack_status,
)

from ...bgcmd import get_slot_info, read_info_output_tail
from ._data import collect_axe_status_data
from ._refresh_collect import AxeRefreshCollectMixin
from ._refresh_full import AxeRefreshFullMixin
from ._refresh_targeted import AxeRefreshTargetedMixin


class AxeDisplayRefreshMixin(AxeRefreshTargetedMixin):
    """Mixin providing AXE data collection and cache refreshes."""


__all__ = [
    "AxeDisplayRefreshMixin",
    "AxeRefreshCollectMixin",
    "AxeRefreshFullMixin",
    "AxeRefreshTargetedMixin",
    "collect_axe_status_data",
    "get_slot_info",
    "read_info_output_tail",
    "read_lumberjack_log_tail",
    "read_lumberjack_metrics",
    "read_lumberjack_status",
]

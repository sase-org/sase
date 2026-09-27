"""Output-log section for the axe dashboard widget.

Public facade: implementation lives in sibling
``_axe_dashboard_output_*`` modules; this file combines the mixins and
re-exports the names that callers and tests historically import from
``_axe_dashboard_output``.
"""

from __future__ import annotations

from typing import Any

from textual.widgets import Static

from ._axe_dashboard_output_chop import AxeChopOutputMixin, render_origin_detail_line
from ._axe_dashboard_output_overview import AxeOverviewOutputMixin, LumberjackSummary
from ._axe_dashboard_output_service import AxeServiceOutputMixin

__all__ = [
    "AxeOutputSection",
    "LumberjackSummary",
    "render_origin_detail_line",
]


class AxeOutputSection(
    AxeChopOutputMixin,
    AxeServiceOutputMixin,
    AxeOverviewOutputMixin,
    Static,
):
    """Section showing live axe output log."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._cached_lumberjack_overview: Any = None
        self._cached_lumberjack_overview_layout: Any = None

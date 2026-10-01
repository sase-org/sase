"""Generic history seam for pager sections."""

from __future__ import annotations

from sase.pager.history.models import (
    HistoryView,
    SectionTimeState,
    VersionPin,
    committed_pin_for_ordinal,
    live_pin_for_subject,
)
from sase.pager.history.provider import (
    HistoryMissingError,
    SectionHistoryProvider,
    clear_history_provider_factories,
    history_factories_snapshot,
    history_provider_for_section,
    register_history_provider_factory,
)
from sase.pager.history.timeline import filter_rows, picker_window, visible_rows

__all__ = [
    "HistoryMissingError",
    "HistoryView",
    "SectionHistoryProvider",
    "SectionTimeState",
    "VersionPin",
    "clear_history_provider_factories",
    "committed_pin_for_ordinal",
    "filter_rows",
    "history_factories_snapshot",
    "history_provider_for_section",
    "live_pin_for_subject",
    "picker_window",
    "register_history_provider_factory",
    "visible_rows",
]

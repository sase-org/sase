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

__all__ = [
    "HistoryMissingError",
    "HistoryView",
    "SectionHistoryProvider",
    "SectionTimeState",
    "VersionPin",
    "clear_history_provider_factories",
    "committed_pin_for_ordinal",
    "history_factories_snapshot",
    "history_provider_for_section",
    "live_pin_for_subject",
    "register_history_provider_factory",
]

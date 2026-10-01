"""Generic section-history provider seam for the pager.

Every ``PagerScreen``, standalone or in ACE, discovers providers without
importing memory modules in pager core: a ``sase_pager_history`` package
entry point loads a memory-provider factory after paint off-thread. The
memory factory returns no registration when the beta is off, before
constructing ``HistoryService`` or inspecting files.
"""

from __future__ import annotations

import importlib.metadata
from typing import Any, Protocol

from sase.pager.document import PagerSection

_PROVIDER_FACTORIES: list[object] = []
_DISCOVERY_DONE = False
_ENTRY_POINT_GROUP = "sase_pager_history"


class HistoryMissingError(Exception):
    """A same-scope target absent at the pinned revision (explicit notice)."""


class SectionHistoryProvider(Protocol):
    """Worker-safe history operations for one section family."""

    provider_key: str

    def recognizes(self, section: PagerSection) -> bool:
        """Return whether this provider owns *section*."""
        ...

    def load_timeline(self, section: PagerSection) -> dict[str, Any]:
        """Load full timeline metadata (hidden rows included)."""
        ...

    def load_version(self, section: PagerSection, ordinal: int) -> PagerSection | None:
        """Load one version body as a derived section, or ``None``."""
        ...

    def compare_versions(
        self, section: PagerSection, base_ordinal: int, target_ordinal: int
    ) -> dict[str, Any] | None:
        """Compare two versions for gutter marks and anchors."""
        ...

    def resolve_historical_link(
        self, section: PagerSection, ref: str
    ) -> PagerSection | None:
        """Resolve a same-scope historical link, or ``None`` to decline."""
        ...

    def refresh(self, section: PagerSection) -> PagerSection | None:
        """Re-sync and re-read now for *section*."""
        ...


def register_history_provider_factory(factory: object) -> None:
    """Register an in-process provider factory (tests and entry points)."""
    _PROVIDER_FACTORIES.append(factory)


def clear_history_provider_factories() -> None:
    """Drop registered factories and force rediscovery (tests only)."""
    global _DISCOVERY_DONE
    _PROVIDER_FACTORIES.clear()
    _DISCOVERY_DONE = False


def _discover_entry_point_factories() -> None:
    """Load ``sase_pager_history`` entry-point factories once per process."""
    global _DISCOVERY_DONE
    if _DISCOVERY_DONE:
        return
    _DISCOVERY_DONE = True
    try:
        points = importlib.metadata.entry_points(group=_ENTRY_POINT_GROUP)
    except Exception:
        return
    for point in points:
        try:
            factory = point.load()
        except Exception:
            continue
        _PROVIDER_FACTORIES.append(factory)


def history_provider_for_section(
    section: PagerSection,
) -> SectionHistoryProvider | None:
    """Return the first provider recognizing *section*, if any.

    Discovery runs lazily so pager core never imports memory modules.
    Failures are isolated: a factory that raises simply declines.
    """
    _discover_entry_point_factories()
    for factory in list(_PROVIDER_FACTORIES):
        try:
            provider = factory() if callable(factory) else factory  # type: ignore[operator]
        except Exception:
            continue
        recognizes = getattr(provider, "recognizes", None)
        if recognizes is None:
            continue
        try:
            if recognizes(section):
                return provider  # type: ignore[return-value]
        except Exception:
            continue
    return None


def history_factories_snapshot() -> tuple[object, ...]:
    """Return the currently registered factories (tests only)."""
    _discover_entry_point_factories()
    return tuple(_PROVIDER_FACTORIES)


__all__ = [
    "HistoryMissingError",
    "SectionHistoryProvider",
    "clear_history_provider_factories",
    "history_factories_snapshot",
    "history_provider_for_section",
    "register_history_provider_factory",
]

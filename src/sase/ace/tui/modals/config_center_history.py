"""Two-slot alternate-section memory for the Admin Center opener key."""

from __future__ import annotations

from dataclasses import dataclass

from .config_center_catalog import CenterTab


@dataclass(frozen=True)
class AdminCenterTabHistory:
    """Immutable ``(current, alternate)`` pair backing the opener's jump.

    ``current`` is what the landing page resumes to. ``alternate`` is the
    opener's in-tab jump target. ``alternate`` can never equal ``current``.
    """

    current: CenterTab | None = None
    alternate: CenterTab | None = None

    def remember(self, tab: CenterTab) -> AdminCenterTabHistory:
        """Return the history after ``tab`` becomes the active section."""
        if tab == self.current:
            return self
        return AdminCenterTabHistory(current=tab, alternate=self.current)


def validated_admin_center_tab_history(
    current: CenterTab | None,
    alternate: CenterTab | None,
) -> AdminCenterTabHistory:
    """Build a history pair, dropping ``alternate`` if it duplicates ``current``."""
    if alternate is not None and alternate == current:
        alternate = None
    return AdminCenterTabHistory(current=current, alternate=alternate)


__all__ = [
    "AdminCenterTabHistory",
    "validated_admin_center_tab_history",
]

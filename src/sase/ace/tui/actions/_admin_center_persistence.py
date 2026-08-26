"""In-memory Admin Center navigation memory, scoped to one ACE session."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..modals.config_center_history import AdminCenterTabHistory

if TYPE_CHECKING:
    from ..modals.config_center_catalog import CenterTab


class AdminCenterPersistenceMixin:
    """Remember the latest Admin Center history for this ACE process."""

    _last_admin_center_tab: CenterTab | None
    _admin_center_history: AdminCenterTabHistory

    def _ensure_admin_center_persistence_state(self) -> None:
        """Initialize fields for direct-mixin tests that bypass app startup."""
        if not hasattr(self, "_admin_center_history"):
            self._admin_center_history = AdminCenterTabHistory(
                current=getattr(self, "_last_admin_center_tab", None)
            )
        if not hasattr(self, "_last_admin_center_tab"):
            self._last_admin_center_tab = self._admin_center_history.current

    def _remember_admin_center_tab(self, value: object) -> None:
        """Remember a valid tab for the remainder of this ACE session."""
        from ..modals.config_center_catalog import validated_center_tab

        self._ensure_admin_center_persistence_state()
        tab = validated_center_tab(value)
        if tab is None:
            return
        history = self._admin_center_history.remember(tab)
        self._admin_center_history = history
        self._last_admin_center_tab = history.current

    def _on_admin_center_tab_activated(self, tab: CenterTab) -> None:
        """Receive the modal's successful-navigation callback."""
        self._remember_admin_center_tab(tab)


__all__ = ["AdminCenterPersistenceMixin"]

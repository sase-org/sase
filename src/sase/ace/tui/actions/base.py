"""Base action methods for sase's TUI app."""

from __future__ import annotations

from ._admin_center_persistence import AdminCenterPersistenceMixin
from ._base_admin import BaseAdminActionsMixin
from ._base_commands import BaseCommandActionsMixin
from ._base_patch import BasePatchActionsMixin
from ._base_query import BaseQueryActionsMixin
from ._base_types import TabName
from ._base_updates import BaseUpdateActionsMixin
from ._base_workflow import BaseWorkflowActionsMixin
from .refresh_panel import RefreshPanelMixin


class BaseActionsMixin(
    AdminCenterPersistenceMixin,
    RefreshPanelMixin,
    BaseWorkflowActionsMixin,
    BaseAdminActionsMixin,
    BaseUpdateActionsMixin,
    BasePatchActionsMixin,
    BaseQueryActionsMixin,
    BaseCommandActionsMixin,
):
    """Mixin providing workflow, tool, and query actions."""


__all__ = [
    "BaseActionsMixin",
    "TabName",
]

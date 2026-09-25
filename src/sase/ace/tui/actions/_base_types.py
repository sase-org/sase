"""Shared types and host attributes for base TUI actions."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from ...patch import Patch
    from ..modals.config_center_modal import CenterTab

TabName = Literal["artifacts", "agents", "services"]


class BaseActionsHost:
    """Shared attributes accessed from AceApp at runtime."""

    patches: list[Patch]
    current_idx: int
    current_tab: TabName
    query_string: str
    parsed_query: Any
    _last_admin_center_tab: CenterTab | None

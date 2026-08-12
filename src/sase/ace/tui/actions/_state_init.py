"""State initialization for the ACE TUI app's startup mixin."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from ._state_init_agents import init_agent_state
from ._state_init_late import init_late_startup_state
from ._state_init_navigation import init_navigation_state
from ._state_init_runtime import init_runtime_state

if TYPE_CHECKING:
    from ..app import TabName

__all__ = ["StateInitMixin"]


class StateInitMixin:
    """Mixin housing the composed ``_init_app_state`` method."""

    _automatic_update_provider_names: tuple[str, ...] | None

    def _init_app_state(
        self,
        query: str,
        model_tier_override: Literal["large", "small"] | None,
        refresh_interval: int,
        auto_start_axe: bool,
        restart_axe: bool,
        initial_tab: TabName,
    ) -> None:
        """Initialize all instance state for ``AceApp``.

        Called from ``AceApp.__init__`` after ``super().__init__()``. The
        helpers are ordered to preserve the original startup sequence.
        """
        init_runtime_state(
            self,
            query=query,
            refresh_interval=refresh_interval,
            auto_start_axe=auto_start_axe,
            restart_axe=restart_axe,
            initial_tab=initial_tab,
        )
        init_navigation_state(self)
        init_agent_state(self)
        init_late_startup_state(self, model_tier_override)

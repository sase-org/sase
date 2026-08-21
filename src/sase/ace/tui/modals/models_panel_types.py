"""Shared contracts and session types for Launch Control."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable


@dataclass(frozen=True)
class ModelsPanelResult:
    """Outcome of a Models panel session.

    ``changed`` is ``True`` when at least one temporary override was set or
    cleared while the panel was open, so the caller knows to refresh top-bar
    indicators. ``provider_routing_changed`` narrows the case where the launch
    default must be re-resolved because provider availability changed.
    """

    changed: bool = False
    provider_routing_changed: bool = False


LaunchPaneDisplayMode = Literal["standalone", "embedded"]


@dataclass
class LaunchPaneSessionState:
    """Stable cursor bookmark for a reusable Launch pane.

    The pane records bucket identity plus row identity instead of a visual index
    so async reloads can restore the same logical target after rows move.
    """

    active_bucket: str | None = None
    selected_row_id: str | None = None

    def record_cursor(
        self, *, active_bucket: str | None, selected_row_id: str | None
    ) -> None:
        self.active_bucket = active_bucket
        self.selected_row_id = selected_row_id


@runtime_checkable
class LaunchPaneHost(Protocol):
    """Close contract implemented by standalone and embedded Launch hosts."""

    def request_launch_close(self, result: ModelsPanelResult) -> None:
        """Dismiss the enclosing surface with the pane's current result."""
        ...


__all__ = [
    "LaunchPaneDisplayMode",
    "LaunchPaneHost",
    "LaunchPaneSessionState",
    "ModelsPanelResult",
]

"""Shared types for the Models panel."""

from __future__ import annotations

from dataclasses import dataclass


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

"""Shared tab scope constants for TUI command catalog builders."""

from __future__ import annotations

from sase.ace.tui.commands.types import CommandTab

ALL_TABS: tuple[CommandTab, ...] = ("changespecs", "agents", "axe")
CL_ONLY: tuple[CommandTab, ...] = ("changespecs",)
AGENTS_ONLY: tuple[CommandTab, ...] = ("agents",)
AXE_ONLY: tuple[CommandTab, ...] = ("axe",)
AGENTS_AXE: tuple[CommandTab, ...] = ("agents", "axe")
CL_AGENTS: tuple[CommandTab, ...] = ("changespecs", "agents")
CL_AXE: tuple[CommandTab, ...] = ("changespecs", "axe")

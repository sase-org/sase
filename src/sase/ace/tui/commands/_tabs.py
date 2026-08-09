"""Shared tab scope constants for TUI command catalog builders."""

from __future__ import annotations

from sase.ace.tui.commands.types import CommandTab

ALL_TABS: tuple[CommandTab, ...] = ("artifacts", "agents", "axe")
CL_ONLY: tuple[CommandTab, ...] = ("artifacts",)
AGENTS_ONLY: tuple[CommandTab, ...] = ("agents",)
AXE_ONLY: tuple[CommandTab, ...] = ("axe",)
AGENTS_AXE: tuple[CommandTab, ...] = ("agents", "axe")
CL_AGENTS: tuple[CommandTab, ...] = ("artifacts", "agents")
CL_AXE: tuple[CommandTab, ...] = ("artifacts", "axe")

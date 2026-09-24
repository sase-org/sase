"""AXE side-panel item types for the background command list widget."""

from dataclasses import dataclass
from typing import Literal

# Item type: "axe" or slot number (1-9)
ItemType = Literal["axe"] | int


@dataclass(frozen=True)
class LumberjackItem:
    """A top-level lumberjack entry."""

    name: str


@dataclass(frozen=True)
class ChopItem:
    """A chop child entry under a lumberjack."""

    lumberjack_name: str
    chop_name: str


@dataclass(frozen=True)
class BgCmdItem:
    """A background command entry."""

    slot: int


@dataclass(frozen=True)
class ServiceProcItem:
    """A service-host managed proc entry."""

    name: str


AxeItem = ServiceProcItem | LumberjackItem | ChopItem | BgCmdItem

__all__ = [
    "AxeItem",
    "BgCmdItem",
    "ChopItem",
    "ItemType",
    "LumberjackItem",
    "ServiceProcItem",
]

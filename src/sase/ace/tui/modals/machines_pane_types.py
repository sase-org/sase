"""Shared types for the Admin Center Machines pane."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from sase.dispatch.models import MachineRecord, MachineStatus

from .base import FilterInput


@dataclass(frozen=True)
class MachineStatusSnapshot:
    """One status result plus local observation time."""

    status: MachineStatus
    checked_at: float


@dataclass(frozen=True)
class MachineRow:
    """Renderable local or enrolled-machine row."""

    alias: str
    kind: Literal["here", "remote"]
    record: MachineRecord | None = None

    @property
    def identity(self) -> str:
        return f"{self.kind}:{self.alias}"


@dataclass(frozen=True)
class MachineFlow:
    """Persistent action guidance rendered beside the selected row."""

    title: str
    body: tuple[str, ...]
    commands: tuple[str, ...]


class MachinesFilterInput(FilterInput):
    """Filter input that lets focused Machines bindings keep working."""


__all__ = [
    "MachineFlow",
    "MachineRow",
    "MachineStatusSnapshot",
    "MachinesFilterInput",
]

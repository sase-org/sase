"""Shared planning model for ``sase init`` onboarding."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

InitOperation = Literal["create", "update", "overwrite", "delete", "validate", "deploy"]


@dataclass(frozen=True)
class InitAction:
    """One planned initialization action."""

    path: Path
    operation: InitOperation
    detail: str = ""
    new_content: str | bytes | None = None


@dataclass(frozen=True)
class InitPlan:
    """Read-only plan for one ``sase init`` subcommand."""

    command: str
    label: str
    summary: str
    actions: tuple[InitAction, ...]
    warnings: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()

    @property
    def has_changes(self) -> bool:
        """Whether this subcommand would change anything if applied."""
        return bool(self.actions)

    @property
    def runnable(self) -> bool:
        """Whether this plan can be applied."""
        return not self.blockers


__all__ = ["InitAction", "InitOperation", "InitPlan"]

"""Shared operation interfaces for the temporary migration driver.

TEMPORARY MODULE: deletion owner sase-x7.14.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from sase.migration_kit.catalog import OperationSpec


class MigrationInjectedAbort(RuntimeError):
    """Raised by tests to simulate a killed process after a durable step."""


@dataclass(slots=True)
class OperationContext:
    """Mutable per-run context passed to operation implementations."""

    run_id: str
    sase_home: Path
    home: Path
    backup_id: str | None = None
    abort_after_archives: int | None = None
    _archive_count: int = 0

    def abort_point_after_archive(self) -> None:
        """Raise once the configured number of archives has been promoted."""
        if self.abort_after_archives is None:
            return
        self._archive_count += 1
        if self._archive_count >= self.abort_after_archives:
            raise MigrationInjectedAbort(
                f"injected abort after {self._archive_count} archive(s)"
            )


@dataclass(frozen=True, slots=True)
class OperationOutcome:
    """Result from applying or verifying one operation entry."""

    ok: bool
    message: str
    errors: tuple[str, ...] = ()
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "message": self.message,
            "errors": list(self.errors),
            "details": self.details,
        }


class MigrationOperation(Protocol):
    """Protocol implemented by every shipped migration operation."""

    spec: OperationSpec

    def plan(self, context: OperationContext) -> dict[str, Any]:
        """Return a ``MigrationOperationEntry``-shaped dictionary."""

    def apply(
        self, context: OperationContext, operation_entry: dict[str, Any]
    ) -> OperationOutcome:
        """Apply one operation entry or return a refusal."""

    def verify(
        self, context: OperationContext, operation_entry: dict[str, Any]
    ) -> OperationOutcome:
        """Verify one operation entry's post-conditions."""


__all__ = [
    "MigrationInjectedAbort",
    "MigrationOperation",
    "OperationContext",
    "OperationOutcome",
]

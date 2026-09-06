"""Outcome type shared by every migration_kit driver command.

TEMPORARY MODULE: deletion owner sase-x7.14.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class MigrationCommandOutcome:
    """Machine-readable result returned by every driver command."""

    ok: bool
    command: str
    dry_run: bool
    message: str
    run_id: str | None = None
    manifest_path: str | None = None
    receipt_path: str | None = None
    errors: tuple[str, ...] = ()
    details: dict[str, Any] = field(default_factory=dict)

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "command": self.command,
            "dry_run": self.dry_run,
            "message": self.message,
            "run_id": self.run_id,
            "manifest_path": self.manifest_path,
            "receipt_path": self.receipt_path,
            "errors": list(self.errors),
            "details": self.details,
        }

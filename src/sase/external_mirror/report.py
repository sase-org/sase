"""Structured reports for external mirror passes."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class MirrorReport:
    seen: int = 0
    fetched: int = 0
    created: int = 0
    repaired: int = 0
    skipped: int = 0
    conflicts: int = 0
    errors: int = 0
    budget_exhausted: int = 0
    checkpoint_advanced: int = 0
    noop_reason: str | None = None
    error_details: list[str] = field(default_factory=list)

    def summary_fields(self) -> dict[str, int]:
        """Return counters accepted by ``BuiltinChopRuntime.emit_summary``."""
        return {
            "seen": self.seen,
            "fetched": self.fetched,
            "created": self.created,
            "repaired": self.repaired,
            "skipped": self.skipped,
            "conflicts": self.conflicts,
            "errors": self.errors,
            "budget_exhausted": self.budget_exhausted,
            "checkpoint_advanced": self.checkpoint_advanced,
        }

    def reason(self) -> str | None:
        """Return the most informative no-op/degraded reason, if any."""
        if self.noop_reason:
            return self.noop_reason
        if self.errors:
            return "errors"
        if self.budget_exhausted:
            return "budget_exhausted"
        if self.conflicts:
            return "conflicts"
        if self.fetched == 0:
            return "no_remote_pull_requests"
        if self.created == 0 and self.repaired == 0 and self.skipped:
            return "all_skipped"
        return None


__all__ = ["MirrorReport"]

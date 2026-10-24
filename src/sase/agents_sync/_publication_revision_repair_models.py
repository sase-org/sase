"""Shared report models for publication revision repair."""

from __future__ import annotations

from dataclasses import dataclass

from sase.core.agent_publication_recovery import (
    STALE_REPAIR_ACTION_LINKED,
    STALE_REPAIR_ACTION_REPAIRED,
    STALE_REPAIR_ACTION_UNCHANGED,
    STALE_REPAIR_ACTION_UNRESOLVED,
)

REPAIR_REVISIONS_COMMAND = "sase agent sync --repair-revisions"
REPAIR_REVISIONS_APPLY_COMMAND = "sase agent sync --repair-revisions --apply"
REPAIR_REVISIONS_AUDIT_FILENAME = "agents-publication-repair-audit.jsonl"


@dataclass(frozen=True, slots=True)
class StaleRevisionRowReport:
    """One row's repair classification for report and audit output."""

    global_agent: str
    local_agent: str
    requested_revision: str
    current_revision: str
    current_scope: str
    action: str
    fulfilling_revision: str | None = None
    new_scope: str | None = None
    evidence_commit: str | None = None
    reason: str = ""
    merged_from: tuple[tuple[str, str], ...] = ()

    @property
    def changed(self) -> bool:
        """Return whether applying this row rewrites the outbox."""

        return self.action in (
            STALE_REPAIR_ACTION_LINKED,
            STALE_REPAIR_ACTION_REPAIRED,
        )

    def diagnostic(self) -> str:
        """Render one stable report line for this row."""

        requested = _short(self.requested_revision)
        if self.action == STALE_REPAIR_ACTION_REPAIRED:
            return (
                f"{self.global_agent}@{requested}: repaired to "
                f"{_short(self.fulfilling_revision or '')} "
                f"({self.reason})"
            )
        if self.action == STALE_REPAIR_ACTION_LINKED:
            return (
                f"{self.global_agent}@{requested}: takes linked scope ({self.reason})"
            )
        if self.action == STALE_REPAIR_ACTION_UNRESOLVED:
            return (
                f"{self.global_agent}@{requested}: unresolved, kept as is "
                f"({self.reason})"
            )
        return f"{self.global_agent}@{requested}: unchanged ({self.reason})"


@dataclass(frozen=True, slots=True)
class StaleRevisionRepairReport:
    """The complete repair outcome for one project."""

    project_key: str
    project: str
    applied: bool
    rows: tuple[StaleRevisionRowReport, ...]
    changed: int
    audit_path: str | None = None

    def diagnostics(self) -> tuple[str, ...]:
        """Render the stable report lines for sync outcome output."""

        lines = [row.diagnostic() for row in self.rows]
        lines.append(self._summary())
        return tuple(lines)

    def _summary(self) -> str:
        counts: dict[str, int] = {}
        for row in self.rows:
            counts[row.action] = counts.get(row.action, 0) + 1
        breakdown = ", ".join(
            f"{counts.get(action, 0)} {action}"
            for action in (
                STALE_REPAIR_ACTION_UNCHANGED,
                STALE_REPAIR_ACTION_LINKED,
                STALE_REPAIR_ACTION_REPAIRED,
                STALE_REPAIR_ACTION_UNRESOLVED,
            )
        )
        if self.applied:
            if self.audit_path is not None:
                return (
                    f"applied {self.changed} stale revision change(s) "
                    f"({breakdown}); audit {self.audit_path}"
                )
            return (
                f"no stale revision changes to apply ({breakdown}); "
                "outbox already consistent"
            )
        return (
            f"report only ({breakdown}); rerun with "
            f"`{REPAIR_REVISIONS_APPLY_COMMAND}` to write"
        )


def _short(revision: str) -> str:
    """Return a stable abbreviated revision for report lines."""

    return revision[:12] if len(revision) > 12 else revision

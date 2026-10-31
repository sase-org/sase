"""Stable reports for evidence-based planner publication scope repair."""

from __future__ import annotations

from dataclasses import dataclass

REPAIR_PLANNER_SCOPES_COMMAND = "sase agent sync --repair-planner-scopes"
REPAIR_PLANNER_SCOPES_APPLY_COMMAND = "sase agent sync --repair-planner-scopes --apply"
REPAIR_PLANNER_SCOPES_AUDIT_FILENAME = (
    "agents-publication-planner-scope-repair-audit.jsonl"
)


@dataclass(frozen=True, slots=True)
class PlannerScopeRowReport:
    """One revision row's planner evidence and proposed scope change."""

    global_agent: str
    local_agent: str
    primary_revision: str
    eligible: bool
    evidence_kind: str | None
    evidence_commit: str | None
    reason: str

    def diagnostic(self, *, applied: bool) -> str:
        """Render one stable line for this outbox row."""

        key = f"{self.global_agent}@{_short(self.primary_revision)}"
        if not self.eligible:
            return f"{key}: unproven, kept as revision ({self.reason})"
        action = "takes linked scope" if applied else "would take linked scope"
        evidence = self.evidence_kind or "planner evidence"
        if self.evidence_commit is not None:
            evidence += f" at {self.evidence_commit[:12]}"
        return f"{key}: {action} ({evidence}; {self.reason})"


@dataclass(frozen=True, slots=True)
class PlannerScopeRepairReport:
    """Report the proven and unproven planner rows for one project."""

    project_key: str
    project: str
    applied: bool
    rows: tuple[PlannerScopeRowReport, ...]
    changed: int
    audit_path: str | None = None
    evidence_error: str | None = None

    def diagnostics(self) -> tuple[str, ...]:
        """Render detailed rows and one stable summary line."""

        lines = [row.diagnostic(applied=self.applied) for row in self.rows]
        proven = sum(row.eligible for row in self.rows)
        unproven = len(self.rows) - proven
        if self.applied:
            if self.changed:
                summary = (
                    f"applied {self.changed} planner scope change(s); "
                    f"{unproven} unproven row(s) unchanged; audit {self.audit_path}"
                )
            elif self.rows:
                summary = (
                    f"no planner scope changes applied; {unproven} unproven row(s)"
                )
            else:
                summary = "no revision-scope planner candidates"
        else:
            summary = (
                f"report only: {proven} proven planner row(s), "
                f"{unproven} unproven row(s); rerun with "
                f"`{REPAIR_PLANNER_SCOPES_APPLY_COMMAND}` to write"
            )
        lines.append(summary)
        if self.evidence_error is not None:
            lines.append(f"planner archive evidence unavailable: {self.evidence_error}")
        return tuple(lines)


def _short(revision: str) -> str:
    """Return a stable abbreviated SHA for report lines."""

    return revision[:12] if len(revision) > 12 else revision


__all__ = [
    "REPAIR_PLANNER_SCOPES_APPLY_COMMAND",
    "REPAIR_PLANNER_SCOPES_AUDIT_FILENAME",
    "REPAIR_PLANNER_SCOPES_COMMAND",
    "PlannerScopeRepairReport",
    "PlannerScopeRowReport",
]

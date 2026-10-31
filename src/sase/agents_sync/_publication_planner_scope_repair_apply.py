"""Outbox mutation and audit support for planner publication scope repair."""

from __future__ import annotations

from dataclasses import replace
import json
import time

from sase.agents_sync.models import ProjectTarget
from sase.agents_sync.publication_outbox import (
    PUBLICATION_SCOPE_LINKED,
    PUBLICATION_SCOPE_REVISION,
    AgentPublicationOutboxItem,
)
from sase.agents_sync.publication_outbox_operations import (
    mutate_publication_outbox,
)
from sase.agents_sync._publication_planner_scope_repair_models import (
    REPAIR_PLANNER_SCOPES_AUDIT_FILENAME,
    PlannerScopeRepairReport,
    PlannerScopeRowReport,
)
from sase.core.paths import sase_projects_dir


def apply_project_planner_scopes(
    target: ProjectTarget,
    report: PlannerScopeRepairReport,
) -> PlannerScopeRepairReport:
    """Change only proven row scopes and append one audit record per change."""

    if report.changed == 0:
        return replace(report, applied=True)

    candidates = {
        (row.global_agent, row.primary_revision): row
        for row in report.rows
        if row.eligible
    }
    applied_rows: list[PlannerScopeRowReport] = []

    def update(
        items: tuple[AgentPublicationOutboxItem, ...],
    ) -> tuple[AgentPublicationOutboxItem, ...]:
        rewritten: list[AgentPublicationOutboxItem] = []
        for item in items:
            row = candidates.get(item.logical_key)
            if (
                row is not None
                and item.scope == PUBLICATION_SCOPE_REVISION
                and item.local_agent == row.local_agent
            ):
                rewritten.append(replace(item, scope=PUBLICATION_SCOPE_LINKED))
                applied_rows.append(row)
            else:
                rewritten.append(item)
        return tuple(rewritten)

    mutate_publication_outbox(target.project_key, update)
    audit_path: str | None = None
    if applied_rows:
        audit_path = _append_planner_scope_audit(target.project_key, applied_rows)
    return replace(
        report,
        applied=True,
        changed=len(applied_rows),
        audit_path=audit_path,
    )


def _append_planner_scope_audit(
    project_key: str,
    rows: list[PlannerScopeRowReport],
) -> str:
    """Append one stable JSON object per scope change beside the outbox."""

    path = sase_projects_dir() / project_key / REPAIR_PLANNER_SCOPES_AUDIT_FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    applied_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    with path.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(
                json.dumps(
                    {
                        "applied_at": applied_at,
                        "project_key": project_key,
                        "global_agent": row.global_agent,
                        "local_agent": row.local_agent,
                        "primary_revision": row.primary_revision,
                        "old_scope": PUBLICATION_SCOPE_REVISION,
                        "new_scope": PUBLICATION_SCOPE_LINKED,
                        "evidence_kind": row.evidence_kind,
                        "evidence_commit": row.evidence_commit,
                        "reason": row.reason,
                    },
                    sort_keys=True,
                )
                + "\n"
            )
    return str(path)


__all__ = ["apply_project_planner_scopes"]

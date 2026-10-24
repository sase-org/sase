"""Outbox mutation and audit support for publication revision repair."""

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
from sase.agents_sync.publication_outbox_models import publication_sort_key
from sase.agents_sync.publication_outbox_operations import mutate_publication_outbox
from sase.agents_sync._publication_revision_repair_models import (
    REPAIR_REVISIONS_AUDIT_FILENAME,
    StaleRevisionRepairReport,
    StaleRevisionRowReport,
)
from sase.core.agent_publication_recovery import STALE_REPAIR_ACTION_REPAIRED
from sase.core.paths import sase_projects_dir


def apply_project_revisions(
    target: ProjectTarget,
    report: StaleRevisionRepairReport,
) -> StaleRevisionRepairReport:
    """Rewrite the outbox for changed rows and audit every applied change."""

    if report.changed == 0:
        return replace(report, applied=True)
    now = time.time()
    applied_rows: list[StaleRevisionRowReport] = []
    by_request = {
        (row.global_agent, row.requested_revision): row for row in report.rows
    }

    def update(
        items: tuple[AgentPublicationOutboxItem, ...],
    ) -> tuple[AgentPublicationOutboxItem, ...]:
        rewritten: list[AgentPublicationOutboxItem] = []
        for item in items:
            revised = _apply_row_report(item, report, now)
            rewritten.append(revised)
            if revised is not item:
                applied = by_request.get(
                    (revised.global_agent, revised.original_revision)
                )
                if applied is not None:
                    applied_rows.append(applied)
        grouped: dict[tuple[str, str], list[AgentPublicationOutboxItem]] = {}
        for item in rewritten:
            grouped.setdefault(item.logical_key, []).append(item)
        merged: list[AgentPublicationOutboxItem] = []
        for group in grouped.values():
            if len(group) == 1:
                merged.append(group[0])
            else:
                merged_item, merge_note = _merge_collision(group, now)
                merged.append(merged_item)
                applied_rows.append(merge_note)
        return tuple(sorted(merged, key=publication_sort_key))

    mutate_publication_outbox(target.project_key, update)
    audit_path: str | None = None
    if applied_rows:
        audit_path = _append_repair_audit(target.project_key, applied_rows, now)
    rows = tuple(_with_merge_notes(row, applied_rows) for row in report.rows)
    return replace(report, applied=True, rows=rows, audit_path=audit_path)


def _apply_row_report(
    item: AgentPublicationOutboxItem,
    report: StaleRevisionRepairReport,
    now: float,
) -> AgentPublicationOutboxItem:
    """Rekey or re-scope one row when its report row still matches."""

    row = next(
        (
            candidate
            for candidate in report.rows
            if candidate.global_agent == item.global_agent
            and candidate.requested_revision == item.original_revision
        ),
        None,
    )
    if row is None or not row.changed:
        return item
    if row.action == STALE_REPAIR_ACTION_REPAIRED:
        if (
            item.primary_revision == row.fulfilling_revision
            and item.scope == PUBLICATION_SCOPE_REVISION
        ):
            return item
        return replace(
            item,
            primary_revision=row.fulfilling_revision or item.primary_revision,
            requested_revision=row.requested_revision,
            scope=PUBLICATION_SCOPE_REVISION,
            updated_at=now,
        )
    if item.scope == PUBLICATION_SCOPE_LINKED:
        return item
    return replace(
        item,
        scope=PUBLICATION_SCOPE_LINKED,
        updated_at=now,
    )


def _merge_collision(
    group: list[AgentPublicationOutboxItem],
    now: float,
) -> tuple[AgentPublicationOutboxItem, StaleRevisionRowReport]:
    """Merge rows sharing a logical key after rekeying, deterministically."""

    ordered = sorted(group, key=lambda item: (item.created_at, item.id))
    survivor = ordered[0]
    latest = max(group, key=lambda item: (item.updated_at, item.id))
    digest = survivor.hood_digest
    if digest == "pending":
        for candidate in ordered[1:]:
            if candidate.hood_digest != "pending":
                digest = candidate.hood_digest
                break
    merged = replace(
        survivor,
        hood_digest=digest,
        scope=(
            PUBLICATION_SCOPE_REVISION
            if any(item.scope == PUBLICATION_SCOPE_REVISION for item in ordered)
            else PUBLICATION_SCOPE_LINKED
        ),
        attempts=max(item.attempts for item in ordered),
        last_error=latest.last_error,
        quarantined=any(item.quarantined for item in ordered),
        quarantined_at=(
            latest.quarantined_at if any(item.quarantined for item in ordered) else None
        ),
        terminal=any(item.terminal for item in ordered),
        terminal_reason=_merged_terminal_reason(ordered),
        updated_at=now,
    )
    note = StaleRevisionRowReport(
        global_agent=merged.global_agent,
        local_agent=merged.local_agent,
        requested_revision=merged.original_revision,
        current_revision=merged.primary_revision,
        current_scope=merged.scope,
        action="merged",
        reason="logical-key collision merged deterministically",
        merged_from=tuple((item.global_agent, item.primary_revision) for item in group),
    )
    return merged, note


def _merged_terminal_reason(
    ordered: list[AgentPublicationOutboxItem],
) -> str | None:
    """Return the latest terminal reason among merged rows, if any."""

    terminal_rows = [item for item in ordered if item.terminal]
    if not terminal_rows:
        return None
    latest = max(terminal_rows, key=lambda item: (item.updated_at, item.id))
    return latest.terminal_reason


def _with_merge_notes(
    row: StaleRevisionRowReport,
    applied_rows: list[StaleRevisionRowReport],
) -> StaleRevisionRowReport:
    """Attach merge records to their surviving report row."""

    for applied in applied_rows:
        if (
            applied.action == "merged"
            and applied.global_agent == row.global_agent
            and applied.requested_revision == row.requested_revision
        ):
            return replace(row, merged_from=applied.merged_from)
    return row


def _append_repair_audit(
    project_key: str,
    applied_rows: list[StaleRevisionRowReport],
    now: float,
) -> str:
    """Append one audit JSON object per applied change beside the outbox."""

    path = sase_projects_dir() / project_key / REPAIR_REVISIONS_AUDIT_FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    applied_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now))
    with path.open("a", encoding="utf-8") as handle:
        for row in applied_rows:
            handle.write(
                json.dumps(
                    {
                        "applied_at": applied_at,
                        "project_key": project_key,
                        "action": row.action,
                        "global_agent": row.global_agent,
                        "local_agent": row.local_agent,
                        "original_revision": row.requested_revision,
                        "current_revision": row.current_revision,
                        "fulfilling_revision": row.fulfilling_revision,
                        "new_scope": row.new_scope,
                        "evidence_commit": row.evidence_commit,
                        "merged_from": [
                            {
                                "global_agent": key[0],
                                "primary_revision": key[1],
                            }
                            for key in row.merged_from
                        ],
                        "reason": row.reason,
                    },
                    sort_keys=True,
                )
                + "\n"
            )
    return str(path)

"""Attachment health for ``sase bead doctor``.

The check reports token/manifest mismatches, dangling descriptors (no bytes
anywhere), pending outbox items, local-only objects, tombstoned references,
local digest mismatches, and orphan local objects older than 7 days. The
``--fix-attachments`` repair removes orphans, re-drains the outbox, and
quarantines corrupt objects. Beads without attachments (and with a clean
cache) report nothing: no attachment imports beyond the local scan, no git,
no network on the healthy path beyond one bounded store probe per digest.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from sase.bead.attachments.lifecycle import (
    collect_inventory,
    orphan_digests,
    outbox_digests_for_project,
    quarantine_local_object,
    remove_orphan_objects,
    store_has_digest,
    store_has_tombstone,
)
from sase.bead.attachments.store import LocalAttachmentStore
from sase.bead.attachments.tombstones import has_local_tombstone

log = logging.getLogger(__name__)

_REPAIR_HINT = "sase bead doctor --fix-attachments"


@dataclass
class AttachmentHealthReport:
    """Structured attachment health for one project."""

    healthy: bool = True
    has_attachments: bool = False
    errors: list[str] = field(default_factory=list)
    mismatches: list[str] = field(default_factory=list)
    dangling: list[str] = field(default_factory=list)
    corrupt: list[str] = field(default_factory=list)
    orphans: list[str] = field(default_factory=list)
    tombstoned: list[str] = field(default_factory=list)
    pending_upload: int = 0
    local_only: int = 0
    outbox_unreadable: bool = False


def manifest_mismatches(issues: list[Any]) -> list[str]:
    """Return token/manifest mismatch lines across *issues*' manifests."""
    from sase.bead.attachment_presentation import extract_attachment_tokens

    lines: list[str] = []
    for issue in issues:
        records: list[tuple[str, Any]] = []
        for ordinal, note in enumerate(getattr(issue, "notes", ()) or (), start=1):
            records.append((f"note#{ordinal}", note))
        for index, evidence in enumerate(
            getattr(issue, "plus_one_evidence", ()) or (), start=1
        ):
            records.append((f"+1#{index}", evidence))
        for source, record in records:
            try:
                prose = getattr(record, "text", None) or getattr(record, "note", None)
                tokens = set(extract_attachment_tokens(prose or ""))
            except Exception:
                continue
            try:
                manifest = {
                    str(item.name) for item in getattr(record, "attachments", ()) or ()
                }
            except Exception:
                continue
            if tokens != manifest:
                lines.append(
                    f"{issue.id} {source}: tokens {sorted(tokens)} != "
                    f"manifest {sorted(manifest)}"
                )
    return lines


def inspect_attachment_health() -> AttachmentHealthReport:
    """Inspect attachment health; never raises on store or git failures.

    When the bead store itself is unavailable, the core doctor already
    reports that: this returns a clean empty report so plain
    ``sase bead doctor`` output stays unchanged.
    """
    report = AttachmentHealthReport()
    try:
        from sase.bead.cli_common import get_read_view

        with get_read_view() as view:
            inventory = collect_inventory(view)
    except Exception as exc:
        log.debug("attachment doctor store unavailable: %s", exc)
        return report
    if inventory.references:
        report.has_attachments = True
    try:
        from sase.bead.cli_common import get_read_view as _get_view
        from sase.bead.model import Status as _Status

        with _get_view() as _view:
            _issues = _view.list_issues(
                statuses=[
                    _Status.OPEN,
                    _Status.CLAIMED,
                    _Status.READY,
                    _Status.SNOOZED,
                    _Status.IN_PROGRESS,
                    _Status.CLOSED,
                ],
            )
        report.mismatches = manifest_mismatches(list(_issues))
    except Exception as exc:
        log.debug("attachment doctor mismatch scan skipped: %s", exc)
    if report.mismatches:
        report.healthy = False
    try:
        from sase.bead.attachments.upload import (
            discover_stores,
            resolve_project_key,
        )

        stores = discover_stores(None)
    except Exception as exc:
        log.debug("attachment doctor store discovery skipped: %s", exc)
        stores = {}
    try:
        project_key = resolve_project_key(None)
    except Exception:
        project_key = None
    outbox: set[str] = set()
    if project_key:
        try:
            from sase.bead.attachments.outbox import read_outbox

            outbox = {entry.digest for entry in read_outbox(project_key)}
        except ValueError as exc:
            report.outbox_unreadable = True
            report.healthy = False
            log.debug("attachment outbox unreadable: %s", exc)
        except Exception as exc:
            log.debug("attachment outbox read skipped: %s", exc)
    elif inventory.references or inventory.local_objects:
        report.outbox_unreadable = False
    local = LocalAttachmentStore()
    referenced = inventory.digests_referenced()
    if outbox:
        report.pending_upload = len(outbox)
    for digest in sorted(referenced):
        try:
            local_present = local.has(digest)
        except Exception:
            local_present = False
        tombstoned = False
        try:
            tombstoned = has_local_tombstone(local, digest) or (
                bool(stores) and store_has_tombstone(stores, digest)
            )
        except Exception:
            tombstoned = False
        if tombstoned:
            report.tombstoned.append(digest)
            continue
        verified = False
        if local_present:
            try:
                verified = local.verify(digest)
            except Exception:
                verified = False
            if not verified:
                report.corrupt.append(digest)
                report.healthy = False
                continue
        remote = False
        if stores:
            try:
                remote = store_has_digest(stores, digest)
            except Exception:
                remote = False
        if digest in outbox:
            continue
        if not local_present and not remote:
            report.dangling.append(digest)
            report.healthy = False
        elif local_present and not remote:
            report.local_only += 1
    try:
        report.orphans = orphan_digests(inventory)
    except Exception as exc:
        log.debug("attachment doctor orphan scan skipped: %s", exc)
    if report.orphans:
        report.healthy = False
    return report


def render_attachment_health_messages(report: AttachmentHealthReport) -> list[str]:
    """Render concise doctor messages; empty when there is nothing to say."""
    if report.errors:
        return [
            f"WARNING: attachment doctor unavailable: {error}"
            for error in report.errors
        ]
    if (
        not report.has_attachments
        and not report.orphans
        and not report.corrupt
        and not report.dangling
        and not report.mismatches
        and not report.pending_upload
        and not report.tombstoned
        and not report.local_only
    ):
        return []
    summary = (
        f"Attachments: {len(report.mismatches)} token/manifest mismatch(es), "
        f"{len(report.dangling)} dangling, {len(report.corrupt)} corrupt, "
        f"{len(report.orphans)} orphan(s), {report.pending_upload} pending "
        f"upload(s), {report.local_only} local-only, "
        f"{len(report.tombstoned)} tombstoned"
    )
    if report.healthy and not _needs_repair(report):
        return [summary]
    messages = [summary + f" (repair with: {_REPAIR_HINT})"]
    for line in report.mismatches:
        messages.append(f"  token/manifest mismatch: {line}")
    for digest in report.dangling:
        messages.append(f"  dangling descriptor (no bytes anywhere): {digest[:12]}…")
    for digest in report.corrupt:
        messages.append(f"  local digest mismatch: {digest[:12]}…")
    for digest in report.orphans:
        messages.append(f"  orphan local object (>7d unreferenced): {digest[:12]}…")
    for digest in report.tombstoned:
        messages.append(f"  tombstoned reference (renders (purged)): {digest[:12]}…")
    if report.pending_upload:
        messages.append(f"  {report.pending_upload} object(s) pending upload")
    if report.local_only:
        messages.append(f"  {report.local_only} local-only object(s)")
    if report.outbox_unreadable:
        messages.append("  attachment outbox is unreadable")
    return messages


def _needs_repair(report: AttachmentHealthReport) -> bool:
    """Return whether the repair would change anything."""
    return bool(
        report.orphans
        or report.corrupt
        or report.pending_upload
        or report.outbox_unreadable
    )


def preview_attachment_repairs(report: AttachmentHealthReport) -> list[str]:
    """Preview the ``--fix-attachments`` repair lines."""
    lines: list[str] = []
    if report.orphans:
        lines.append(
            f"Remove {len(report.orphans)} orphan local object(s) "
            "(unreferenced, older than 7 days)."
        )
    if report.corrupt:
        lines.append(
            f"Quarantine {len(report.corrupt)} corrupt local object(s) "
            "for forensics; shared-store copies refetch on demand."
        )
    if report.pending_upload or report.outbox_unreadable:
        lines.append("Re-drain the attachment upload outbox (bounded).")
    if report.mismatches or report.dangling or report.tombstoned:
        lines.append(
            "Token/manifest mismatches, dangling descriptors, and tombstoned "
            "references need manual note edits; no automatic repair."
        )
    return lines


def repair_attachment_health(report: AttachmentHealthReport) -> list[str]:
    """Apply the repair; return one result line per action."""
    results: list[str] = []
    if report.orphans:
        removed, freed = remove_orphan_objects(list(report.orphans))
        results.append(f"Removed {removed} orphan object(s) ({freed} bytes).")
    if report.corrupt:
        moved = sum(1 for digest in report.corrupt if quarantine_local_object(digest))
        results.append(f"Quarantined {moved} corrupt object(s).")
    if report.pending_upload or report.outbox_unreadable:
        try:
            from sase.bead.attachments.background import drain_project_outbox
            from sase.bead.attachments.upload import resolve_project_key

            project_key = resolve_project_key(None)
            if project_key is None:
                results.append("Outbox drain skipped: no project resolved.")
            else:
                drained, remaining = drain_project_outbox(
                    project_key, time_bound_seconds=60.0, progress=False
                )
                results.append(
                    f"Drained {drained} queued upload(s); {remaining} remain."
                )
        except Exception as exc:
            results.append(f"Outbox drain skipped: {exc}")
    return results


__all__ = [
    "AttachmentHealthReport",
    "inspect_attachment_health",
    "manifest_mismatches",
    "preview_attachment_repairs",
    "render_attachment_health_messages",
    "repair_attachment_health",
]

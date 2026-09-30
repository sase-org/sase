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
class _AttachmentHealthReport:
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
    rescan_hits: list[str] = field(default_factory=list)
    store_growth: list[str] = field(default_factory=list)


def _current_scanner_rules_version() -> int:
    """Return the core scanner rules version, failing open to 1."""
    try:
        from sase.bead.attachments import audience as _audience

        return int(_audience.scanner_rules_version())
    except Exception:
        return 1


def _read_audience_metadata_dict(digest: str) -> dict[str, object] | None:
    """Return the local audience metadata for *digest*, if recorded."""
    try:
        import json as _json

        from sase.bead.attachments import audience as _audience

        raw = _audience.audience_metadata_path(digest).read_text(encoding="utf-8")
        data = _json.loads(raw)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _public_note_targets(
    issues: list[Any],
) -> dict[str, list[tuple[str, str, int]]]:
    """Map each public note digest to ``(issue_id, name, size)`` targets."""
    targets: dict[str, list[tuple[str, str, int]]] = {}
    for issue in issues:
        issue_id = str(getattr(issue, "id", "") or "")
        for note in getattr(issue, "notes", ()) or ():
            for attachment in getattr(note, "attachments", ()) or ():
                try:
                    effective = attachment.effective_visibility()
                except Exception:
                    effective = "private"
                if effective != "public":
                    continue
                digest = str(getattr(attachment, "sha256", "") or "")
                if not digest:
                    continue
                name = str(getattr(attachment, "name", "") or "")
                try:
                    size = int(getattr(attachment, "size_bytes", 0) or 0)
                except Exception:
                    size = 0
                targets.setdefault(digest, []).append((issue_id, name, size))
    return targets


def _find_stale_scanner_hits(
    issues: list[Any] | None = None,
) -> list[str]:
    """Rescan cached public objects recorded under older scanner rules.

    Only public note descriptors whose local audience metadata records a
    ``scanner_rules_version`` older than the current one are rescanned, and
    only when the bytes are cached locally. A hit never unpublishes
    automatically; the finding names the ``unpublish`` command.
    """
    from sase.bead.attachments.store import LocalAttachmentStore

    if issues is None:
        try:
            from sase.bead.cli_common import get_read_view
            from sase.bead.model import Status as _Status

            with get_read_view() as _view:
                issues = list(
                    _view.list_issues(
                        statuses=[
                            _Status.OPEN,
                            _Status.CLAIMED,
                            _Status.READY,
                            _Status.SNOOZED,
                            _Status.IN_PROGRESS,
                            _Status.CLOSED,
                        ],
                    )
                )
        except Exception:
            return []
    current = _current_scanner_rules_version()
    targets = _public_note_targets(list(issues))
    if not targets:
        return []
    local = LocalAttachmentStore()
    findings: list[str] = []
    for digest in sorted(targets):
        metadata = _read_audience_metadata_dict(digest)
        if metadata is None:
            continue
        try:
            recorded_raw = metadata.get("scanner_rules_version", current)
            assert isinstance(recorded_raw, (int, str))
            recorded = int(recorded_raw)
        except Exception:
            continue
        if recorded >= current:
            continue
        try:
            if not local.has(digest) or not local.verify(digest):
                continue
        except Exception:
            continue
        scan: dict[str, Any] | None = None
        try:
            from sase.bead.attachments import audience as _audience
            from sase.bead.config import get_attachment_public_max_bytes

            scan = _audience.scan_cas_object(
                local.object_path(digest),
                max_bytes=get_attachment_public_max_bytes(),
            )
        except Exception:
            continue
        if scan is None or str(scan.get("outcome") or "") != "hit":
            continue
        hit = scan.get("hit") if isinstance(scan.get("hit"), dict) else {}
        kind = str((hit or {}).get("kind") or "credential")
        rule_id = str((hit or {}).get("rule_id") or kind)
        issue_id, name, _size = targets[digest][0]
        findings.append(
            f"rotate the credential first, then sase bead attachment "
            f"unpublish {issue_id} {name} "
            f"(sha256:{digest[:12]}… rescanned hit {kind}/{rule_id} under "
            f"rules v{current}, recorded v{recorded})"
        )
    return findings


def store_growth_lines() -> list[str]:
    """Report logical and physical bytes per reachable shared store."""
    try:
        from sase.bead.attachments.upload import discover_stores

        stores = discover_stores(None)
    except Exception:
        return []
    if not stores:
        return []
    lines: list[str] = []
    for tier in ("public", "git", "large"):
        store = stores.get(tier)
        if store is None:
            continue
        logical = _logical_bytes_for_store(store)
        physical = _physical_bytes_for_store(store)
        guidance = ""
        size_for_guidance = physical if physical is not None else logical
        if size_for_guidance is not None and size_for_guidance >= 1073741824:
            guidance = (
                " — approaching GitHub's 1–5 GB repo guidance; "
                "rotate or prune before pushing more"
            )
        if physical is not None:
            lines.append(
                f"{tier} store {store.describe()}: logical "
                f"{_format_bytes(logical)}, physical {_format_bytes(physical)}"
                f"{guidance}"
            )
        else:
            lines.append(
                f"{tier} store {store.describe()}: logical "
                f"{_format_bytes(logical)}{guidance}"
            )
    return lines


def _logical_bytes_for_store(store: Any) -> int | None:
    """Sum referenced sizes confirmed present in *store*."""
    try:
        from sase.bead.cli_common import get_read_view
        from sase.bead.model import Status as _Status

        with get_read_view() as view:
            issues = view.list_issues(
                statuses=[
                    _Status.OPEN,
                    _Status.CLAIMED,
                    _Status.READY,
                    _Status.SNOOZED,
                    _Status.IN_PROGRESS,
                    _Status.CLOSED,
                ],
            )
    except Exception:
        return None
    total = 0
    seen: set[str] = set()
    for issue in issues or ():
        for source in list(getattr(issue, "notes", ()) or ()) + list(
            getattr(issue, "plus_one_evidence", ()) or ()
        ):
            for attachment in getattr(source, "attachments", ()) or ():
                digest = str(getattr(attachment, "sha256", "") or "")
                if not digest or digest in seen:
                    continue
                try:
                    present = bool(store.has(digest))
                except Exception:
                    continue
                if not present:
                    continue
                seen.add(digest)
                try:
                    total += int(getattr(attachment, "size_bytes", 0) or 0)
                except Exception:
                    continue
    return total


def _physical_bytes_for_store(store: Any) -> int | None:
    """Return the on-disk bytes of a git store clone, if discoverable."""
    try:
        from pathlib import Path as _Path

        repo = getattr(store, "_repo", None)
        if repo is None:
            return None
        root = _Path(str(repo))
        if not root.is_dir():
            return None
        total = 0
        for path in root.rglob("*"):
            try:
                if path.is_file() and not path.is_symlink():
                    total += path.stat().st_size
            except OSError:
                continue
        return total
    except Exception:
        return None


def _format_bytes(value: int | None) -> str:
    """Format an optional byte count for doctor output."""
    if value is None:
        return "unknown size"
    try:
        from sase.bead.attachments.fetch import format_attachment_size

        return format_attachment_size(int(value))
    except Exception:
        return f"{value} bytes"


def _manifest_mismatches(issues: list[Any]) -> list[str]:
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


def inspect_attachment_health() -> _AttachmentHealthReport:
    """Inspect attachment health; never raises on store or git failures.

    When the bead store itself is unavailable, the core doctor already
    reports that: this returns a clean empty report so plain
    ``sase bead doctor`` output stays unchanged.
    """
    report = _AttachmentHealthReport()
    try:
        from sase.bead.cli_common import get_read_view

        with get_read_view() as view:
            inventory = collect_inventory(view)
    except Exception as exc:
        log.debug("attachment doctor store unavailable: %s", exc)
        return report
    if inventory.references:
        report.has_attachments = True
    all_issues: list[Any] | None = None
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
        all_issues = list(_issues)
        report.mismatches = _manifest_mismatches(all_issues)
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
    try:
        report.rescan_hits = _find_stale_scanner_hits(all_issues)
    except Exception as exc:
        log.debug("attachment doctor rescan skipped: %s", exc)
        report.rescan_hits = []
    if report.rescan_hits:
        report.healthy = False
        report.has_attachments = True
    try:
        report.store_growth = store_growth_lines()
    except Exception as exc:
        log.debug("attachment doctor growth scan skipped: %s", exc)
        report.store_growth = []
    return report


def render_attachment_health_messages(report: _AttachmentHealthReport) -> list[str]:
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
        and not report.rescan_hits
        and not report.store_growth
    ):
        return []
    summary = (
        f"Attachments: {len(report.mismatches)} token/manifest mismatch(es), "
        f"{len(report.dangling)} dangling, {len(report.corrupt)} corrupt, "
        f"{len(report.orphans)} orphan(s), {report.pending_upload} pending "
        f"upload(s), {report.local_only} local-only, "
        f"{len(report.tombstoned)} tombstoned, "
        f"{len(report.rescan_hits)} stale-scan hit(s)"
    )
    if report.healthy and not _needs_repair(report):
        base = [summary]
        base.extend(f"  {line}" for line in report.store_growth)
        return base
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
    for hit in report.rescan_hits:
        messages.append(f"  stale scanner rules hit: {hit}")
    for line in report.store_growth:
        messages.append(f"  {line}")
    return messages


def _needs_repair(report: _AttachmentHealthReport) -> bool:
    """Return whether the repair would change anything."""
    return bool(
        report.orphans
        or report.corrupt
        or report.pending_upload
        or report.outbox_unreadable
    )


def preview_attachment_repairs(report: _AttachmentHealthReport) -> list[str]:
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


def repair_attachment_health(report: _AttachmentHealthReport) -> list[str]:
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
    "_AttachmentHealthReport",
    "inspect_attachment_health",
    "_manifest_mismatches",
    "preview_attachment_repairs",
    "render_attachment_health_messages",
    "repair_attachment_health",
]

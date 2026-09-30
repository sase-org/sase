"""Bead attachment lifecycle commands: ``purge`` and ``prune``.

``purge`` removes one attachment's bytes everywhere while leaving every bead
event untouched: a tombstone goes to each configured shared store, the local
object and its views are deleted, and a local tombstone is recorded, so
notes render ``(purged)`` and fetches refuse the digest. ``prune`` evicts
cached objects confirmed present in a shared store, oldest first, to fit
under the local cache budget. Neither command authors notes or checks the
beta flag.
"""

from __future__ import annotations

import argparse
import sys
from typing import Any

from sase.bead.attachment_presentation import strip_display_name
from sase.bead.attachments.fetch import format_attachment_size
from sase.bead.attachments.lifecycle import (
    apply_prune_evictions,
    collect_inventory,
    outbox_digests_for_project,
    plan_prune,
    roster_for_issue,
)
from sase.bead.attachments.store import LocalAttachmentStore
from sase.bead.attachments.tombstones import (
    tombstone_bytes,
    write_local_tombstone,
)
from sase.bead.cli_common import get_read_view, resolve_bead_operation_context


def _stores_for_purge(bead_context: Any) -> dict[str, Any]:
    """Return every reachable shared store, never raising."""
    try:
        from sase.bead.attachments.upload import discover_stores

        return discover_stores(bead_context)
    except Exception:
        return {}


def _confirm_purge(name: str, digest: str, reference_count: int) -> bool:
    """Ask for an interactive purge confirmation; False declines."""
    print(
        f"Purge {strip_display_name(name)} (sha256:{digest[:12]}…) "
        f"referenced by {reference_count} note(s)? [y/N] ",
        file=sys.stderr,
        end="",
    )
    try:
        answer = input().strip().lower()
    except (EOFError, KeyboardInterrupt):
        return False
    return answer in {"y", "yes"}


def handle_bead_attachment_purge(args: argparse.Namespace) -> None:
    """Purge one attachment's bytes behind tombstones, keeping all events."""
    name = str(getattr(args, "name", "") or "")
    reason = str(getattr(args, "reason", "") or "")
    assume_yes = bool(getattr(args, "yes", False))
    if not name:
        print("Error: attachment name cannot be empty.", file=sys.stderr)
        sys.exit(1)
    if not reason.strip():
        print(
            "Error: -r/--reason is required to purge an attachment.",
            file=sys.stderr,
        )
        sys.exit(1)
    bead_context = resolve_bead_operation_context([args.id])
    resolved_id = bead_context.resolved_ids[0]
    with get_read_view(bead_context=bead_context) as view:
        try:
            issue = view.show(resolved_id)
        except KeyError:
            print(f"Error: issue not found: {args.id}", file=sys.stderr)
            sys.exit(1)
        roster = roster_for_issue(issue)
        attachment = roster.get(name)
        if attachment is None:
            print(
                f"Error: attachment not found: {strip_display_name(name)} "
                f"on {resolved_id}",
                file=sys.stderr,
            )
            sys.exit(1)
        digest = attachment.sha256
        inventory = collect_inventory(view)
    references = inventory.references_for_digest(digest)
    print(
        f"Purging {strip_display_name(name)} (sha256:{digest[:12]}…) "
        f"from {resolved_id} — {reason.strip()}"
    )
    if references:
        print("References (notes keep their text and render (purged)):")
        for reference in references:
            print(f"  {reference.issue_id} {reference.source} {reference.name}")
    else:
        print("No current note references this digest.")
    if not assume_yes:
        import sys as _sys

        if not (_sys.stdin.isatty() and _sys.stderr.isatty()):
            print(
                "Refusing to purge without confirmation on a non-TTY; "
                "re-run with -y/--yes.",
                file=sys.stderr,
            )
            sys.exit(2)
        if not _confirm_purge(name, digest, len(references)):
            print("Purge cancelled; nothing was removed.")
            return
    payload = tombstone_bytes(digest, reason.strip())
    stores = _stores_for_purge(bead_context)
    store_results: list[str] = []
    for tier in ("git", "large"):
        store = stores.get(tier)
        if store is None:
            continue
        writer = getattr(store, "write_tombstone", None)
        try:
            if writer is not None:
                writer(digest, payload)
                store_results.append(f"{tier}: tombstone written")
            else:
                store.delete(digest)
                store_results.append(f"{tier}: object deleted (no tombstone support)")
        except Exception as exc:
            print(
                f"Error: purge tombstone write to the {tier} store failed: {exc}",
                file=sys.stderr,
            )
            sys.exit(1)
    local = LocalAttachmentStore()
    try:
        local_removed = local.remove(digest)
    except Exception as exc:
        print(f"Error: local purge removal failed: {exc}", file=sys.stderr)
        sys.exit(1)
    try:
        write_local_tombstone(local, digest, reason.strip())
    except Exception as exc:
        print(f"Error: local purge tombstone failed: {exc}", file=sys.stderr)
        sys.exit(1)
    try:
        from sase.bead.attachments.upload import resolve_project_key

        project_key = resolve_project_key(bead_context)
        if project_key:
            from sase.bead.attachments.outbox import remove_outbox_digests

            remove_outbox_digests(project_key, {digest})
    except Exception:
        pass
    if store_results:
        for result in store_results:
            print(f"  {result}")
    else:
        print("  no shared store on this machine — local purge only")
    print(
        f"Purged {strip_display_name(name)} (sha256:{digest[:12]}…): "
        f"{'local object removed; ' if local_removed else 'no local object; '}"
        f"{len(references)} note(s) now render (purged)."
    )
    print(
        "To also erase the bytes from the private repo history "
        "(not automated):\n"
        "  git clone --bare <attachments-private-remote> /tmp/attachments-scrub\n"
        f"  git -C /tmp/attachments-scrub filter-repo --path files/objects/sha256/{digest[:2]}/{digest} --invert-paths --force\n"
        "  git -C /tmp/attachments-scrub push --force --all"
    )


def handle_bead_attachment_prune(args: argparse.Namespace) -> None:
    """Evict store-confirmed cached objects to fit the cache budget."""
    assume_yes = bool(getattr(args, "yes", False))
    from sase.bead.attachments.upload import discover_stores, resolve_project_key

    from sase.bead.config import get_attachment_local_cache_max_bytes

    budget = get_attachment_local_cache_max_bytes()
    try:
        stores = discover_stores(None)
    except Exception:
        stores = {}
    with get_read_view() as view:
        inventory = collect_inventory(view)
    try:
        project_key = resolve_project_key(None)
    except Exception:
        project_key = None
    if not stores:
        print(
            "No attachment shared store on this machine; every cached object "
            "is local-only by design — nothing to prune."
        )
        return
    plan = plan_prune(
        inventory, stores, outbox_digests_for_project(project_key), budget
    )
    print(
        f"Attachment cache: {format_attachment_size(plan.total_bytes)} "
        f"(budget {format_attachment_size(plan.budget_bytes)})"
    )
    if plan.skipped_pending:
        print(f"  {plan.skipped_pending} pending-upload object(s) kept")
    if plan.skipped_local_only:
        print(f"  {plan.skipped_local_only} local-only object(s) kept")
    if not plan.evict:
        print("Cache fits the budget; nothing to prune.")
        return
    print(
        f"Plan: evict {len(plan.evict)} object(s), freeing "
        f"{format_attachment_size(plan.evicted_bytes)} "
        f"(leaving {format_attachment_size(plan.remaining_bytes)}):"
    )
    for candidate in plan.evict:
        label = candidate.names[0] if candidate.names else "unnamed"
        print(
            f"  {candidate.sha256[:12]}…  "
            f"{format_attachment_size(candidate.size_bytes)}  "
            f"{strip_display_name(label)}"
        )
    if not assume_yes:
        print("Dry run — re-run with -y/--yes to evict.")
        return
    evicted, freed = apply_prune_evictions(plan)
    print(
        f"Pruned {evicted} object(s), freeing {format_attachment_size(freed)}; "
        f"cache is now {format_attachment_size(plan.total_bytes - freed)}."
    )


__all__ = [
    "handle_bead_attachment_prune",
    "handle_bead_attachment_purge",
]

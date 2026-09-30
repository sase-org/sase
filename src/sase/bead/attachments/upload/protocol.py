"""Pre-write / post-write upload protocol around the bead commit."""

from __future__ import annotations

import logging
import sys
import time
from typing import Any

from sase.bead.attachments.upload.errors import AttachmentTooLargeError

log = logging.getLogger(__name__)

# Public helpers from sibling modules resolve through the ``upload`` facade
# at call time, so monkeypatching ``sase.bead.attachments.upload.<name>``
# keeps working after the split.


def pre_write_upload(
    wires: list[dict[str, Any]],
    echo_rows: list[str],
    *,
    local_only: bool,
    bead_context: Any | None = None,
) -> tuple[str, dict[str, Any], str | None, bool]:
    """Decide placement and run the pre-write half of the upload protocol.

    Returns ``(placement, stores, project_key, require_upload)`` where
    *stores* maps every reachable tier name to its store. Local-only and
    no-store rows are rewritten in place; ``require_upload`` successes
    upload now (synchronously, even above the background threshold) and
    are rewritten with the destination. Exits non-zero before any bead
    write on oversize or missing-store refusal.
    """
    from sase.bead.attachments import upload
    from sase.bead.config import get_attachment_require_upload

    if not wires:
        return ("skip", {}, None, False)
    upload.drain_before_upload(bead_context)
    placement, stores, project_key = upload.prepare_placement(
        wires,
        local_only=local_only,
        bead_context=bead_context,
    )
    require_upload = get_attachment_require_upload()
    if placement in ("local_only", "no_store"):
        upload.rewrite_echo_for_local(echo_rows)
        return (placement, stores, project_key, require_upload)
    if require_upload:
        assert stores
        try:
            elapsed = upload.upload_wires_now(wires, stores)
        except Exception as exc:
            print(f"Error: attachment upload failed: {exc}", file=sys.stderr)
            sys.exit(1)
        first_store = next(iter(stores.values()))
        upload.rewrite_echo_for_upload(
            echo_rows, wires, label=first_store.describe(), elapsed=elapsed
        )
        return ("uploaded", stores, project_key, require_upload)
    return (placement, stores, project_key, require_upload)


def _store_identity(tier_name: str, store: Any) -> tuple[str, str]:
    """Return ``(store_repo, store_label)`` for one tier store."""
    if tier_name == "large":
        remote = str(getattr(store, "_remote", "") or store.describe())
        return (remote, store.describe())
    return (str(getattr(store, "_repo", "") or ""), store.describe())


def post_write_queue(
    mutation: Any,
    wires: list[dict[str, Any]],
    echo_rows: list[str],
    *,
    placement: str,
    stores: dict[str, Any] | Any | None,
    project_key: str | None,
    require_upload: bool,
) -> None:
    """Register a post-commit upload when placement chose a shared store.

    Wires route per tier; wires at or above the background threshold are
    marked for the detached worker instead of the inline post-commit
    upload. *stores* is the tier-name mapping from :func:`pre_write_upload`
    (a single store still works for one-tier placements).
    """
    from sase.bead.attachments import upload

    if not wires:
        return
    if placement not in ("git", "large", "mixed") or require_upload:
        return
    if not isinstance(stores, dict):
        stores = {"git": stores} if stores is not None else {}
    if not stores:
        return
    if project_key is None:
        project_key = upload.resolve_project_key(None)
        if project_key is None:
            return
    from sase.bead.attachments.background import should_background
    from sase.bead.config import get_attachment_git_max_bytes

    tiers = upload.placement_tiers(stores, git_max_bytes=get_attachment_git_max_bytes())
    try:
        grouped = upload.split_wires_by_tier(wires, tiers)
    except AttachmentTooLargeError as exc:
        log.warning("attachment post-write queue skipped: %s", exc)
        return
    for tier_name, tier_wires in grouped.items():
        store = stores.get(tier_name)
        if store is None:
            continue
        repo, label = _store_identity(tier_name, store)
        if tier_name == "git" and not repo:
            continue
        foreground = [
            wire
            for wire in tier_wires
            if not should_background(int(wire.get("size_bytes") or 0))
        ]
        background_wires = [
            wire
            for wire in tier_wires
            if should_background(int(wire.get("size_bytes") or 0))
        ]
        if foreground:
            upload.queue_pending_upload(
                mutation,
                foreground,
                store_name=tier_name,
                store_repo=repo,
                store_label=label,
                project_key=project_key,
                echo_rows=echo_rows,
            )
        if background_wires:
            upload.queue_pending_upload(
                mutation,
                background_wires,
                store_name=tier_name,
                store_repo=repo,
                store_label=label,
                project_key=project_key,
                echo_rows=echo_rows,
                background=True,
            )


def drain_before_upload(
    bead_context: Any | None = None,
    *,
    store: Any | None = None,
    time_bound_seconds: float = 5.0,
) -> None:
    """Opportunistically drain the outbox before a new upload; never raises."""
    from sase.bead.attachments import upload

    try:
        project_key = upload.resolve_project_key(bead_context)
        if not project_key:
            return
        if store is not None:
            actives = [store]
        else:
            actives = list(upload.discover_stores(bead_context).values())
        if not actives:
            return
        from sase.bead.attachments.outbox import drain_outbox

        for active in actives:
            drain_outbox(project_key, active, time_bound_seconds=time_bound_seconds)
    except Exception as exc:
        log.warning("attachment outbox opportunistic drain skipped: %s", exc)


def promote_local_only(
    project_key: str,
    stores: dict[str, Any] | Any,
    *,
    time_bound_seconds: float = 10.0,
) -> int:
    """Upload local-only objects referenced by current notes, if placeable.

    *stores* maps tier names to stores (a single store still means the git
    tier). Each object routes via the core placement policy, so big
    local-only objects promote to the large tier when it is configured.
    Returns the count promoted. Objects still rejected by placement stay
    local-only. Never raises.
    """
    from sase.bead.attachments import upload

    deadline = time.monotonic() + max(0.0, time_bound_seconds)
    if not isinstance(stores, dict):
        stores = {"git": stores} if stores is not None else {}
    if not stores:
        return 0
    try:
        from sase.bead.cli_common import get_read_view
        from sase.bead.config import get_attachment_git_max_bytes
        from sase.bead.attachments.outbox import read_outbox
        from sase.bead.attachments.store import LocalAttachmentStore
        from sase.bead.model import Status
        from sase.core.rust import require_rust_binding
    except Exception as exc:
        log.warning("attachment promote skipped: %s", exc)
        return 0
    try:
        git_max = get_attachment_git_max_bytes()
        placement = require_rust_binding("attachment_placement")
        tiers = upload.placement_tiers(stores, git_max_bytes=git_max)
        if not tiers:
            return 0
        try:
            queued = {entry.digest for entry in read_outbox(project_key)}
        except (OSError, ValueError):
            queued = set()
        local = LocalAttachmentStore()
        with get_read_view() as view:
            issues = view.list_issues(
                statuses=[
                    Status.OPEN,
                    Status.CLAIMED,
                    Status.READY,
                    Status.SNOOZED,
                    Status.IN_PROGRESS,
                    Status.CLOSED,
                ],
            )
        promoted = 0
        for issue in issues:
            if time.monotonic() >= deadline:
                break
            for note in getattr(issue, "notes", ()):
                for attachment in getattr(note, "attachments", ()):
                    if time.monotonic() >= deadline:
                        break
                    digest = str(getattr(attachment, "sha256", "") or "")
                    size = int(getattr(attachment, "size_bytes", 0) or 0)
                    if not digest or digest in queued:
                        continue
                    if not local.has(digest):
                        continue
                    try:
                        decision = placement(size, tiers, False)
                        tier_name = str(decision.get("store"))
                    except Exception:
                        continue
                    store = stores.get(tier_name)
                    if store is None:
                        continue
                    try:
                        if store.has(digest):
                            continue
                    except Exception:
                        continue
                    try:
                        store.put(digest, local.object_path(digest), size)
                    except Exception as exc:
                        log.warning(
                            "attachment promote of %s… failed: %s",
                            digest[:12],
                            exc,
                        )
                        continue
                    promoted += 1
        return promoted
    except Exception as exc:
        log.warning("attachment promote skipped: %s", exc)
        return 0


__all__ = [
    "drain_before_upload",
    "post_write_queue",
    "pre_write_upload",
    "promote_local_only",
]

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
    from sase.bead.config import (
        get_attachment_git_max_bytes,
        get_attachment_public_max_bytes,
        get_attachment_require_upload,
    )

    if not wires:
        return ("skip", {}, None, False)
    upload.drain_before_upload(bead_context)
    if local_only:
        upload.rewrite_echo_for_local(echo_rows)
        stores = upload.discover_stores(bead_context)
        project_key = upload.resolve_project_key(bead_context)
        return ("local_only", stores, project_key, get_attachment_require_upload())
    public_wires = [w for w in wires if str(w.get("visibility") or "") == "public"]
    private_wires = [w for w in wires if str(w.get("visibility") or "") != "public"]
    stores = upload.discover_stores(bead_context)
    project_key = upload.resolve_project_key(bead_context)
    require_upload = get_attachment_require_upload()
    git_max = get_attachment_git_max_bytes()
    try:
        public_max = get_attachment_public_max_bytes()
    except Exception:
        public_max = 26214400
    # Validate each audience against its own tiers; over-cap public bytes
    # have no next tier and never fall back onto git/large.
    if public_wires:
        public_tiers = upload.placement_tiers(
            stores,
            git_max_bytes=git_max,
            public_max_bytes=public_max,
            audience="public",
        )
        if not public_tiers:
            upload.rewrite_echo_for_public_pending(echo_rows, public_wires)
        else:
            try:
                upload.split_wires_by_tier(public_wires, public_tiers)
            except AttachmentTooLargeError:
                # Over-cap public bytes stay local; they never reach the
                # public remote and never fall back to private tiers.
                upload.rewrite_echo_for_local(echo_rows)
                public_wires = []
            else:
                # Reachable here; the post-write queue uploads them.
                pass
    if private_wires:
        private_tiers = upload.placement_tiers(
            stores,
            git_max_bytes=git_max,
            public_max_bytes=public_max,
            audience="private",
        )
        try:
            placement, _, _ = _prepare_audience_placement(
                private_wires,
                private_tiers,
                stores,
                project_key,
                require_upload=require_upload,
            )
        except (AttachmentTooLargeError, Exception) as exc:
            from sase.bead.attachments.upload.errors import (
                AttachmentStoreMissingError,
            )

            if isinstance(exc, AttachmentStoreMissingError):
                print(f"Error: {exc}", file=sys.stderr)
                sys.exit(1)
            if isinstance(exc, AttachmentTooLargeError):
                print(f"Error: {exc}", file=sys.stderr)
                sys.exit(1)
            raise
        if placement in ("local_only", "no_store"):
            if not public_wires:
                upload.rewrite_echo_for_local(echo_rows)
            if public_wires and not stores.get("public"):
                upload.rewrite_echo_for_public_pending(echo_rows, public_wires)
            return (placement, stores, project_key, require_upload)
    else:
        placement = "public" if public_wires else "skip"
        if placement == "public" and not stores.get("public"):
            upload.rewrite_echo_for_public_pending(echo_rows, public_wires)
            return ("public_pending", stores, project_key, require_upload)
        if placement == "public":
            return ("public", stores, project_key, require_upload)
    if not private_wires:
        return (placement, stores, project_key, require_upload)
    # Private placement name for the post-write queue.
    private_tiers = upload.placement_tiers(
        stores,
        git_max_bytes=git_max,
        public_max_bytes=public_max,
        audience="private",
    )
    try:
        grouped = upload.split_wires_by_tier(private_wires, private_tiers)
    except AttachmentTooLargeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
    names = sorted(grouped)
    private_placement = names[0] if len(names) == 1 else "mixed"
    if public_wires and stores.get("public") is None:
        upload.rewrite_echo_for_public_pending(echo_rows, public_wires)
    if require_upload:
        try:
            elapsed = upload.upload_wires_now(private_wires, stores)
        except Exception as exc:
            if getattr(exc, "secret_scan", False):
                try:
                    from sase.bead.attachments.upload.secret_scan import (
                        handle_secret_scan_rejection,
                    )
                    from sase.bead.attachments.outbox import OutboxEntry

                    for wire in private_wires:
                        digest = str(wire.get("sha256") or wire.get("digest") or "")
                        if not digest:
                            continue
                        handle_secret_scan_rejection(
                            project_key or "",
                            OutboxEntry(
                                digest=digest,
                                size_bytes=int(wire.get("size_bytes") or 0),
                                store="git",
                                mime_type=str(wire.get("mime_type") or "")
                                if isinstance(wire.get("mime_type"), str)
                                else None,
                            ),
                            stores.get("git"),
                            str(exc),
                        )
                except Exception:
                    pass
                print(f"Error: attachment upload failed: {exc}", file=sys.stderr)
                sys.exit(1)
            print(f"Error: attachment upload failed: {exc}", file=sys.stderr)
            sys.exit(1)
        # Upload public wires now as well when require_upload is set and
        # the public store is reachable; otherwise they stay queued.
        if public_wires and stores.get("public") is not None:
            try:
                public_elapsed = upload.upload_wires_now(public_wires, stores)
            except Exception as exc:
                if getattr(exc, "secret_scan", False):
                    try:
                        from sase.bead.attachments.upload.secret_scan import (
                            handle_secret_scan_rejection,
                        )
                        from sase.bead.attachments.outbox import OutboxEntry

                        for wire in public_wires:
                            digest = str(wire.get("sha256") or wire.get("digest") or "")
                            if not digest:
                                continue
                            handle_secret_scan_rejection(
                                project_key or "",
                                OutboxEntry(
                                    digest=digest,
                                    size_bytes=int(wire.get("size_bytes") or 0),
                                    store="public",
                                    mime_type=str(wire.get("mime_type") or "")
                                    if isinstance(wire.get("mime_type"), str)
                                    else None,
                                ),
                                stores.get("public"),
                                str(exc),
                            )
                            wire["visibility"] = "private"
                    except Exception:
                        pass
                    # Fall back to the private tiers for the rejected wires.
                    try:
                        fallback_elapsed = upload.upload_wires_now(public_wires, stores)
                        elapsed.update(fallback_elapsed)
                    except Exception:
                        pass
                    first_store = next(iter(stores.values()))
                    upload.rewrite_echo_for_upload(
                        echo_rows,
                        wires,
                        label=first_store.describe(),
                        elapsed=elapsed,
                    )
                    return ("uploaded", stores, project_key, require_upload)
                print(f"Error: attachment upload failed: {exc}", file=sys.stderr)
                sys.exit(1)
            elapsed.update(public_elapsed)
            first_store = next(iter(stores.values()))
            upload.rewrite_echo_for_upload(
                echo_rows,
                wires,
                label=first_store.describe(),
                elapsed=elapsed,
            )
        else:
            first_store = next(iter(stores.values())) if stores else None
            if first_store is not None:
                upload.rewrite_echo_for_upload(
                    echo_rows,
                    private_wires,
                    label=first_store.describe(),
                    elapsed=elapsed,
                )
            if public_wires:
                upload.rewrite_echo_for_public_pending(echo_rows, public_wires)
        return ("uploaded", stores, project_key, require_upload)
    # Mixed audience: the post-write queue handles each audience.
    if public_wires and private_wires:
        return ("mixed", stores, project_key, require_upload)
    if public_wires:
        return ("public", stores, project_key, require_upload)
    return (private_placement, stores, project_key, require_upload)


def _prepare_audience_placement(
    wires: list[dict[str, Any]],
    tiers: list[dict[str, Any]],
    stores: dict[str, Any],
    project_key: str | None,
    *,
    require_upload: bool,
) -> tuple[str, dict[str, Any], str | None]:
    from sase.bead.attachments import upload

    _ = stores
    placement = upload.decide_placement(
        wires,
        tiers,
        local_only=False,
        require_upload=require_upload,
    )
    return (placement, stores, project_key)


def _queue_public_wires(
    mutation: Any,
    public_wires: list[dict[str, Any]],
    echo_rows: list[str],
    project_key: str | None,
) -> None:
    """Queue public wires for the public store (no fallback)."""
    from sase.bead.attachments import upload

    if project_key is None:
        project_key = upload.resolve_project_key(None)
        if project_key is None:
            return
    for wire in public_wires:
        digest = str(wire.get("sha256") or wire.get("digest") or "")
        if not digest:
            continue
        pending = getattr(mutation, "pending_attachment_uploads", None)
        if pending is None:
            pending = []
            mutation.pending_attachment_uploads = pending
        item: dict[str, Any] = {
            "digest": digest,
            "size_bytes": int(wire.get("size_bytes") or 0),
            "store_name": "public",
            "store_repo": "",
            "store_label": "public attachments sidecar",
            "project_key": project_key,
            "background": False,
        }
        mime_value = wire.get("mime_type")
        if isinstance(mime_value, str) and mime_value:
            item["mime_type"] = mime_value
        pending.append(item)
    mutation.pending_attachment_echo_rows = echo_rows
    mutation.pending_attachment_wires = list(public_wires)


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
    if placement == "public_pending":
        public_wires = [w for w in wires if str(w.get("visibility") or "") == "public"]
        if not public_wires:
            return
        if project_key is None:
            project_key = upload.resolve_project_key(None)
            if project_key is None:
                return
        for wire in public_wires:
            digest = str(wire.get("sha256") or wire.get("digest") or "")
            if not digest:
                continue
            pending = getattr(mutation, "pending_attachment_uploads", None)
            if pending is None:
                pending = []
                mutation.pending_attachment_uploads = pending
            item: dict[str, Any] = {
                "digest": digest,
                "size_bytes": int(wire.get("size_bytes") or 0),
                "store_name": "public",
                "store_repo": "",
                "store_label": "public attachments sidecar",
                "project_key": project_key,
                "background": False,
            }
            mime_value = wire.get("mime_type")
            if isinstance(mime_value, str) and mime_value:
                item["mime_type"] = mime_value
            pending.append(item)
        mutation.pending_attachment_echo_rows = echo_rows
        mutation.pending_attachment_wires = list(wires)
        return
    if placement not in ("git", "large", "mixed", "public") or require_upload:
        # Public placements queue below; uploaded/skip/local_only queue nothing.
        if placement != "public" or require_upload:
            if placement not in ("mixed",):
                return
    if not isinstance(stores, dict):
        stores = {"git": stores} if stores is not None else {}
    if not stores:
        # Still queue public wires for a missing public store.
        public_wires = [w for w in wires if str(w.get("visibility") or "") == "public"]
        if public_wires:
            _queue_public_wires(mutation, public_wires, echo_rows, project_key)
        return
    if project_key is None:
        project_key = upload.resolve_project_key(None)
        if project_key is None:
            return
    public_wires = [w for w in wires if str(w.get("visibility") or "") == "public"]
    private_wires = [w for w in wires if str(w.get("visibility") or "") != "public"]
    if public_wires:
        public_store = stores.get("public")
        if public_store is not None:
            repo, label = _store_identity("public", public_store)
            # A public row written before the clone existed drains after
            # materialization; keep the empty repo to resolve via discovery.
            if not repo:
                repo = ""
                label = label or "public attachments sidecar"
            from sase.bead.attachments.background import should_background

            foreground = [
                wire
                for wire in public_wires
                if not should_background(int(wire.get("size_bytes") or 0))
            ]
            background_wires = [
                wire
                for wire in public_wires
                if should_background(int(wire.get("size_bytes") or 0))
            ]
            if foreground:
                upload.queue_pending_upload(
                    mutation,
                    foreground,
                    store_name="public",
                    store_repo=repo,
                    store_label=label,
                    project_key=project_key,
                    echo_rows=echo_rows,
                )
            if background_wires:
                upload.queue_pending_upload(
                    mutation,
                    background_wires,
                    store_name="public",
                    store_repo=repo,
                    store_label=label,
                    project_key=project_key,
                    echo_rows=echo_rows,
                    background=True,
                )
        else:
            _queue_public_wires(mutation, public_wires, echo_rows, project_key)
    wires = private_wires
    if not wires:
        return
    from sase.bead.attachments.background import should_background
    from sase.bead.config import get_attachment_git_max_bytes

    tiers = upload.placement_tiers(
        stores,
        git_max_bytes=get_attachment_git_max_bytes(),
        audience="private",
    )
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
        tiers = upload.placement_tiers(
            stores,
            git_max_bytes=git_max,
            audience="private",
        )
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
